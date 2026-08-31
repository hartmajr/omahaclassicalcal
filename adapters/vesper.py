"""Vesper Concerts -- Omaha's longest-running chamber music series.

vesperconcerts.org is WordPress, but concerts are ordinary *pages*, not
calendar events: there is no Events Calendar plugin, no .ics, no REST
events endpoint. The season page instead lists each concert as an image
tile plus two text lines:

    Emanuel Ax, piano
    Tuesday, September 8, 2026 @ 7 PM
    [Learn More] -> https://vesperconcerts.org/emanuel-ax/

So this is an HTML parse, like the Symphony adapter. The upside is that the
markup is regular and the series is small (7-8 concerts a season), so a
tolerant parser plus a date regex handles it.

Every Vesper concert is free and at the same venue (Presbyterian Church of
the Cross), except occasional outdoor editions, so the venue is a constant
with a note in the description rather than something we try to scrape.

Selectors verified against the live page 2026-08-31 (all 7 Season 38
concerts parsed; the site is WordPress + Divi, see _from_html). The
offline fixture holds the real captured Season 38, so the rest of the
pipeline is exercised correctly either way.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from dateutil import parser as dtparse

from adapters.base import Adapter
from models import Event

SEASON_URL = "https://vesperconcerts.org/"
VENUE = "Presbyterian Church of the Cross"

# "Tuesday, September 8, 2026 @ 7 PM"  /  "Sunday, November 15 @ 7 PM"
# The year is optional on the page, so infer it from the season when absent.
_DATE_RE = re.compile(
    r"(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,\s*)?"
    r"([A-Z][a-z]+)\s+(\d{1,2})(?:,\s*(\d{4}))?\s*@\s*(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?",
    re.IGNORECASE,
)


class VesperAdapter(Adapter):
    name = "vesper_concerts"
    source_label = "Vesper Concerts"
    channel = "local"
    fixture_ext = "json"

    def fetch_raw(self) -> Any:
        return self._get(SEASON_URL).text

    def parse(self, raw: Any) -> list[Event]:
        if isinstance(raw, (list, dict)):
            rows = raw["concerts"] if isinstance(raw, dict) else raw
            return [self._build(r) for r in rows if self._parse_date(r["date_text"])]
        return self._from_html(raw)

    def _from_html(self, html: str) -> list[Event]:
        # Verified against the live page 2026-08-31. WordPress + Divi: each
        # concert is one div.et_pb_column stacking modules --
        #   image module    <a href=".../emanuel-ax/"><img title="Emanuel Ax">
        #   text module     "Emanuel Ax, piano"          <- the title we want
        #   text module     "All Seats Reserved"          (sometimes)
        #   text module     "Tuesday, September 8, 2026 @ 7 PM"
        #   button module   "Learn More" -> same /emanuel-ax/ link
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        seen: set[str] = set()
        for col in soup.select("div.et_pb_column"):
            text = re.sub(r"\s+", " ", col.get_text(" ", strip=True))
            m = _DATE_RE.search(text)
            if not m:
                continue
            link = col.find(
                "a", href=re.compile(r"^https?://vesperconcerts\.org/[^/?#]+/?$"))
            # Title: the first text module that is neither the date line nor
            # a ticketing note; fall back to the tile image's title attr.
            title = ""
            for inner in col.select(".et_pb_text_inner"):
                t = re.sub(r"\s+", " ", inner.get_text(" ", strip=True))
                if not t or _DATE_RE.search(t):
                    continue
                if re.search(r"seats reserved|learn more|tickets", t, re.IGNORECASE):
                    continue
                title = t
                break
            if not title:
                img = col.find("img")
                title = (img.get("title") or img.get("alt") or "").strip() if img else ""
            key = f"{title}|{m.group(0)}"
            if not title or key in seen:
                continue
            seen.add(key)
            events.append(self._build({
                "title": title, "date_text": m.group(0),
                "url": link["href"] if link else None,
                "description": None,
            }))
        return events

    def _build(self, r: dict) -> Event:
        start = self._parse_date(r["date_text"])
        outdoor = "outdoor" in r["title"].lower()
        desc = r.get("description") or ""
        note = "Free and open to the public."
        return Event(
            title=r["title"].strip(),
            start=start,
            venue=r.get("venue") or (None if outdoor else VENUE),
            url=r.get("url"),
            description=(desc + " " + note).strip(),
            category="Chamber Music",
            source=self.source_label,
        )

    def _parse_date(self, date_text: str) -> datetime | None:
        m = _DATE_RE.search(date_text)
        if not m:
            return None
        month, day, year, hour, minute, ampm = m.groups()
        year = year or str(_season_year(month))
        stamp = f"{month} {day} {year} {hour}:{minute or '00'} {ampm.upper()}M"
        try:
            return dtparse.parse(stamp)
        except (ValueError, OverflowError):
            return None


def _season_year(month_abbr: str) -> int:
    """Vesper's season spans two calendar years and the page often omits the
    year on spring dates, so map Jan-Jun to next year when we're past them."""
    now = datetime.now()
    try:
        m = dtparse.parse(f"{month_abbr} 1").month
    except ValueError:
        return now.year
    return now.year if m >= now.month else now.year + 1
