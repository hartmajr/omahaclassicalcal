"""Juilliard -- server-rendered Drupal 10 performance calendar.

Unlike the Omaha Symphony's JS calendar, Juilliard's renders events right
in the HTML, paginated with ?page=N. Each event block carries a date, a
title linking to /event/{id}/{slug}, a venue, one or more type tags
(Music, Chamber Music, Recital, Orchestra, Live Streaming, ...), and a time.

Online detection is explicit and reliable here: Juilliard tags streamed
performances with the "Live Streaming" performance type and/or places them
at the "Livestream" / "Streaming Event" venues. With online_only=True we
keep just those -- the point of including Juilliard in an Omaha calendar is
the performances you can actually watch from Omaha.

HONESTY NOTE (as with the Symphony): the live HTML selectors below are a
documented best-effort; the calendar's content and structure were confirmed
but exact class names should be verified against raw page source. The
offline fixture is real-shaped data so the pipeline is exercised correctly.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from dateutil import parser as dtparse

from adapters.base import Adapter
from models import Event

CALENDAR_URL = "https://www.juilliard.edu/stage-beyond/performance/calendar"
STREAMING_VENUES = {"livestream", "streaming event"}
STREAMING_TYPES = {"live streaming"}
MAX_PAGES = 20   # ~2.5 weeks per page -> roughly a full season


class JuilliardAdapter(Adapter):
    name = "juilliard"
    source_label = "Juilliard"
    channel = "online"
    fixture_ext = "json"   # offline fixture is structured; live path parses HTML

    def __init__(self, online_only: bool = True,
                 page_url_template: str | None = None):
        self.online_only = online_only
        # Optional override for the real "Load More" endpoint, if you capture
        # it from devtools. Must contain "{page}".
        self.page_url_template = page_url_template

    def fetch_raw(self) -> Any:
        """Fetch calendar pages, stopping as soon as one adds nothing new.

        The calendar's "Load More" is JavaScript. Whether `?page=N` also
        works server-side could not be confirmed, so this must handle BOTH
        cases safely: if pagination works we keep going; if the server
        ignores `?page` and returns page 1 every time, the identical-content
        check stops us after the second fetch instead of re-parsing the same
        HTML a dozen times.

        If you want the events beyond page 1 and `?page=` turns out not to
        work, open the calendar in a browser with devtools' Network tab
        open, click "Load More", and copy the request URL it fires. Pass
        that pattern as `page_url_template` (it takes `{page}`).
        """
        pages: list[str] = []
        seen_digests: set[str] = set()
        for page in range(MAX_PAGES):
            url = (self.page_url_template.format(page=page)
                   if self.page_url_template else CALENDAR_URL)
            params = {} if self.page_url_template else ({"page": page} if page else {})
            html = self._get(url, **params).text
            digest = hashlib.sha1(html.encode()).hexdigest()
            if digest in seen_digests:
                # Server ignored the page parameter -- further fetches would
                # return the same HTML. Stop rather than hammering the site.
                break
            seen_digests.add(digest)
            pages.append(html)
        return "\n".join(pages)

    def parse(self, raw: Any) -> list[Event]:
        if isinstance(raw, (list, dict)):
            rows = raw["events"] if isinstance(raw, dict) else raw
            return self._from_rows(rows)
        return self._from_html(raw)

    def _from_rows(self, rows: list[dict]) -> list[Event]:
        events: list[Event] = []
        for r in rows:
            online = self._is_online(r.get("venue"), r.get("types", []))
            if self.online_only and not online:
                continue
            events.append(self._build(r, online))
        return events

    def _from_html(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        current_date = None
        # Each date is an <h2>/<h3> like "Jul 09 Thu"; events follow as
        # links to /event/. This walks the list, tracking the last date seen.
        for el in soup.find_all(["h2", "h3", "a"]):
            text = el.get_text(" ", strip=True)
            if el.name in {"h2", "h3"} and re.match(r"[A-Z][a-z]{2}\s+\d{1,2}", text):
                current_date = text
                continue
            href = el.get("href", "") if el.name == "a" else ""
            if "/event/" in href and current_date:
                block = el.find_parent(["li", "article", "div"])
                btext = block.get_text(" ", strip=True) if block else text
                types = [t.lower() for t in re.findall(
                    r"(Live Streaming|Orchestra|Chamber Music|Recital|Opera / Voice|"
                    r"Historical Performance|Contemporary / New Work|Jazz|Music)", btext)]
                venue_m = re.search(r"(Livestream|Streaming Event|[A-Z][\w .'/-]+Hall)", btext)
                venue = venue_m.group(0) if venue_m else None
                time_m = re.search(r"(\d{1,2}:\d{2}\s*[AP]M)", btext)
                start = self._date(current_date, time_m.group(1) if time_m else "7:00PM")
                if not start:
                    continue
                online = self._is_online(venue, types)
                if self.online_only and not online:
                    continue
                events.append(self._build({
                    "title": text, "url": href, "venue": venue,
                    "types": types, "start": start.isoformat(),
                }, online))
        return events

    # Type tags ranked by how much they say about the music. "Live Streaming",
    # "Free" and bare "Music" describe delivery/price, not genre, so they must
    # never win: picking one as the category hides the genre tag ("Jazz",
    # "Orchestra") that the classifier actually needs.
    _GENRE_TYPES = ["orchestra", "chamber music", "historical performance",
                    "opera / voice", "recital", "classical", "jazz", "dance",
                    "drama", "contemporary / new work", "special event"]

    def _build(self, r: dict, online: bool) -> Event:
        start = (dtparse.parse(r["start"]) if r.get("start")
                 else self._date(r["date_text"], r.get("time", "7:00PM")))
        types = r.get("types", [])
        lowered = [t.lower() for t in types]
        category = next((t.title() for t in self._GENRE_TYPES if t in lowered),
                        types[0].title() if types else "Performance")
        # Keep EVERY tag in the description: the classifier reads this text,
        # and dropping tags loses the genre signal entirely.
        desc_parts = [r["description"]] if r.get("description") else []
        if types:
            desc_parts.append("Tags: " + ", ".join(types) + ".")
        ev = Event(
            title=r["title"].strip(),
            start=start,
            venue="Online / Livestream" if online else r.get("venue"),
            url=("https://www.juilliard.edu" + r["url"]
                 if r.get("url", "").startswith("/") else r.get("url")),
            description=" ".join(desc_parts) or None,
            category=category,
            source=self.source_label,
        )
        return ev

    def _is_online(self, venue: str | None, types: list[str]) -> bool:
        v = (venue or "").lower()
        t = {x.lower() for x in types}
        return v in STREAMING_VENUES or bool(t & STREAMING_TYPES)

    def _date(self, date_text: str, time_text: str) -> datetime | None:
        # date_text like "Jul 09 Thu" (no year) -> assume the coming season.
        m = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2})", date_text)
        if not m:
            return None
        month, day = m.group(1), m.group(2)
        year = _season_year(month)
        try:
            return dtparse.parse(f"{month} {day} {year} {time_text}")
        except (ValueError, OverflowError):
            return None


def _season_year(month_abbr: str) -> int:
    # Academic calendar spans two years; map months to the right one so a
    # "Jan" event lands next year, not this past January.
    now = datetime.now()
    try:
        m = dtparse.parse(f"{month_abbr} 1").month
    except ValueError:
        return now.year
    return now.year if m >= now.month else now.year + 1
