"""Publish an RSS feed of newly announced concerts.

Where the .ics answers "what's my whole upcoming calendar", the RSS feed
answers "what got announced recently" -- so followers find out when a new
concert is added. We feed it the events the store flagged as newly seen,
falling back to soonest-upcoming so the feed is never empty on first run.
"""

from __future__ import annotations

from pathlib import Path

from feedgen.feed import FeedGenerator

from dateformat import fmt
from models import Event


def write_rss(events: list[Event], out: Path, *, title: str, site_url: str) -> Path:
    fg = FeedGenerator()
    fg.id(site_url)
    fg.title(title)
    fg.link(href=site_url, rel="alternate")
    fg.description("Newly announced classical concerts in the Omaha area")
    fg.language("en")

    for ev in events:
        fe = fg.add_entry()
        fe.id(ev.uid)
        prefix = {"online": "[Online] ", "broadcast": "[Broadcast] "}.get(ev.channel, "")
        fe.title(f"{prefix}{ev.title} — {fmt(ev.start, '%b %-d, %Y')}")
        if ev.url:
            fe.link(href=ev.url)
        parts = []
        if ev.venue:
            parts.append(ev.venue)
        parts.append(fmt(ev.start, "%A, %B %-d, %Y · %-I:%M %p"))
        if ev.description:
            parts.append(ev.description)
        parts.append(f"Source: {ev.source}")
        fe.description("\n".join(parts))
        # pubDate = when we first saw the announcement, so readers get
        # items in discovery order (fallback: the event's own start).
        from datetime import timezone
        stamp = ev.first_seen or ev.start
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        fe.pubDate(stamp)

    fg.rss_file(str(out), pretty=True)
    return out
