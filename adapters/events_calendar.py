"""Two reusable adapters for 'The Events Calendar' WordPress plugin, which
both KVNO and the Omaha Conservatory run.

The plugin gives you two ways in, and we demo both because the pipeline
should be able to consume either:

  EventsCalendarRest -- the JSON REST API at
      /wp-json/tribe/events/v1/events
    Richer, paginated, filterable. Used here for KVNO.

  ICSFeedAdapter -- the plain .ics export the plugin publishes (e.g.
      https://omahacm.org/events/?ical=1  or  .../list/?ical=1 )
    Dead simple: one URL, standard iCalendar. Used here for the
    Conservatory. This same adapter works for ANY .ics feed, so it's also
    how you'd wire in Creighton or a venue once you find their feed URL.
"""

from __future__ import annotations

from html import unescape as html_unescape
from typing import Any

from dateutil import parser as dtparse
from icalendar import Calendar

from adapters.base import Adapter
from models import Event


class EventsCalendarRest(Adapter):
    """Generic adapter for the Tribe/Events-Calendar REST API."""
    fixture_ext = "json"

    def __init__(self, name: str, source_label: str, base_url: str,
                 channel: str = "local", no_query: bool = False):
        self.name = name
        self.source_label = source_label
        self.base_url = base_url.rstrip("/")
        self.channel = channel
        # Some sites (e.g. omahacm.org) publish "Disallow: /*?" -- a blanket
        # ban on query strings. Paginating with ?page= would violate it, so
        # no_query fetches the bare endpoint and takes the default page.
        # Fine for small presenters; not for high-volume feeds.
        self.no_query = no_query
        self.truncated: tuple[int, int] | None = None

    def fetch_raw(self) -> Any:
        endpoint = f"{self.base_url}/wp-json/tribe/events/v1/events"
        out: dict[str, Any] = {"events": []}
        if self.no_query:
            # No query string at all -- robots-safe on sites banning "?".
            # This gets ONE default page, so it can silently truncate. The
            # plugin reports the true total, so compare and shout if we're
            # missing events rather than quietly publishing a partial list.
            data = self._get(endpoint).json()
            events = data.get("events", [])
            total = data.get("total")
            if isinstance(total, int) and total > len(events):
                self.truncated = (len(events), total)
            return {"events": events}
        page = 1
        while True:
            data = self._get(endpoint, page=page, per_page=50,
                             start_date="now").json()
            out["events"].extend(data.get("events", []))
            if page >= data.get("total_pages", 1):
                break
            page += 1
        return out

    def parse(self, raw: Any) -> list[Event]:
        events: list[Event] = []
        for e in raw.get("events", []):
            # The API returns titles/venues HTML-encoded ("Bach&#8217;s
            # Lunch"). Unescape them, or dedupe against a primary source's
            # plain-text copy of the same concert can never match.
            title = html_unescape((e.get("title") or "").strip())
            if not title or not e.get("start_date"):
                continue
            venue = (e.get("venue") or {}).get("venue") if isinstance(
                e.get("venue"), dict) else None
            venue = html_unescape(venue) if venue else None
            cats = e.get("categories") or []
            category = cats[0]["name"] if cats and isinstance(cats[0], dict) else None
            events.append(
                Event(
                    title=title,
                    start=dtparse.parse(e["start_date"]),
                    end=dtparse.parse(e["end_date"]) if e.get("end_date") else None,
                    venue=venue,
                    url=e.get("url"),
                    description=_strip_html(e.get("description") or "") or None,
                    category=category,
                    source=self.source_label,
                )
            )
        return events


class ICSFeedAdapter(Adapter):
    """Generic adapter for any iCalendar (.ics) feed."""
    fixture_ext = "ics"

    def __init__(self, name: str, source_label: str, feed_url: str,
                 channel: str = "local"):
        self.name = name
        self.source_label = source_label
        self.feed_url = feed_url
        self.channel = channel

    def fetch_raw(self) -> Any:
        return self._get(self.feed_url).text

    def parse(self, raw: Any) -> list[Event]:
        # A feed with nothing to publish may answer 200 with an empty body
        # (omahacm.org does this off-season); that's zero events, not an error.
        if not str(raw or "").strip():
            return []
        cal = Calendar.from_ical(raw)
        events: list[Event] = []
        for comp in cal.walk("VEVENT"):
            start = comp.get("DTSTART")
            summary = comp.get("SUMMARY")
            if not start or not summary:
                continue
            end = comp.get("DTEND")
            events.append(
                Event(
                    title=str(summary).strip(),
                    start=_to_dt(start.dt),
                    end=_to_dt(end.dt) if end else None,
                    venue=str(comp.get("LOCATION")) if comp.get("LOCATION") else None,
                    url=str(comp.get("URL")) if comp.get("URL") else None,
                    description=(str(comp.get("DESCRIPTION")).strip()
                                if comp.get("DESCRIPTION") else None),
                    category=(str(comp.get("CATEGORIES")) if comp.get("CATEGORIES")
                             else None),
                    source=self.source_label,
                )
            )
        return events


def _to_dt(value):
    from datetime import date, datetime
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return dtparse.parse(str(value))


def _strip_html(text: str) -> str:
    import re
    return html_unescape(re.sub(r"<[^>]+>", "", text)).strip()
