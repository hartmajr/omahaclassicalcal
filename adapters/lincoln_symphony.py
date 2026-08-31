"""Lincoln's Symphony Orchestra -- season-page HTML parse.

lincolnsymphony.com is WordPress with concerts as ordinary pages; there is
no calendar plugin, no .ics, no events REST endpoint. The "Season at a
Glance" page lists every concert as a card:

    Mozart & Haydn
    Friday, October 9, 2026, 7:30PM
    Saint Paul United Methodist Church

Two structural wrinkles, both real in the current season:
  - "Organ Celebration" runs on TWO dates (Apr 30 & May 1).
  - "Deck the Halls" runs TWICE IN ONE DAY (2:00PM & 6:00PM).
So a card can yield several events, and the second case means dates alone
don't disambiguate -- repeats are labelled with date *and* time.

LSO publishes no series labels on this page (unlike the Omaha Symphony's
Masterworks / LIVE tags), so pops and film nights can only be identified
from their titles. That is what the film/pops keyword vetoes in config.py
are for; see the README note about the limits of that.

HONESTY NOTE: live CSS selectors are a documented best-effort; verify
against page source. The offline fixture holds the real captured season.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from dateutil import parser as dtparse

from adapters.base import Adapter
from dateformat import fmt
from models import Event

SEASON_URL = "https://lincolnsymphony.com/season-at-a-glance/"

# "Friday, October 9, 2026, 7:30PM" / "Sunday, December 6, 2026, 2:00PM & 6:00PM"
# / "Friday, April 30 & Saturday, May 1, 2027, 7:30PM"
_DATE_RE = re.compile(
    r"([A-Z][a-z]+)\s+(\d{1,2})(?:,\s*(\d{4}))?", re.UNICODE)
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?", re.IGNORECASE)
_MONTHS = {"january","february","march","april","may","june","july",
           "august","september","october","november","december"}


class LincolnSymphonyAdapter(Adapter):
    name = "lincoln_symphony"
    source_label = "Lincoln's Symphony Orchestra"
    channel = "lincoln"
    fixture_ext = "json"

    def fetch_raw(self) -> Any:
        return self._get(SEASON_URL).text

    def parse(self, raw: Any) -> list[Event]:
        if isinstance(raw, (list, dict)):
            rows = raw["concerts"] if isinstance(raw, dict) else raw
            return [e for r in rows for e in self._expand(r)]
        return self._from_html(raw)

    def _from_html(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        seen: set[str] = set()
        for heading in soup.find_all(["h2", "h3"]):
            title = heading.get_text(strip=True)
            if not title or title in seen:
                continue
            block = heading.find_parent(["div", "section", "article"]) or heading.parent
            text = block.get_text("\n", strip=True)
            # The date/venue lines follow the heading inside the same card.
            after = text.split(title, 1)[-1]
            line = " ".join(after.splitlines()[:3])
            if not self._dates(line):
                continue
            seen.add(title)
            link = heading.find("a") or block.find("a", href=True)
            venue = None
            for cand in after.splitlines():
                if any(k in cand for k in ("Center", "Hall", "Church", "Theater")):
                    venue = cand.strip()
                    break
            events.extend(self._expand({
                "title": title, "date_text": line, "venue": venue,
                "url": link["href"] if link and link.has_attr("href") else None,
            }))
        return events

    def _expand(self, r: dict) -> list[Event]:
        starts = self._dates(r["date_text"])
        events = []
        multi = len(starts) > 1
        for start in starts:
            title = r["title"].strip()
            if multi:
                # Two shows can share a date (Deck the Halls 2pm & 6pm), so
                # include the time. Keep minutes when they're not :00 --
                # labelling a 7:30 concert "7pm" would be plainly wrong.
                pat = "%b %-d, %-I%p" if start.minute == 0 else "%b %-d, %-I:%M%p"
                title = f"{title} ({fmt(start, pat)})".replace("AM", "am").replace("PM", "pm")
            events.append(Event(
                title=title,
                start=start,
                venue=r.get("venue"),
                url=r.get("url"),
                description=r.get("description"),
                category=r.get("category"),
                source=self.source_label,
            ))
        return events

    def _dates(self, text: str) -> list[datetime]:
        """Expand a card's date line into every performance datetime."""
        if not text:
            return []
        year_m = re.search(r"(20\d{2})", text)
        year = year_m.group(1) if year_m else str(datetime.now().year)
        days = [(m.group(1), m.group(2)) for m in _DATE_RE.finditer(text)
                if m.group(1).lower() in _MONTHS]
        times = _TIME_RE.findall(text)
        if not days or not times:
            return []
        out: list[datetime] = []
        # One time for all dates (Apr 30 & May 1 @ 7:30) OR several times on
        # one date (Dec 6 @ 2pm & 6pm). Both appear in the real season.
        pairs = ([(d, t) for d in days for t in times] if len(days) == 1 or len(times) == 1
                 else list(zip(days, times)))
        for (month, day), (hour, minute, ampm) in pairs:
            try:
                out.append(dtparse.parse(
                    f"{month} {day} {year} {hour}:{minute or '00'} {ampm.upper()}M"))
            except (ValueError, OverflowError):
                continue
        return sorted(set(out))
