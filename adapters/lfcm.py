"""Lincoln Friends of Chamber Music -- homepage season-block HTML parse.

A presenter, not a venue: four touring chamber concerts a season, rented
into the Lied's Carson Theater or UNL's Kimball Recital Hall. Until
2026-10-19 their concerts reached us incidentally through the Lied
Center's listing (see the old CLAUDE.md note). When the Lied went behind
Cloudflare and moved to UNL Events, which carries no rental events, LFCM's
concerts would have vanished silently -- so LFCM is now read from its own
site, which is the source of record for them anyway.

lfcm.us is WordPress (Pro/Cornerstone page builder) with no calendar plugin
and an empty RSS feed. The homepage carries the whole current season,
one column per concert (verified against the live page 2026-11-10):

    <div class="x-col ...">
      <h3 class="x-text-content-text-primary">Poiesis Quartet</h3>
      <span class="x-text-content-text-subheadline">
        <p>Tuesday, Mar. 23, 2027 at 7:30 PM</p>
        <p>Johnny Carson Theater at the Lied</p>
        <p>$41 Regular | $10 Student <br><em>Complimentary Streaming...</em></p>
      </span>
      <a class="x-anchor-button" href=".../2026-2027-season/poiesis-quartet/">More Information</a>

Some concerts carry a line BEFORE the date naming the performers ("An
Afternoon of French Romantic Chamber Music" / "Featuring Rachel Barton
Pine, Orion Weiss & Pacifica Quartet"); it is appended to the title, since
the performers are what a reader recognizes. The first line after the
last date that isn't prices or streaming is the venue. Dates carry their
year, so no year inference is needed; a block with several date lines
becomes several performances.

The parser is strict about what counts as a concert, because this source
is classical by category -- a rule that runs before the keyword vetoes --
so a ticket notice or gala block let through would publish as a concert.
Only blocks whose "More Information" link leads into a season page
qualify, and a block that says cancelled or postponed is skipped (the
stored copy is then pruned). A concert block with no readable date is
reported in status.json via `unparsed`, not dropped silently.

The season's own page moves every year (/2026-2027-season/), which is why
we read the homepage rather than hardcoding a season URL that would
silently serve last year -- the Nebraska Wind Symphony lesson. robots.txt
is the stock WordPress file (only /wp-admin/ etc. disallowed); one request
per run.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from bs4 import BeautifulSoup
from dateutil import parser as dtparse

from adapters.base import Adapter
from adapters.lied_center import _label
from models import Event

HOME_URL = "https://lfcm.us/"
SERIES = "Lincoln Friends of Chamber Music"

# A date line: optional weekday (full or abbreviated), month (abbreviated,
# dotted or full), day, year, then an optional time after "at", a comma, a
# dash or a bar. "Tuesday, Mar. 23, 2027 at 7:30 PM" / "Tue., Sept. 22,
# 2026 | 7:30 PM" / "Sept. 22, 2026". A time with no am/pm is ambiguous and
# publishes all-day rather than as a guess.
_DATE_RE = re.compile(
    r"(?:\b(?:Sun|Mon|Tue|Tues|Wed|Wednes|Thu|Thur|Thurs|Fri|Sat|Satur)(?:day)?\.?,?\s+)?"
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})"
    r"(?:\s*(?:at|,|\||-|–|—)?\s*(\d{1,2}(?::\d{2})?\s*[AP]\.?\s?M\.?|noon))?",
    re.I,
)
# Only blocks whose "More Information" button leads into a season are
# concerts. The homepage also carries ticket, donation and gala blocks, and
# this source is classical by category -- which runs before the keyword
# vetoes -- so anything let through here publishes as a concert.
_SEASON_LINK = re.compile(r"/\d{4}-\d{4}-season/[^/]+")
# A block announcing a change is not a performance to list. Dropping it is
# right: the stored copy is then pruned as cancelled.
_CANCELLED = re.compile(r"\b(cancel+ed|postponed)\b", re.I)
# Lines that are neither date, performers nor venue.
_INFO = re.compile(r"\$|streaming|sold out|tickets?\b|free admission", re.I)
# LFCM's name for the Lied's hall; the Lied's own feed (and every Lied
# entry here) says "Carson Theater". One name keeps the uid of a concert
# the Lied once listed stable (Event.uid hashes the venue) and lets dedupe
# match the two if both ever list it.
_VENUES = {"johnny carson theater at the lied": "Carson Theater"}


class LFCMAdapter(Adapter):
    name = "lfcm"
    source_label = "Lincoln Friends of Chamber Music"
    channel = "lincoln"
    fixture_ext = "html"

    def fetch_raw(self) -> Any:
        return self._get(HOME_URL).text

    def parse(self, raw: Any) -> list[Event]:
        soup = BeautifulSoup(raw, "html.parser")
        events: list[Event] = []
        seen: set[tuple[str, str]] = set()
        # Concert blocks we recognized but could not read a date from --
        # reported in status.json rather than dropped silently (the prune
        # guard only catches a source returning nothing at all).
        self.unparsed: list[str] = []
        for h3 in soup.find_all("h3"):
            col = h3.find_parent("div", class_="x-col")
            sub = h3.find_next_sibling("span", class_="x-text-content-text-subheadline")
            if not col or not sub:
                continue
            link = next((a["href"] for a in col.find_all("a", href=True)
                         if _SEASON_LINK.search(a["href"])), None)
            if not link:
                continue
            title = re.sub(r"\s+", " ", h3.get_text(" ", strip=True))
            lines = [re.sub(r"\s+", " ", p.get_text(" ", strip=True))
                     for p in sub.find_all("p")]
            lines = [ln for ln in lines if ln]
            if _CANCELLED.search(title) or any(_CANCELLED.search(ln) for ln in lines):
                continue
            dated = [(i, m) for i, ln in enumerate(lines) if (m := _DATE_RE.search(ln))]
            starts = []
            for _, m in dated:
                st = _start(m)
                if st:
                    starts.append((st, bool(m.group(4))))
            if not starts:
                self.unparsed.append(title)
                continue
            first, last = dated[0][0], dated[-1][0]
            performers = " ".join(ln for ln in lines[:first] if not _INFO.search(ln))
            if performers:
                title = (f"{title}, {performers[0].lower() + performers[1:]}"
                         if performers.lower().startswith("featuring")
                         else f"{title}: {performers}")
            venue = next((ln for ln in lines[last + 1:] if not _INFO.search(ln)), None)
            venue = _VENUES.get((venue or "").lower(), venue)
            per_day = Counter(st.date() for st, _ in starts)
            for st, timed in starts:
                label = _label(title, st) if timed and per_day[st.date()] > 1 else title
                key = (label, st.isoformat())
                if key in seen:   # page builders sometimes repeat a block for mobile
                    continue
                seen.add(key)
                events.append(Event(
                    title=label,
                    start=st,
                    venue=venue,
                    url=link,
                    category=SERIES,
                    source=self.source_label,
                    # No stated time -> all-day, never a guessed midnight.
                    all_day=not timed,
                ))
        return events


def _start(m: re.Match):
    month, day, year, clock = m.groups()
    clock = "12:00 PM" if (clock or "").lower() == "noon" else (clock or "")
    try:
        return dtparse.parse(f"{month[:3]} {day} {year} {clock}".strip())
    except (ValueError, OverflowError):
        return None
