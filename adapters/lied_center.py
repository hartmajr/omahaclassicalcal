"""Lied Center for Performing Arts -- Lincoln's presenting venue, via UNL Events.

UNL's performing-arts presenter: touring orchestras, chamber ensembles, and
recitalists share the season with Broadway tours, comedians, and pop acts,
so the classifier does real filtering here (the source's default verdict is
non-classical -- see SOURCE_PRIORITY in config.py).

WHY NOT liedcenter.org. Until 2026-10-19 this adapter parsed the Lied's own
events page plus one page per event (for hall and showtimes). From
2026-10-26 every URL there, robots.txt included, answered our identified
client with a Cloudflare "Just a moment..." challenge. We asked; the Lied's
press office replied (2026-11) that after a hosting change they cannot
allow particular crawlers. The RSS view they pointed us to (/events-feed)
is challenged too, and carries only the 10 most recently posted listings
with no performance dates. Per the project rule, a refusal is answered by
asking, never by disguising the client -- so we stopped reading
liedcenter.org.

WHAT WE READ INSTEAD. The Lied's marketing office posts its own season to
UNL's official events calendar -- the same service (events.unl.edu) that
serves UNL Music's feed, and which serves our client normally. The Lied's
calendar there is "Lied_Center" (the short name is case-sensitive;
lowercase "liedcenter" is a different, empty calendar), exported as JSON:

    https://events.unl.edu/Lied_Center/upcoming/?format=json&limit=-1

Verified 2026-11-10: 53 performances, 2026-11-13 to 2027-04-18. JSON
rather than the calendar's .ics because only the JSON carries the
"Event webpage" link back to the Lied's own page for each event -- our
entries should send readers to the presenter, not to a UNL index page. It
also gives the hall as a structured Room, local times with UTC offsets
(localized downstream by normalize._localize), the full programme notes,
and an event type ("Performing Arts - Music", "... - Musical Theatre"),
published as the category.

What this calendar does NOT carry: the Lied's rental events. That includes
Lincoln Friends of Chamber Music, which rents Carson Theater -- LFCM has
its own adapter (lfcm.py) reading its own site, the better source for its
concerts anyway.

Two things the parser has to do:

  - KEEP THE OLD HALL NAMES. Room is "Lied Center Main Stage" / "Carson
    Theater" -- the same names the old adapter read from the Lied's event
    pages. Same names means the same event uids (Event.uid hashes title,
    date and venue), so the switch did not make calendar apps delete and
    re-add the season. A Lied presentation in another building (it has
    used Kimball) publishes as "<Room>, <Building>".
  - LABEL MATINEES. Two performances of one show on one day share a
    title, date and venue -- Event.match_key -- and would collapse in
    dedupe, losing a showtime. Same fix and labels as before
    ("Hamilton (1:30pm)").

Lincoln's Symphony concerts at the Lied are skipped: LSO's own adapter is
their source of record, and the titles differ ("Emanuel Ax with Lincoln's
Symphony Orchestra" vs "Emanuel Ax"), which defeats fuzzy dedupe.

events.unl.edu's robots.txt allows us with Crawl-delay: 5. UNL Music's feed
is fetched from the same host earlier in the run, so fetch_raw waits that
long first.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from datetime import datetime
from typing import Any

from dateutil import parser as dtparse

from adapters.base import Adapter
from adapters.events_calendar import _strip_html
from dateformat import fmt
from models import Event

FEED_URL = "https://events.unl.edu/Lied_Center/upcoming/?format=json&limit=-1"
BUILDING = "Lied Center for Performing Arts"
CRAWL_DELAY_SECONDS = 5   # events.unl.edu robots.txt


class LiedCenterAdapter(Adapter):
    name = "lied_center"
    source_label = "Lied Center for Performing Arts"
    channel = "lincoln"
    fixture_ext = "json"

    def fetch_raw(self) -> Any:
        time.sleep(CRAWL_DELAY_SECONDS)   # UNL Music hit this host already
        return self._get(FEED_URL).json()

    def parse(self, raw: Any) -> list[Event]:
        events: list[Event] = []
        for e in (raw or {}).get("Events") or []:
            ev = self._event(e)
            if ev:
                events.append(ev)
        # Matinee labels, counted per (title, local day).
        per_day = Counter((ev.title, ev.start.date()) for ev in events)
        for ev in events:
            if per_day[(ev.title, ev.start.date())] > 1:
                ev.title = _label(ev.title, ev.start)
        return events

    def _event(self, e: dict) -> Event | None:
        title = re.sub(r"\s+", " ", e.get("EventTitle") or "").strip()
        when = e.get("DateTime") or {}
        if not title or not when.get("Start"):
            return None
        # Only what the Lied itself posted; UNL Events can surface other
        # calendars' events, and an LSO concert from LSO's calendar would
        # neither be skipped by title nor dedupe against LSO's own copy.
        origin = ((e.get("OriginCalendar") or {}).get("ShortName") or "Lied_Center")
        if origin.lower() != "lied_center":
            return None
        # Cancellation can arrive in either field: iCalendar-style Status,
        # or UNL's human-facing EventStatus ("Happening As Scheduled" on
        # every event in 2026-11). Dropping the event lets the prune remove
        # the stored copy, which is how a cancellation leaves the calendar.
        status = f"{e.get('Status') or ''} {e.get('EventStatus') or ''}".lower()
        if "cancel" in status or "postpone" in status:
            return None
        if "lincoln's symphony" in title.lower().replace("’", "'"):
            return None
        try:
            start = dtparse.isoparse(when["Start"])
        except (ValueError, TypeError):
            return None
        # Local wall-clock from here on, whatever offset UNL sends, so the
        # matinee count below groups by the Lincoln day, not the UTC one.
        start = _local(start)
        all_day = bool(when.get("AllDay")) or "tbd" in (when.get("TimeMode") or "").lower()
        end = None
        if when.get("End") and when.get("TimeMode") != "STARTTIMEONLY":
            try:
                end = _local(dtparse.isoparse(when["End"]))
            except (ValueError, TypeError):
                end = None
        subtitle = (e.get("EventSubtitle") or "").strip()
        if subtitle:
            title = f"{title}: {subtitle}"
        desc = _strip_html(e.get("Description") or "")
        desc = re.sub(r"\s+", " ", desc.replace("(R)", "®")).strip() or None
        types = [t.get("EventTypeName") for t in e.get("EventTypes") or []
                 if t.get("EventTypeName")]
        return Event(
            title=title,
            start=start,
            end=end,
            all_day=all_day,
            venue=_venue(e),
            url=_url(e),
            description=desc,
            category=", ".join(types) or None,
            source=self.source_label,
        )


def _venue(e: dict) -> str:
    """The hall; the building too when it isn't the Lied."""
    loc = (e.get("Locations") or [{}])[0] or {}
    addr = loc.get("Address") or {}
    building = (addr.get("BuildingName") or loc.get("LocationName") or "").strip()
    room = (e.get("Room") or addr.get("Room") or "").strip()
    if building and building != BUILDING:
        return f"{room}, {building}" if room else building
    return room or BUILDING


def _url(e: dict) -> str | None:
    """The Lied's own event page; UNL's instance page only as a fallback."""
    pages = e.get("WebPages") or []
    for p in pages:
        if (p.get("Title") or "").lower() == "event webpage" and p.get("URL"):
            return p["URL"]
    for p in pages:
        url = p.get("URL") or ""
        if url:
            return "https:" + url if url.startswith("//") else url
    return None


def _local(dt: datetime) -> datetime:
    """Aware -> Lincoln wall-clock (still aware); naive is taken as local."""
    from normalize import _LOCAL_TZ
    if dt.tzinfo is not None and _LOCAL_TZ is not None:
        return dt.astimezone(_LOCAL_TZ)
    return dt


def _label(title: str, start: datetime) -> str:
    """'Hamilton' -> 'Hamilton (1:30pm)', from a local wall-clock start."""
    pat = "%-I%p" if start.minute == 0 else "%-I:%M%p"
    return f"{title} ({fmt(start, pat)})".replace("AM", "am").replace("PM", "pm")
