"""Reusable adapter: fetch web pages, extract concerts with an LLM.

For sources with no feed and no regular markup -- where a hand-written
parser would be brittle guesswork -- fetch the page, strip it to readable
text, and ask a model to return structured events.

Three things make this practical rather than expensive:

1. BOILERPLATE STRIPPING. Squarespace and friends repeat their whole nav
   several times per page; on the Omaha Chamber Music pages the navigation
   outweighs the actual concert listings many times over. Sending that raw
   would cost more, and bury the real content in noise. `_readable_text`
   drops nav/header/footer/script and collapses repeated lines first.

2. CONTENT-HASH CACHING. The WCH adapter caches per toot URL because each
   post is immutable. Here the URL is constant and the *content* changes, so
   the cache key is a hash of the extracted text. Re-running costs nothing
   until the page actually changes -- which for a season page is a few times
   a year.

3. A PROMPT THAT ALLOWS "NOTHING". The commonest failure of LLM extraction
   is inventing events from an empty page. The prompt demands an empty list
   when there are no concerts, and requires dates to be copied, not guessed.

Live use needs ANTHROPIC_API_KEY; `--offline` uses the fixture and makes no
API call.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as dtparse

from adapters.base import Adapter
from models import Event

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5"

_PROMPT = """Below is the readable text of a concert-presenter web page.

Extract every SPECIFIC, DATED concert performance you can find.

Rules:
- Return ONLY a JSON array. No prose, no markdown fences.
- Each item: {{"title": str, "date": "YYYY-MM-DD", "time": "HH:MM" or null,
  "venue": str or null, "description": str or null}}
- COPY dates and times from the page. Never guess or infer a date that is
  not written there. If a date has no year, use the year the page states.
- A series may announce dates before announcing programs. If a date is
  listed with no program, still return it, with a descriptive title such as
  "{series_hint} concert" and description noting the program is TBA.
- Ignore navigation, ticket links, donation appeals, past-season archives,
  and anything that is not a dated performance.
- If the page contains NO dated concerts, return exactly: []

Page URL: {url}
Page text:
---
{text}
---"""


class LLMPageExtractAdapter(Adapter):
    """Extract events from one or more pages using an LLM."""

    fixture_ext = "json"

    def __init__(self, name: str, source_label: str, urls: list[str],
                 channel: str = "local", category: str | None = None,
                 series_hint: str = "Concert", default_venue: str | None = None,
                 cache_path: str | None = None):
        self.name = name
        self.source_label = source_label
        self.urls = urls
        self.channel = channel
        self.category = category
        self.series_hint = series_hint
        self.default_venue = default_venue
        self.cache_path = cache_path or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), f"{name}_cache.json")

    # --- fetch -----------------------------------------------------------
    def fetch_raw(self) -> Any:
        pages = []
        for url in self.urls:
            html = self._get(url).text
            pages.append({"url": url, "text": _readable_text(html)})
        return {"pages": pages}

    # --- parse -----------------------------------------------------------
    def parse(self, raw: Any) -> list[Event]:
        # Offline fixture: already-extracted events.
        if isinstance(raw, dict) and "events" in raw:
            return [self._build(r) for r in raw["events"] if r.get("date")]
        if isinstance(raw, list):
            return [self._build(r) for r in raw if r.get("date")]

        cache = self._load_cache()
        dirty = False
        events: list[Event] = []
        for page in raw.get("pages", []):
            key = hashlib.sha1(page["text"].encode()).hexdigest()
            if key in cache:
                rows = cache[key]
            else:
                rows = self._extract(page)
                cache[key] = rows
                dirty = True
            events.extend(self._build(r) for r in rows if r.get("date"))
        if dirty:
            self._save_cache(cache)
        return events

    def _build(self, r: dict) -> Event:
        stamp = f"{r['date']} {r.get('time') or '00:00'}"
        return Event(
            title=(r.get("title") or f"{self.series_hint} concert").strip(),
            start=dtparse.parse(stamp),
            venue=r.get("venue") or self.default_venue,
            url=r.get("url") or (self.urls[0] if self.urls else None),
            description=r.get("description"),
            category=self.category,
            source=self.source_label,
        )

    # --- LLM -------------------------------------------------------------
    def _extract(self, page: dict) -> list[dict]:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                f"{self.source_label} live extraction needs ANTHROPIC_API_KEY "
                "(run with --offline to use the fixture instead)."
            )
        prompt = _PROMPT.format(url=page["url"], text=page["text"][:20000],
                                series_hint=self.series_hint)
        resp = httpx.post(
            API_URL,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": MODEL, "max_tokens": 2000,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        resp.raise_for_status()
        text = "".join(b.get("text", "") for b in resp.json().get("content", []))
        rows = _parse_json_array(text)
        for r in rows:
            r.setdefault("url", page["url"])
        return rows

    def _load_cache(self) -> dict:
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self, cache: dict) -> None:
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=1)
        except OSError:
            pass  # cache is an optimization, never fatal


def _readable_text(html: str) -> str:
    """Strip a page to its readable content.

    Squarespace repeats the full navigation several times per page; without
    this the nav dominates the prompt and buries the concerts.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    # Collapse duplicate lines (repeated menus) while preserving order.
    seen: set[str] = set()
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)


def _parse_json_array(text: str) -> list[dict]:
    """Tolerantly pull a JSON array out of a model response."""
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)]
