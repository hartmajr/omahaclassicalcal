"""Nebraska Chamber Players -- Squarespace event-list HTML parse.

A Lincoln chamber ensemble (30th season in 2026-27) whose performance home
is the Unitarian Church of Lincoln, 6300 A Street -- a venue no other
source here covers, so these events are genuinely new to the calendar
rather than another view of a Lied/Kimball booking.

Each program is played twice, Friday 7:30pm and Sunday 3:00pm, and the
site renders each performance as its own <article class="eventlist-event">
under /calendar (verified against the live page 2026-09-22):

    <article class="eventlist-event eventlist-event--upcoming">
      <h1 class="eventlist-title"><a class="eventlist-title-link" href="...">
        November Concert Series - British & American Music for Winds and Piano
      <time class="event-date" datetime="2026-11-13">Friday, November 13, 2026</time>
      <time class="event-time-24hr-start" datetime="2026-11-13">19:30</time>
      <div class="eventlist-description">...<strong>Performed at The
        Unitarian Church of Lincoln, 6300 A Street</strong><p><em>Sextet</em>
        - Gordon Jacob</p>...

Three things about this page that the parser has to respect:

  - THE URL SLUG LIES. Squarespace event pages are reused between seasons,
    so November 2026's concert still lives at a 2025/10/31 Halloween slug.
    Dates come from the <time datetime> attributes, never from the href.
  - Past performances are rendered too, in separate eventlist--past
    containers. We read only the eventlist--upcoming list; store.py would
    drop the stale ones on read anyway, but there is no reason to upsert
    last season into events.db every week.
  - The venue lives in the description prose ("Performed at ..."), not in
    any structured field, so we read it from there and fall back to their
    stated home venue. The 2026-27 season trails "a very special event in
    2027" that may well be elsewhere.

We deliberately do NOT use the per-event ICS export (?format=ical) that
the page links: nebraskachamberplayers.org's robots.txt -- the stock
Squarespace file -- carries "Disallow: /*?format=ical". That rule names
the ical format specifically rather than catching it incidentally, so it
fails the bar for a config.ROBOTS_EXCEPTIONS entry. The /calendar HTML
page is permitted, so that is what we read: one request per run.

The repertoire prose is kept as the description on purpose -- it carries
the composer names (Jacob, Larsen, Price, Glazunov) that the classifier's
composer signal keys on for a group that publishes no series labels.

HONESTY NOTE: live CSS selectors are a documented best-effort; verify
against page source. The offline fixture holds the real captured season.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from adapters.base import Adapter
from models import Event

CALENDAR_URL = "https://nebraskachamberplayers.org/calendar"
SITE = "https://nebraskachamberplayers.org"
VENUE = "Unitarian Church of Lincoln"

# The venue sits in its own <strong>/<p> inside the description:
# "Performed at The Unitarian Church of Lincoln, 6300 A Street". Read it
# from that element rather than from the flattened prose -- once the
# description is collapsed to one line there is no boundary between the
# address and the repertoire list that follows it.
_VENUE_PREFIX = re.compile(r"^performed at\s+", re.IGNORECASE)


class NebraskaChamberPlayersAdapter(Adapter):
    name = "nebraska_chamber_players"
    source_label = "Nebraska Chamber Players"
    channel = "lincoln"
    fixture_ext = "json"

    def fetch_raw(self) -> Any:
        return self._get(CALENDAR_URL).text

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
        # Scope to the upcoming list; the page also renders past seasons.
        for section in soup.select("div.eventlist--upcoming"):
            for card in section.select("article.eventlist-event"):
                title_el = card.select_one(".eventlist-title")
                date_el = card.select_one("time.event-date")
                if not title_el or not date_el:
                    continue
                link_el = card.select_one("a.eventlist-title-link")
                time_el = card.select_one("time.event-time-24hr-start")
                desc_el = card.select_one(".eventlist-description")
                href = (link_el.get("href") or "") if link_el else ""
                rows.append({
                    "title": title_el.get_text(" ", strip=True),
                    # The datetime attribute, not the human text or the href.
                    "date": date_el.get("datetime"),
                    "time_24": time_el.get_text(strip=True) if time_el else None,
                    "url": SITE + href if href.startswith("/") else (href or None),
                    "description": desc_el.get_text(" ", strip=True) if desc_el else None,
                    "venue": self._venue_from(desc_el),
                })
        return rows

    def _build(self, r: dict) -> Event | None:
        start, timed = self._start(r.get("date"), r.get("time_24"))
        if not start:
            return None
        title = re.sub(r"\s+", " ", r["title"]).strip()
        description = re.sub(r"\s+", " ", r["description"]).strip() if r.get("description") else None
        return Event(
            title=title,
            start=start,
            venue=r.get("venue") or VENUE,
            url=r.get("url"),
            description=description,
            # No usable showtime: publish as an all-day entry rather than
            # inventing one, the same call the Lied Center adapter makes.
            all_day=not timed,
            source=self.source_label,
        )

    def _start(self, date: str | None, time_24: str | None) -> tuple[datetime | None, bool]:
        """(start, whether a real showtime was found) -- a time we could not
        read must publish all-day, not silently as midnight."""
        if not date:
            return None, False
        try:
            day = datetime.strptime(date.strip(), "%Y-%m-%d")
        except (ValueError, TypeError):
            return None, False
        m = re.match(r"(\d{1,2}):(\d{2})", (time_24 or "").strip())
        if not m:
            return day, False
        return day.replace(hour=int(m.group(1)), minute=int(m.group(2))), True

    def _venue_from(self, desc_el: Any) -> str | None:
        """The 'Performed at ...' line, read from its own element."""
        if desc_el is None:
            return None
        for el in desc_el.select("strong, em, p"):
            text = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
            if _VENUE_PREFIX.match(text):
                return _VENUE_PREFIX.sub("", text).strip(" .*") or None
        return None
