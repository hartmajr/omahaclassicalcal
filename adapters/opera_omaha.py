"""Opera Omaha -- season-page HTML parse.

operaomaha.org is WordPress with a custom "production" post type. There is
no Events Calendar plugin and no .ics, so the 26/27 season page is the
source of truth. Each production block carries a title, a composer credit,
a venue, and ONE OR MORE performance dates:

    La bohème
    Nov. 13, 2026, 7:30PM
    Nov. 15, 2026, 2PM
    Orpheum Theater
    Music by Giacomo Puccini

The important structural detail: a production is not an event. "La bohème"
is two performances on different nights, and "The Pigeon Keeper" is three.
Someone subscribing to this calendar wants every date they could actually
attend, so this adapter emits one Event per performance date, titling
repeats "La bohème (Nov 15)" so a calendar app doesn't show two
indistinguishable entries.

Composer credits are folded into the description, which also gives the
classifier a strong signal (Puccini, Strauss, Handel are all canonical).

Selectors verified against the live page 2026-08-31 (9 performances across
5 productions parsed, with venues and composer credits; WordPress block
theme, see _from_html). The offline fixture holds the real captured 26/27
season.
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

SEASON_URL = "https://operaomaha.org/26-27-season/"

# "Sept. 27, 2026 | 7:00PM"  /  "Nov. 13, 2026, 7:30PM"  /  "Nov. 15, 2026, 2PM"
_PERF_RE = re.compile(
    r"([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),\s*(\d{4})\s*[|,]\s*(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?",
    re.IGNORECASE,
)
_MONTHS = {"sept": "Sep", "sept.": "Sep"}


class OperaOmahaAdapter(Adapter):
    name = "opera_omaha"
    source_label = "Opera Omaha"
    channel = "local"
    fixture_ext = "json"

    def fetch_raw(self) -> Any:
        return self._get(SEASON_URL).text

    def parse(self, raw: Any) -> list[Event]:
        if isinstance(raw, (list, dict)):
            rows = raw["productions"] if isinstance(raw, dict) else raw
            return self._from_rows(rows)
        return self._from_html(raw)

    def _from_rows(self, rows: list[dict]) -> list[Event]:
        events: list[Event] = []
        for r in rows:
            starts = [self._parse_perf(d) for d in r.get("dates", [])]
            starts = [s for s in starts if s]
            events.extend(self._expand(r, starts))
        return events

    def _from_html(self, html: str) -> list[Event]:
        # Verified against the live page 2026-08-31. WordPress block theme:
        # each production with announced dates is a div.wp-block-group whose
        # <h2 class="wp-block-heading has-text-align-center alignwide"> holds
        # the title, with performances as <strong> lines, then venue, "Music
        # by ...", and a /production/ "Learn More" link. One outer
        # wp-block-group wraps the whole season, so we start from each
        # production heading and take its nearest group -- never the wrapper.
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        seen: set[str] = set()
        for heading in soup.select("h2.wp-block-heading.has-text-align-center"):
            block = heading.find_parent("div", class_="wp-block-group")
            if block is None:
                continue
            text = re.sub(r"\s+", " ", block.get_text(" ", strip=True))
            matches = list(_PERF_RE.finditer(text))
            if not matches:
                continue
            link = block.find("a", href=re.compile(r"/production/"))
            title = heading.get_text(" ", strip=True)
            if not title or title in seen:
                continue
            seen.add(title)
            venue = None
            for v in ("Orpheum Theater", "Holland Performing Arts Center",
                      "The Rose Theater", "Slowdown"):
                if v in text:
                    venue = v
                    break
            comp = re.search(r"Music by ([A-Z][\w .'-]+?)(?=\s+Libretto\b|[.,;“\"]|$)", text)
            starts = [s for s in (self._parse_perf(m.group(0)) for m in matches) if s]
            events.extend(self._expand({
                "title": title, "venue": venue,
                "url": link.get("href") if link else SEASON_URL,
                "composer": comp.group(1).strip() if comp else None,
            }, starts))
        return events

    def _expand(self, r: dict, starts: list[datetime]) -> list[Event]:
        """One Event per performance date; disambiguate repeats by date."""
        events = []
        multi = len(starts) > 1
        for start in starts:
            title = r["title"].strip()
            if multi:
                title = f"{title} ({fmt(start, '%b %-d')})"
            desc = []
            if r.get("composer"):
                desc.append(f"Music by {r['composer']}.")
            if r.get("description"):
                desc.append(r["description"])
            events.append(Event(
                title=title,
                start=start,
                venue=r.get("venue"),
                url=r.get("url"),
                description=" ".join(desc) or None,
                category="Opera",
                source=self.source_label,
            ))
        return events

    def _parse_perf(self, text: str) -> datetime | None:
        m = _PERF_RE.search(text)
        if not m:
            return None
        month, day, year, hour, minute, ampm = m.groups()
        month = _MONTHS.get(month.lower(), month[:3])
        try:
            return dtparse.parse(f"{month} {day} {year} {hour}:{minute or '00'} {ampm.upper()}M")
        except (ValueError, OverflowError):
            return None
