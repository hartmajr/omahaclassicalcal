"""Gallery 1516 -- "Bagels & Sometimes Bach", parsed from a Squarespace page.

An Omaha art gallery (1516 Leavenworth St) whose free Sunday-morning
series puts local classical players in the room: Omaha Chamber Music
Society, Opera Omaha, the Conservatory, UNO faculty, visiting duos. The
rest of the page is exhibition receptions, artist talks and book launches,
so only the music series is read (by decision, 2026-10-27).

/calendar-of-events is NOT a Squarespace events collection -- it is an
ordinary page of hand-typed text blocks, one per event (verified against
the live page 2026-10-27):

    <div class="sqs-block html-block" data-block-type="2">
      <h2>Bagels &amp; Sometimes Bach - Sunday Music Series<br/>
          ft. Omaha Chamber Music Society</h2>
      <h3>Sunday, November 1st — Doors open at 11:00am<br/>
          Performance runs 11:30am - 12:30pm</h3>
      <p>Bagels &amp; Sometimes Bach is Gallery 1516's Sunday morning ...</p>

An <h1>Upcoming Events</h1> heads the list and <h1>PAST EVENTS</h1> starts
last season's; we read only between the two. Three things the parser has
to respect:

  - NO YEAR ANYWHERE. Dates read "Sunday, November 1st". The weekday pins
    the year: within a three-year window around today a given month/day
    falls on a given weekday in exactly one year. A date whose weekday
    matches none of them is a typo on the page, and is skipped rather than
    guessed.
  - DOORS ARE NOT CURTAIN. The h3 gives doors (11:00) and performance
    (11:30-12:30); the event starts at the performance time. Without a
    "Performance runs" line it publishes all-day instead of inventing one.
  - THE BLURB SAYS "GALLERY". Every description names "Gallery 1516", a
    firm veto word in config.py, so the series is tagged with its own
    category and listed in CLASSICAL_CATEGORIES; category rules run before
    keyword vetoes. UNO lists its faculty's appearances here too, with
    "Gallery 1516" in the prose, so its copy is always vetoed -- hence
    titles lead with the performer (to match UNO's "Christine Beard, Flute
    Recital" in dedupe) and SOURCE_PRIORITY ranks this copy first.

No per-event pages exist; every event links to the calendar page. The
stock Squarespace robots.txt disallows ?format=json and ?format=ical, which
this page would not serve usefully anyway. One request per run.

HONESTY NOTE: live selectors are a documented best-effort; verify against
page source. The offline fixture is the captured page itself.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup

from adapters.base import Adapter
from models import Event

CALENDAR_URL = "https://www.gallery1516.org/calendar-of-events"
VENUE = "Gallery 1516"
SERIES = "Bagels & Sometimes Bach"

# "Bagels & Sometimes Bach - Sunday Music Series ft. Opera Omaha", and once
# "... Sunday Music Series Mother's Day Performance with ..." (no "ft.").
_SERIES_PREFIX = re.compile(
    r"^bagels\s*&\s*sometimes\s+bach\s*-?\s*(?:sunday\s+music\s+series)?\s*",
    re.IGNORECASE)
_FT = re.compile(r"^ft\.?\s+", re.IGNORECASE)
_DATE = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?")
_TIME = r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?"
_PERFORMANCE = re.compile(
    rf"performance\s+runs\s+{_TIME}(?:\s*[-–—]\s*{_TIME})?", re.IGNORECASE)
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday"]


class Gallery1516Adapter(Adapter):
    name = "gallery_1516"
    source_label = "Gallery 1516"
    fixture_ext = "html"

    def fetch_raw(self) -> Any:
        return self._get(CALENDAR_URL).text

    def parse(self, raw: Any) -> list[Event]:
        soup = BeautifulSoup(raw, "html.parser")
        events: list[Event] = []
        for h2 in self._upcoming_headings(soup):
            ev = self._build(h2)
            if ev:
                events.append(ev)
        return events

    def _upcoming_headings(self, soup: BeautifulSoup) -> list[Any]:
        """Event-title <h2>s between "Upcoming Events" and "PAST EVENTS"."""
        out: list[Any] = []
        started = False
        for h in soup.find_all(["h1", "h2"]):
            text = h.get_text(" ", strip=True).lower()
            if h.name == "h1":
                if text.startswith("upcoming events"):
                    started = True
                elif text.startswith("past events"):
                    break
            elif started:
                out.append(h)
        return out

    def _build(self, h2: Any) -> Event | None:
        heading = re.sub(r"\s+", " ", h2.get_text(" ", strip=True))
        if not _SERIES_PREFIX.match(heading):
            return None  # receptions, artist talks, book launches
        when_el = h2.find_next_sibling("h3")
        if when_el is None:
            return None
        when = re.sub(r"\s+", " ", when_el.get_text(" ", strip=True))
        day = self._day(when)
        if day is None:
            return None
        start, end = self._times(day, when)
        performer = _FT.sub("", _SERIES_PREFIX.sub("", heading)).strip(" -–—")
        paras = [re.sub(r"\s+", " ", p.get_text(" ", strip=True))
                 for p in when_el.find_next_siblings("p")]
        return Event(
            title=f"{performer} — {SERIES}" if performer else SERIES,
            start=start or datetime.combine(day, datetime.min.time()),
            end=end,
            venue=VENUE,
            url=CALENDAR_URL,
            description=" ".join([when] + [p for p in paras if p]),
            category=SERIES,
            all_day=start is None,
            source=self.source_label,
        )

    def _day(self, when: str, today: date | None = None) -> date | None:
        m = _DATE.search(when)
        if not m:
            return None
        weekday, month, dom = m.group(1).lower(), m.group(2), int(m.group(3))
        today = today or date.today()
        for year in (today.year - 1, today.year, today.year + 1):
            try:
                d = datetime.strptime(f"{month} {dom} {year}", "%B %d %Y").date()
            except ValueError:
                continue  # bad month name, or Feb 29 in a non-leap year
            if _WEEKDAYS[d.weekday()] == weekday:
                return d
        return None

    def _times(self, day: date, when: str) -> tuple[datetime | None, datetime | None]:
        m = _PERFORMANCE.search(when)
        if not m:
            return None, None
        start = self._at(day, *m.group(1, 2, 3))
        end = self._at(day, *m.group(4, 5, 6)) if m.group(4) else None
        return start, end

    @staticmethod
    def _at(day: date, hour: str, minute: str | None, ampm: str) -> datetime:
        h = int(hour) % 12 + (12 if ampm.lower() == "p" else 0)
        return datetime(day.year, day.month, day.day, h, int(minute or 0))
