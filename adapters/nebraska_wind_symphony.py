"""Nebraska Wind Symphony -- season page read through WordPress's REST API.

Omaha's community concert band (50th season in 2026-27). Formal concerts
are at UNO's Strauss Performing Arts Center, each premiering a commissioned
work; a small-ensembles concert and summer concerts by the NWS Swingtones
play elsewhere. None of these reached the calendar through another source.

The site is WordPress with no calendar plugin (no ?ical=1, no tribe REST
endpoint, an empty RSS feed). The whole season is prose on one page, one
<strong> date line per concert followed by dash-led notes (verified against
the live page 2026-09-23):

    <strong>Sunday, October 18, 2026 &#8211; 7:30PM</strong> – UNO Strauss
      Performing Arts Center<br>– performance of composition by ...<br>
    <strong>Sunday, December 6 &#8211; 3:00PM</strong> – UNO Strauss ...
    <strong><em>Summer Concerts</em> </strong>with the Nebraska Wind
      Symphony Swingtones<br>
    <strong>Sunday, June 6 2027 &#8211; 6PM</strong> – St. Robert ...

Why the REST API rather than the HTML page:
  - THE PAGE MOVES EVERY SEASON: /seasons/season49/, /seasons/season50/, ...
    A hardcoded URL keeps working and silently serves last season. The API
    lists page slugs, so we take the highest-numbered seasonNN.
  - The served HTML carries mojibake ("â€“" for an en dash); the API's JSON
    is clean UTF-8.
Two requests per run -- the slug list, then that one page -- spaced by the
10-second Crawl-delay robots.txt asks for. /wp-json/ is not disallowed.

The prose is written loosely, and the parser takes it as it comes:
  - Years are sometimes omitted ("Sunday, December 6"). The season heading
    gives the span ("2026-2027"); the weekday the page states then picks
    the year, which catches a wrong guess instead of publishing it.
  - Times appear as "7:30PM", "3:00 pm" and "6PM"; the February date and
    time sit in separate <strong> tags on one line.
  - Concerts have no titles. Each is published as "Nebraska Wind Symphony"
    unless the page names it -- a section heading ("Summer Concerts with
    the Nebraska Wind Symphony Swingtones") or an "NWS ... concert" note.
    Nothing is invented; the notes go in the description.

Swingtones concerts are published by decision (2026-09-23): they are the
band's own summer series. A category rule in config.CLASSICAL_CATEGORIES
keeps a future "swing"/"jazz" blurb from vetoing them.

HONESTY NOTE: live CSS selectors are a documented best-effort; verify
against page source. The offline fixture holds the real captured page.
"""

from __future__ import annotations

import html as htmllib
import re
import time
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from adapters.base import Adapter
from models import Event

API = "https://nebraskawindsymphony.com/wp-json/wp/v2/pages"
TITLE = "Nebraska Wind Symphony"
SWINGTONES = "Swingtones"          # the category config.py whitelists
CRAWL_DELAY_SECONDS = 10

_SEASON_SLUG = re.compile(r"season(\d+)")
_SPAN = re.compile(r"(20\d{2})\s*[-–—]\s*(20\d{2})")
_DASH = r"[-–—]"
# "Sunday, October 18, 2026 – 7:30PM – UNO Strauss Performing Arts Center"
_EVENT = re.compile(
    r"^(?P<wday>mon|tues|wednes|thurs|fri|satur|sun)day,?\s+"
    r"(?P<month>[a-z]+)\s+(?P<day>\d{1,2})(?:,?\s+(?P<year>20\d{2}))?"
    rf"\s*{_DASH}\s*(?P<hour>\d{{1,2}})(?::(?P<minute>\d{{2}}))?\s*(?P<ampm>[ap])\.?\s*m\.?"
    rf"(?:\s*{_DASH}\s*(?P<venue>.*))?$",
    re.IGNORECASE,
)
_NOTE = re.compile(rf"^{_DASH}\s*(.+)$")
_NAMED = re.compile(r"^NWS\s+(.+?)\s+concert$", re.IGNORECASE)
_WEEKDAYS = ["mon", "tues", "wednes", "thurs", "fri", "satur", "sun"]


class NebraskaWindSymphonyAdapter(Adapter):
    name = "nebraska_wind_symphony"
    source_label = "Nebraska Wind Symphony"
    fixture_ext = "json"

    def fetch_raw(self) -> Any:
        slugs = self._get(API, search="season", per_page=100, _fields="slug").json()
        numbered = [(int(m.group(1)), s["slug"]) for s in slugs
                    if (m := _SEASON_SLUG.fullmatch(s.get("slug", "")))]
        if not numbered:
            raise ValueError(f"{self.source_label}: no seasonNN page found")
        slug = max(numbered)[1]
        time.sleep(CRAWL_DELAY_SECONDS)  # robots.txt Crawl-delay
        pages = self._get(API, slug=slug, _fields="slug,link,modified,content").json()
        if not pages:
            raise ValueError(f"{self.source_label}: page {slug} vanished")
        page = pages[0]
        return {"slug": page["slug"], "link": page["link"],
                "modified": page.get("modified"),
                "html": page["content"]["rendered"]}

    def parse(self, raw: Any) -> list[Event]:
        lines = self._lines(raw["html"])
        span = next((m for m in map(_SPAN.search, lines) if m), None)
        years = (int(span.group(1)), int(span.group(2))) if span else None
        events: list[Event | None] = []
        section: str | None = None
        current: dict | None = None
        for line in lines:
            m = _EVENT.match(line)
            if m:
                if current:
                    events.append(self._build(current, raw["link"]))
                current = {"match": m, "section": section, "notes": [], "years": years}
                continue
            note = _NOTE.match(line)
            if note and current:
                current["notes"].append(note.group(1).strip())
                continue
            # Anything else ends the current concert. A heading for the dates
            # after it only occurs once the schedule has begun, and reads as
            # a label, not a sentence -- the intro's "See the flyer for this
            # season's concerts." must not title every concert.
            if current:
                events.append(self._build(current, raw["link"]))
                current = None
            if (events and "concert" in line.lower() and len(line) < 90
                    and not line.endswith(".")):
                section = line
        if current:
            events.append(self._build(current, raw["link"]))
        return [e for e in events if e]

    def _lines(self, html: str) -> list[str]:
        """Content as text lines, one per <br>/<p>, entities decoded."""
        soup = BeautifulSoup(html, "html.parser")
        for br in soup.find_all("br"):
            br.replace_with("\n")
        out = []
        for block in soup.find_all(["p", "h1", "h2", "h3"]):
            for line in block.get_text("").split("\n"):
                line = re.sub(r"\s+", " ", htmllib.unescape(line)).strip()
                if line:
                    out.append(line)
        return out

    def _build(self, c: dict, link: str) -> Event | None:
        m = c["match"]
        start = self._start(m, c["years"])
        if not start:
            return None
        section = c["section"]
        named = next((n for n in map(_NAMED.match, c["notes"]) if n), None)
        if section:
            # "Summer Concerts with ..." heads several dates; each is one.
            title = re.sub(r"\bConcerts\b", "Concert", section)
        elif named:
            title = f"{TITLE} {named.group(1)}"
        else:
            title = TITLE
        venue = (m.group("venue") or "").strip(" –—-") or None
        return Event(
            title=title,
            start=start,
            venue=venue,
            url=link,
            description="; ".join(c["notes"]) or None,
            category=SWINGTONES if section and SWINGTONES.lower() in section.lower() else None,
            source=self.source_label,
        )

    def _start(self, m: re.Match, years: tuple[int, int] | None) -> datetime | None:
        hour, minute = int(m.group("hour")), int(m.group("minute") or 0)
        ampm = m.group("ampm").lower()
        if ampm == "p" and hour != 12:
            hour += 12
        if ampm == "a" and hour == 12:
            hour = 0
        stated = _WEEKDAYS.index(m.group("wday").lower())
        if m.group("year"):
            candidates = [int(m.group("year"))]
        elif years:
            # Season runs autumn to summer: try the likelier year first, but
            # let the weekday the page states make the call.
            try:
                month = datetime.strptime(m.group("month")[:3], "%b").month
            except ValueError:
                return None
            candidates = [years[0], years[1]] if month >= 8 else [years[1], years[0]]
        else:
            candidates = [datetime.now().year, datetime.now().year + 1]
        parsed = []
        for year in candidates:
            try:
                parsed.append(datetime.strptime(
                    f"{m.group('month')} {m.group('day')} {year} {hour}:{minute}",
                    "%B %d %Y %H:%M"))
            except ValueError:
                continue
        if not parsed:
            return None
        return next((d for d in parsed if d.weekday() == stated), parsed[0])
