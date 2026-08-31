"""Omaha Symphony -- HTML parse of the season page.

The Symphony runs a custom Craft CMS site with no public API. Its /calendar
page is JavaScript-rendered (a plain fetch returns an empty shell), but the
/season/<year> page is fully server-rendered: every concert is a uniform
block carrying a series label, a date (or date range), a title, a blurb,
and ticket links. We parse that.

Selectors verified against the live season page 2026-08-31 (37 events
parsed, all with series + per-concert URLs). The page uses Tachyons
utility classes with no semantic hooks; see _parse_html for the card
shape being relied on. The offline fixture is the real captured season
data so the rest of the pipeline is exercised correctly regardless.

The series label is the gold here: it drives classical-vs-pops filtering
downstream (Masterworks / Symphony Joslyn = classical; LIVE / Family /
Community / Forte = not), per config.py.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from dateutil import parser as dtparse

from adapters.base import Adapter
from models import Event

SEASON_URL = "https://www.omahasymphony.org/season/2026-27-season"
# Map the season's natural-language date lines to real datetimes. The page
# uses forms like "September 25 - September 26, 2026" or "July 4, 2026".
_DATE_RANGE = re.compile(
    r"([A-Z][a-z]+ \d{1,2})(?:\s*-\s*([A-Z][a-z]+ \d{1,2}))?,?\s*(\d{4})"
)


class SymphonyAdapter(Adapter):
    name = "omaha_symphony"
    source_label = "Omaha Symphony"
    fixture_ext = "json"   # fixture is the parsed season (see honesty note above)

    def fetch_raw(self) -> Any:
        return self._get(SEASON_URL).text

    def parse(self, raw: Any) -> list[Event]:
        # Offline path: fixture is already-structured JSON of the real season.
        if isinstance(raw, (list, dict)):
            return self._parse_fixture(raw)
        return self._parse_html(raw)

    def _parse_fixture(self, raw: Any) -> list[Event]:
        rows = raw["concerts"] if isinstance(raw, dict) else raw
        events: list[Event] = []
        for r in rows:
            start, end = self._dates(r["date_text"], r.get("title", ""))
            if not start:
                continue
            events.append(
                Event(
                    title=r["title"].strip(),
                    start=start,
                    end=end,
                    venue=r.get("venue"),
                    url=r.get("url"),
                    description=r.get("description"),
                    category=r.get("series"),
                    source=self.source_label,
                )
            )
        return events

    def _parse_html(self, html: str) -> list[Event]:
        # Verified against the live page 2026-08-31. The site is Craft CMS
        # styled with Tachyons utility classes, so there are no semantic
        # class names to hook on. Each concert is an <article>:
        #   <article class="ph2-ns pb3 h-100">
        #     <span>Masterworks</span>              <- series: bare, class-less
        #     <span class="db f5 tc">September 25 - September 26, 2026</span>
        #     <h1 class="pn-ec ...">Falletta Conducts Gershwin & Strauss</h1>
        #     <span class="db pn f5">blurb...</span>
        #     <a href=".../concerts/<slug>">Read More</a>
        soup = BeautifulSoup(html, "html.parser")
        events: list[Event] = []
        for card in soup.find_all("article"):
            title_el = card.find(["h1", "h2", "h3"])
            if not title_el:
                continue
            text = re.sub(r"\s+", " ", card.get_text(" ", strip=True))
            m = _DATE_RANGE.search(text)
            if not m:
                continue
            start, end = self._dates(m.group(0), title_el.get_text(strip=True))
            if not start:
                continue
            # The series label is the card's only class-less span; everything
            # else (date, blurb) carries utility classes.
            series = None
            for sp in card.find_all("span", class_=False):
                label = sp.get_text(strip=True)
                if label and len(label) < 40 and not any(c.isdigit() for c in label):
                    series = label
                    break
            # A card holds /concerts/ links to BOTH the series page (its text
            # is the series label) and the concert's own page (image + "Read
            # More"). Keep the concert one.
            url = None
            for a in card.find_all("a", href=re.compile(r"/concerts/")):
                if a.get_text(strip=True) != series:
                    url = a["href"]
                    break
            desc_el = card.select_one("span.pn")
            events.append(
                Event(
                    title=re.sub(r"\s+", " ", title_el.get_text(strip=True)),
                    start=start,
                    end=end,
                    url=url,
                    description=desc_el.get_text(" ", strip=True) if desc_el else None,
                    category=series,
                    source=self.source_label,
                )
            )
        return events

    def _dates(self, date_text: str, _title: str) -> tuple[datetime | None, datetime | None]:
        m = _DATE_RANGE.search(date_text.replace("\n", " "))
        if not m:
            return None, None
        first, second, year = m.groups()
        start = dtparse.parse(f"{first} {year}")
        end = dtparse.parse(f"{second} {year}") if second else None
        return start, end
