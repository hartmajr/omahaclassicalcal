"""Lied Center for Performing Arts -- Lincoln's presenting venue.

UNL's performing-arts presenter: touring orchestras, chamber ensembles, and
recitalists share the season with Broadway tours, comedians, and pop acts,
so the classifier does real filtering here (the source's default verdict is
non-classical -- see SOURCE_PRIORITY in config.py).

The site is Drupal; /events (-> /events-page) renders every upcoming event
as a Views row (verified against the live page 2026-09-01):

    <div class="views-row ...">
      <div class="event-type">Season Event</div>
      <div class="title"><a href="/event/daniil-trifonov">Daniil Trifonov</a></div>
      <div class="date">March 22, 2027</div>
      <div class="body"><p>teaser prose...</p></div>

Dates are day-precision only ("October 1, 2026", ranges like
"September 25-26, 2026" or "May 31-June 2, 2027"); showtimes live behind
each /event/ page. Fetching 50 detail pages against their 10-second
robots.txt crawl-delay would take ~10 minutes per run, so events publish
as all-day entries with the detail link one click away. robots.txt allows
event pages; we make one listing-page request per run.

Lincoln's Symphony concerts at the Lied are skipped here: LSO's own
adapter is their source of record (with showtimes), and the Lied lists
them under different titles ("Emanuel Ax with Lincoln's Symphony
Orchestra" vs LSO's "Emanuel Ax"), which defeats fuzzy dedupe.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from dateutil import parser as dtparse

from adapters.base import Adapter
from models import Event

EVENTS_URL = "https://www.liedcenter.org/events-page"
SITE = "https://www.liedcenter.org"
VENUE = "Lied Center for Performing Arts"

# "October 1, 2026" / "September 25-26, 2026" / "May 31-June 2, 2027"
_DATE_RE = re.compile(
    r"([A-Z][a-z]+)\s+(\d{1,2})(?:\s*[-–]\s*(?:([A-Z][a-z]+)\s+)?(\d{1,2}))?,\s*(\d{4})"
)


class LiedCenterAdapter(Adapter):
    name = "lied_center"
    source_label = "Lied Center for Performing Arts"
    channel = "lincoln"
    fixture_ext = "json"

    def fetch_raw(self) -> Any:
        return self._get(EVENTS_URL).text

    def parse(self, raw: Any) -> list[Event]:
        rows = raw if isinstance(raw, list) else self._rows_from_html(raw)
        events = []
        for r in rows:
            ev = self._build(r)
            if ev:
                events.append(ev)
        return events

    def _rows_from_html(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        rows: list[dict] = []
        for card in soup.select("div[class*=views-row]"):
            title_el = card.select_one(".title a")
            date_el = card.select_one(".date")
            if not title_el or not date_el:
                continue
            body_el = card.select_one(".body p")
            type_el = card.select_one(".event-type")
            href = title_el.get("href") or ""
            rows.append({
                "title": title_el.get_text(" ", strip=True),
                "date_text": date_el.get_text(" ", strip=True),
                "url": SITE + href if href.startswith("/") else href,
                "description": body_el.get_text(" ", strip=True) if body_el else None,
                "event_type": type_el.get_text(strip=True) if type_el else None,
            })
        return rows

    def _build(self, r: dict) -> Event | None:
        title = re.sub(r"\s+", " ", r["title"]).strip()
        # LSO concerts at the Lied come from LSO's own adapter (see module
        # docstring); the apostrophe varies between ' and ’ on the page.
        if "lincoln's symphony" in title.lower().replace("’", "'"):
            return None
        start, end = self._dates(r["date_text"])
        if not start:
            return None
        return Event(
            title=title,
            start=start,
            end=end,
            venue=VENUE,
            url=r.get("url"),
            description=r.get("description"),
            category=r.get("event_type"),
            all_day=True,
            source=self.source_label,
        )

    def _dates(self, text: str) -> tuple[datetime | None, datetime | None]:
        m = _DATE_RE.search(text or "")
        if not m:
            return None, None
        m1, d1, m2, d2, year = m.groups()
        try:
            start = dtparse.parse(f"{m1} {d1} {year}")
            end = dtparse.parse(f"{m2 or m1} {d2} {year}") if d2 else None
        except (ValueError, OverflowError):
            return None, None
        return start, end
