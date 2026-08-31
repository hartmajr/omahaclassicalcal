"""Publish the static website -- data-driven tabs, one per channel.

Given a list of channel groups (In Omaha / Online / Broadcasts / ...), this
renders one tab and one subscribe link per group. Adding a channel in
config.py automatically adds a tab here; nothing in this file is hardcoded
to a specific set. Self-contained: inline CSS + a few lines of vanilla JS
for the toggle, no build step, no external deps.
"""

from __future__ import annotations

import html
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dateformat import fmt
from models import Event

try:
    from zoneinfo import ZoneInfo
    _LOCAL_TZ = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover
    _LOCAL_TZ = None


def _local(dt):
    """Render tz-aware datetimes (e.g. WCH's GMT broadcasts) in Omaha time.

    Naive datetimes are assumed already-local and pass through. Without this,
    an 18:00 GMT broadcast displays as '6:00 PM' when it actually airs at
    1:00 PM Central -- the single worst error a broadcast calendar can make.
    """
    if dt.tzinfo is not None and _LOCAL_TZ is not None:
        return dt.astimezone(_LOCAL_TZ)
    return dt

_CSS = """
:root { --ink:#1a1a1a; --muted:#6b6b6b; --line:#e6e3dc; --accent:#7a3b2e; --bg:#faf8f4; }
* { box-sizing:border-box; }
body { font:16px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
       color:var(--ink); background:var(--bg); margin:0; padding:0 20px 60px; }
.wrap { max-width:720px; margin:0 auto; }
header { padding:48px 0 20px; border-bottom:2px solid var(--ink); }
h1 { font-size:30px; margin:0 0 6px; letter-spacing:-.01em; }
.sub { color:var(--muted); margin:0; }
.tabs { display:flex; gap:6px; margin:24px 0 0; flex-wrap:wrap; }
.tab { border:1px solid var(--line); background:none; font:inherit; font-weight:600;
       color:var(--muted); padding:8px 16px; border-radius:8px 8px 0 0; cursor:pointer; }
.tab[aria-selected=true] { color:var(--ink); border-bottom-color:var(--bg); background:#fff; }
.panel { display:none; }
.panel.active { display:block; }
.subscribe { margin:16px 0 0; font-size:14px; }
.subscribe a { color:var(--accent); text-decoration:none; border:1px solid var(--line);
       padding:6px 12px; border-radius:6px; margin-right:8px; display:inline-block; }
.intro { font-size:14px; color:var(--muted); margin:12px 0 0; }
h2 { font-size:14px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted);
     margin:32px 0 0; padding-bottom:8px; border-bottom:1px solid var(--line); }
.event { padding:18px 0; border-bottom:1px solid var(--line); display:flex; gap:18px; }
.date { flex:0 0 64px; text-align:center; }
.date .d { font-size:24px; font-weight:600; line-height:1; }
.date .m { font-size:12px; text-transform:uppercase; color:var(--muted); }
.body { flex:1; }
.title { font-weight:600; margin:0 0 2px; }
.title a { color:var(--ink); text-decoration:none; }
.title a:hover { color:var(--accent); }
.meta { font-size:14px; color:var(--muted); }
.src { font-size:12px; color:var(--accent); }
.pill { font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:#3a6b5f;
        border:1px solid #cfe3dc; border-radius:4px; padding:1px 6px; margin-left:6px; }
.banner { background:#fdf3e3; border:1px solid #ecd9b0; color:#7a5b1e; border-radius:8px;
          padding:10px 14px; font-size:14px; margin:20px 0 0; }
footer { margin-top:48px; font-size:13px; color:var(--muted); }
"""

_JS = """
document.querySelectorAll('.tab').forEach(function(t){
  t.addEventListener('click', function(){
    document.querySelectorAll('.tab').forEach(function(x){x.setAttribute('aria-selected','false');});
    document.querySelectorAll('.panel').forEach(function(p){p.classList.remove('active');});
    t.setAttribute('aria-selected','true');
    document.getElementById(t.dataset.panel).classList.add('active');
  });
});
"""

# Per-channel intro line + pill label shown on the tab's events.
_CHANNEL_META = {
    "local":     ("Classical concerts happening in person around Omaha.", None),
    "online":    ("Streamed performances you can watch from anywhere.", "stream"),
    "lincoln":   ("Classical concerts in Lincoln, about an hour down I-80.", None),
    "broadcast": ("Curated live classical broadcasts from concert halls worldwide.", "broadcast"),
}


def _events_html(events: list[Event], pill_label: str | None) -> str:
    by_month: dict[str, list[Event]] = defaultdict(list)
    for ev in events:
        by_month[_local(ev.start).strftime("%B %Y")].append(ev)
    rows = []
    for month, evs in by_month.items():
        rows.append(f"<h2>{html.escape(month)}</h2>")
        for ev in evs:
            start = _local(ev.start)
            open_a = f'<a href="{html.escape(ev.url)}">' if ev.url else ""
            close_a = "</a>" if ev.url else ""
            pill = f'<span class="pill">{pill_label}</span>' if pill_label else ""
            meta = [fmt(start, "%a · %-I:%M %p")]
            if ev.venue:
                meta.append(html.escape(ev.venue))
            rows.append(f"""
            <div class="event">
              <div class="date"><div class="d">{fmt(start, '%-d')}</div>
                <div class="m">{start.strftime('%b')}</div></div>
              <div class="body">
                <p class="title">{open_a}{html.escape(ev.title)}{close_a}{pill}</p>
                <p class="meta">{' · '.join(meta)}</p>
                <p class="src">{html.escape(ev.source)}</p>
              </div>
            </div>""")
    return "".join(rows) if rows else "<p>No upcoming events.</p>"


def write_site(groups: list[dict], out: Path, *, title: str, rss_name: str,
               generated: datetime, demo: bool = False,
               demo_note: str | None = None, unlisted: bool = False) -> Path:
    """groups: list of {id, label, ics, events} in display order."""
    banner = ""
    if demo:
        note = demo_note or ('<strong>Demo build.</strong> This page was '
                  'generated from offline sample data (fixtures). Some events are '
                  'illustrative and links may not work. Run the pipeline without '
                  '<code>--offline</code> to publish real, live events.')
        banner = f'<p class="banner">{note}</p>'
    tabs, panels = [], []
    for i, g in enumerate(groups):
        intro, pill = _CHANNEL_META.get(g["id"], ("", None))
        sel = "true" if i == 0 else "false"
        active = " active" if i == 0 else ""
        tabs.append(
            f'<button class="tab" role="tab" aria-selected="{sel}" '
            f'data-panel="p-{g["id"]}">{html.escape(g["label"])} ({len(g["events"])})</button>'
        )
        rss_link = f'<a href="{rss_name}">RSS</a>' if i == 0 else ""
        panels.append(f"""
<div class="panel{active}" id="p-{g['id']}">
  <p class="subscribe"><a href="{g['ics']}">Subscribe (iCal)</a>{rss_link}</p>
  <p class="intro">{html.escape(intro)}</p>
  {_events_html(g['events'], pill)}
</div>""")

    summary = " · ".join(f"{len(g['events'])} {g['label'].lower()}" for g in groups)
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{'<meta name="robots" content="noindex, nofollow">' if unlisted else ''}
<title>{html.escape(title)}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header>
  <h1>{html.escape(title)}</h1>
  <p class="sub">Classical concerts in Omaha, streamed performances, and live broadcasts worldwide.</p>
  {banner}
  <div class="tabs" role="tablist">
    {''.join(tabs)}
  </div>
</header>
{''.join(panels)}
<footer>Updated {fmt(generated, '%B %-d, %Y')} · {summary} ·
  Each event links back to its source.</footer>
</div><script>{_JS}</script></body></html>"""
    # Explicit UTF-8: Windows defaults write_text to cp1252, which cannot
    # encode names like Dvořák.
    out.write_text(doc, encoding="utf-8")
    return out
