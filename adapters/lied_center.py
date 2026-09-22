"""Lied Center for Performing Arts -- Lincoln's presenting venue.

UNL's performing-arts presenter: touring orchestras, chamber ensembles, and
recitalists share the season with Broadway tours, comedians, and pop acts,
so the classifier does real filtering here (the source's default verdict is
non-classical -- see SOURCE_PRIORITY in config.py).

The site is Drupal; /events (-> /events-page) renders every upcoming event
as a Views row (verified against the live page 2026-09-01):

    <div class="views-row ...">
      <div class="event-type">Season Event</div>
      <div class="title"><a href="/event/daniil-trifonov">Daniil Trifonov</a></div>
      <div class="date">March 22, 2027</div>
      <div class="body"><p>teaser prose...</p></div>

The listing carries day-precision dates only ("October 1, 2026", ranges
like "September 25-26, 2026") and NO venue at all. Both live on each
/event/ page, in Drupal fields:

    <div class="field-name-field-location">...<div class="field-item">
      Kimball Hall
    <div class="field-name-field-showtimes-links">...<a>
      Tuesday, September 22, 2026 | 7:30PM

Venue matters more than it looks. The Lied presents in halls it does not
contain -- Kimball Hall is UNL's, blocks away -- so publishing the
building as every event's location was not merely vague but wrong, and a
wrong LOCATION sends a subscriber to the wrong place while a missing one
only makes them click. Showtimes come along for the same request, so
events now publish at their real times instead of all-day, and a card
spanning two dates becomes the two performances it actually is.

That costs one request per event against a 10-second robots.txt
crawl-delay, which is why the listing alone was used while the build ran
daily. Results are cached per event URL (lied_center_cache.json, committed
like the LLM caches) and pruned to the current listing, so a normal week
fetches only what was announced since the last run; entries expire after
CACHE_TTL_DAYS so a corrected hall or time is picked up. A cold start is bounded by
MAX_DETAIL_FETCHES and written back every CACHE_FLUSH_EVERY pages, so a
long run that dies part-way keeps what it had. Anything not reached -- or
an event page that fails -- keeps the old all-day-plus-building fallback
and is retried next run. robots.txt allows event pages.

Lincoln's Symphony concerts at the Lied are skipped here: LSO's own
adapter is their source of record (with showtimes), and the Lied lists
them under different titles ("Emanuel Ax with Lincoln's Symphony
Orchestra" vs LSO's "Emanuel Ax"), which defeats fuzzy dedupe.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup
from dateutil import parser as dtparse

from adapters.base import Adapter
from dateformat import fmt
from models import Event

EVENTS_URL = "https://www.liedcenter.org/events-page"
SITE = "https://www.liedcenter.org"
VENUE = "Lied Center for Performing Arts"

# Detail-page fetching. robots.txt asks for Crawl-delay: 10, so each extra
# page costs ten seconds -- which is why the listing alone was used at
# first, when the build ran daily. At a weekly cadence, with results cached
# per event URL, the steady-state cost is the handful of events announced
# since last Monday. The cap bounds a cold start (or a season dump) to a
# predictable run; anything not reached keeps the listing-only fallback and
# is picked up next week.
DETAIL_DELAY_SECONDS = 10
# Headroom, not a target. Exceeding the cap is silent -- those events fall
# back to all-day at the building name, which looks exactly like the bug
# this enrichment fixed and reports nothing. Keep it comfortably above a
# full season (55 events in 2026-27), since every entry expires on the same
# day the cache was first warmed and so comes due together.
MAX_DETAIL_FETCHES = 120
# Flush part-way through a long run: a cold start or a TTL expiry is ~10
# minutes of fetching, and losing all of it to one dropped connection means
# repeating the whole batch next week.
CACHE_FLUSH_EVERY = 10
# A venue or showtime can be corrected after we first read it, so entries
# go stale rather than living forever.
CACHE_TTL_DAYS = 30
CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "lied_center_cache.json")

# "October 1, 2026" / "September 25-26, 2026" / "May 31-June 2, 2027"
_DATE_RE = re.compile(
    r"([A-Z][a-z]+)\s+(\d{1,2})(?:\s*[-–]\s*(?:([A-Z][a-z]+)\s+)?(\d{1,2}))?,\s*(\d{4})"
)


class LiedCenterAdapter(Adapter):
    name = "lied_center"
    source_label = "Lied Center for Performing Arts"
    channel = "lincoln"
    fixture_ext = "json"

    def fetch_raw(self) -> Any:
        """Listing rows, enriched with each event's hall and showtimes.

        Network work stays here so parse() remains pure over the rows,
        whether they came from the live site or the fixture.
        """
        rows = self._rows_from_html(self._get(EVENTS_URL).text)
        self._enrich(rows)
        return rows

    def parse(self, raw: Any) -> list[Event]:
        rows = raw if isinstance(raw, list) else self._rows_from_html(raw)
        events = []
        for r in rows:
            events.extend(self._build_all(r))
        return events

    def _rows_from_html(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        rows: list[dict] = []
        for card in soup.select("div[class*=views-row]"):
            title_el = card.select_one(".title a")
            date_el = card.select_one(".date")
            if not title_el or not date_el:
                continue
            body_el = card.select_one(".body p")
            type_el = card.select_one(".event-type")
            href = title_el.get("href") or ""
            rows.append({
                "title": title_el.get_text(" ", strip=True),
                "date_text": date_el.get_text(" ", strip=True),
                "url": SITE + href if href.startswith("/") else href,
                "description": body_el.get_text(" ", strip=True) if body_el else None,
                "event_type": type_el.get_text(strip=True) if type_el else None,
            })
        return rows

    def _build_all(self, r: dict) -> list[Event]:
        """One event per published showtime, else one all-day event.

        A card that spans dates ("September 25-26") is a single all-day
        entry without showtimes and two timed entries with them, which is
        what the run actually is.
        """
        title = re.sub(r"\s+", " ", r["title"]).strip()
        # LSO concerts at the Lied come from LSO's own adapter (see module
        # docstring); the apostrophe varies between ' and ’ on the page.
        if "lincoln's symphony" in title.lower().replace("’", "'"):
            return []
        # The hall, when we read it from the event page. Falling back to the
        # building is deliberate but imprecise: the Lied programmes halls it
        # does not contain (Kimball Hall is UNL's, blocks away), so a fallback
        # is a guess and is never published as though it had been read.
        venue = r.get("venue") or VENUE
        common = dict(
            venue=venue,
            url=r.get("url"),
            description=r.get("description"),
            category=r.get("event_type"),
            source=self.source_label,
        )
        starts = self._showtimes(r.get("showtimes"))
        if starts:
            per_day = Counter(st.date() for st in starts)
            return [
                Event(title=self._label(title, st, per_day[st.date()] > 1),
                      start=st, all_day=False, **common)
                for st in starts
            ]
        start, end = self._dates(r["date_text"])
        if not start:
            return []
        return [Event(title=title, start=start, end=end, all_day=True, **common)]

    def _label(self, title: str, start: datetime, repeats: bool) -> str:
        """Distinguish a matinee from an evening show.

        Title, date and venue ARE the dedupe key (Event.match_key), so two
        performances on one day would otherwise collapse into one and lose
        a showtime -- which is exactly what happens to Mamma Mia's 2pm and
        7:30pm. Same fix the LSO adapter makes for Deck the Halls.
        """
        if not repeats:
            return title
        pat = "%-I%p" if start.minute == 0 else "%-I:%M%p"
        return f"{title} ({fmt(start, pat)})".replace("AM", "am").replace("PM", "pm")

    def _showtimes(self, raw: Any) -> list[datetime]:
        """Parse cached showtime stamps ("2026-09-22T19:30")."""
        out = []
        for stamp in raw or []:
            try:
                out.append(datetime.fromisoformat(stamp))
            except (ValueError, TypeError):
                continue
        return sorted(set(out))

    def _dates(self, text: str) -> tuple[datetime | None, datetime | None]:
        m = _DATE_RE.search(text or "")
        if not m:
            return None, None
        m1, d1, m2, d2, year = m.groups()
        try:
            start = dtparse.parse(f"{m1} {d1} {year}")
            end = dtparse.parse(f"{m2 or m1} {d2} {year}") if d2 else None
        except (ValueError, OverflowError):
            return None, None
        return start, end

    # ---- detail pages (hall + showtimes), cached per event URL ----

    def _enrich(self, rows: list[dict]) -> None:
        """Fill rows with the hall and showtimes from each event page.

        Cached by URL and pruned to the current listing, so the committed
        cache stays the size of a season and a normal week fetches only
        what was announced since the last run.
        """
        cache = self._load_cache()
        fresh = {u: e for u, e in cache.items() if self._is_fresh(e)}
        urls = [r["url"] for r in rows if r.get("url")]
        # The listing is known up front, so pruning to it is valid at any
        # point -- which is what lets the cache be written mid-run.
        keep = set(urls)

        def flush() -> None:
            pruned = {u: e for u, e in fresh.items() if u in keep}
            if pruned != cache:
                self._save_cache(pruned)

        fetched = unsaved = 0
        for url in urls:
            if url in fresh:
                continue
            if fetched >= MAX_DETAIL_FETCHES:
                continue
            if fetched:
                time.sleep(DETAIL_DELAY_SECONDS)  # robots.txt Crawl-delay
            try:
                entry = self._detail(self._get(url).text)
            except Exception:
                # One unreachable event page must not cost the listing;
                # it falls back to all-day + building and retries next run.
                continue
            finally:
                fetched += 1
            entry["fetched"] = datetime.now().date().isoformat()
            fresh[url] = entry
            unsaved += 1
            if unsaved >= CACHE_FLUSH_EVERY:
                flush()
                unsaved = 0
        for r in rows:
            entry = fresh.get(r.get("url") or "")
            if entry:
                r["venue"] = entry.get("venue")
                r["showtimes"] = entry.get("showtimes")
        flush()

    def _is_fresh(self, entry: Any) -> bool:
        if not isinstance(entry, dict):
            return False
        try:
            stamp = datetime.fromisoformat(entry["fetched"])
        except (KeyError, ValueError, TypeError):
            return False
        return datetime.now() - stamp < timedelta(days=CACHE_TTL_DAYS)

    def _detail(self, html: str) -> dict:
        """Hall and showtimes from one event page's Drupal fields."""
        soup = BeautifulSoup(html, "html.parser")
        venue_el = soup.select_one(".field-name-field-location .field-item")
        venue = venue_el.get_text(" ", strip=True) if venue_el else None
        showtimes = []
        for el in soup.select(".field-name-field-showtimes-links .field-item"):
            # "Tuesday, September 22, 2026 | 7:30PM"
            text = el.get_text(" ", strip=True).replace("|", " ")
            try:
                showtimes.append(dtparse.parse(text, fuzzy=True).isoformat())
            except (ValueError, OverflowError, TypeError):
                continue
        return {"venue": venue or None, "showtimes": sorted(set(showtimes))}

    def _load_cache(self) -> dict:
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self, cache: dict) -> None:
        try:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=1, sort_keys=True)
        except OSError:
            pass  # cache is an optimization, never fatal
