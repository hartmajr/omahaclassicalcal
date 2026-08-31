"""Publish a subscribable .ics calendar -- the primary output.

This is the thing people actually use: point Google Calendar or Apple
Calendar at the published URL and the aggregated Omaha classical calendar
appears in their app and stays updated. Stable per-event UIDs mean updates
replace entries in place instead of piling up duplicates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from icalendar import Calendar, Event as ICalEvent

from models import Event


def write_ics(events: list[Event], out: Path, calendar_name: str) -> Path:
    cal = Calendar()
    cal.add("prodid", "-//Omaha Classical Calendar//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", calendar_name)
    cal.add("x-wr-timezone", "America/Chicago")

    for ev in events:
        ie = ICalEvent()
        ie.add("uid", ev.uid)
        ie.add("summary", ev.title)
        ie.add("dtstart", ev.start)
        ie.add("dtend", ev.end or ev.start)
        ie.add("dtstamp", datetime.now(timezone.utc))
        if ev.venue:
            ie.add("location", ev.venue)
        # Third-party promotional copy is the presenter's, not ours. Publish
        # a short excerpt for context and send readers to the source for the
        # rest -- an aggregator should drive traffic to presenters, not
        # substitute for them.
        MAX_DESC = 240
        desc = (ev.description or "").strip()
        if len(desc) > MAX_DESC:
            desc = desc[:MAX_DESC].rsplit(" ", 1)[0] + "\u2026"
        attribution = f"\n\nSource: {ev.source}"
        if ev.url:
            attribution += f"\n{ev.url}"
        ie.add("description", (desc + attribution).strip())
        if ev.url:
            ie.add("url", ev.url)
        if ev.category:
            ie.add("categories", [ev.category])
        cal.add_component(ie)

    out.write_bytes(cal.to_ical())
    return out
