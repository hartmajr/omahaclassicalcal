"""The one shared shape every adapter must produce.

The whole architecture rests on this: no matter how an event is sourced
(JSON API, .ics feed, or HTML scrape), it gets turned into an Event with
these fields. Everything downstream -- dedupe, classification, and the
.ics / RSS / website publishers -- only ever touches this object, never
the raw source data. Adding a new source later is just writing one more
adapter that returns a list[Event].
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime


def _slug(text: str | None) -> str:
    """Lowercase, strip punctuation, collapse whitespace -- for matching."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Event:
    title: str
    start: datetime
    source: str                       # human label, e.g. "Omaha Symphony"
    end: datetime | None = None
    venue: str | None = None
    url: str | None = None
    description: str | None = None
    category: str | None = None       # the source's own series/category
    all_day: bool = False

    # Filled in by the normalize step, not the adapters:
    is_classical: bool | None = None
    tags: list[str] = field(default_factory=list)

    # Which tab/output this event belongs to, set by the adapter:
    #   "local"     -> in-person Omaha
    #   "online"    -> streamed institutional performances (Juilliard, Oberlin)
    #   "broadcast" -> curated global live broadcasts (World Concert Hall)
    channel: str = "local"

    # When our pipeline first saw this event (set on store reads); used as
    # the RSS pubDate so feed readers sort by announcement, not concert date.
    first_seen: datetime | None = None

    @property
    def is_online(self) -> bool:
        """Watchable remotely (anything that isn't a local in-person event)."""
        return self.channel != "local"

    @property
    def uid(self) -> str:
        """Stable identity for an event.

        Used two ways: as the dedupe key (so the same concert from two
        sources collapses to one) and as the iCalendar UID (so a calendar
        app updates an existing entry instead of creating a duplicate when
        details change). Deliberately based on *what and when and where*,
        not the source -- that's what makes cross-source dedupe work.
        """
        basis = f"{_slug(self.title)}|{self.start.date().isoformat()}|{_slug(self.venue)}"
        digest = hashlib.sha1(basis.encode()).hexdigest()[:16]
        return f"{digest}@omaha-classical-calendar"

    @property
    def match_key(self) -> tuple[str, str, str]:
        """Looser key for fuzzy dedupe (title + date + venue, all slugged)."""
        return (_slug(self.title), self.start.date().isoformat(), _slug(self.venue))
