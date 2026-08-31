"""World Concert Hall -- curated global live classical broadcasts.

The worldconcerthall.com site itself publishes no feed and blocks scraping
via robots.txt, but WCH posts every pick to Mastodon, and every Mastodon
account exposes a built-in RSS feed at <profile-url>.rss. That feed is the
sanctioned way in.

The catch is shape: each RSS item is a free-text post ("Wagner's 'Die
Walkuere' from the Bavarian State Opera, cond. Jurowski. Live.") plus a link
and a timestamp -- not structured fields. So this adapter pairs the RSS with
an LLM extraction step (the same pattern the Omaha Chamber Music Society
needs): fetch the toots, then ask a model to turn each into
{title, performers, venue, start} JSON.

Everything WCH lists is a live broadcast, so these all land in the
"broadcast" channel (its own tab + broadcasts.ics). The post time is used as
the broadcast start -- WCH posts around air time -- which is approximate;
see README caveats.

Live path needs ANTHROPIC_API_KEY in the environment. The offline fixture is
already-extracted events, so the demo runs without any API call.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import feedparser
import httpx
from dateutil import parser as dtparse

from adapters.base import Adapter
from models import Event

RSS_URL = "https://mastodon.world/@WConcertHall.rss"
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"
# Cache of toot-url -> extracted JSON, so re-running never re-extracts the
# same post (saves API calls; results stay stable). Committed alongside
# events.db by the CI workflow.
CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "wch_cache.json")

_EXTRACT_PROMPT = """You are given a short social-media post announcing a live \
classical music broadcast. Extract its details.

Post: {text}
Posted at (ISO): {published}

Return ONLY a JSON object, no prose, with keys:
  "title": concise concert title (work + performer/orchestra), string
  "venue": originating hall / opera house / city if stated, else null
  "is_classical": true unless it is clearly non-classical (jazz, pop), bool
Use the post's wording. If it is not a concert announcement, return \
{{"title": null}}."""


class WorldConcertHallAdapter(Adapter):
    name = "world_concert_hall"
    source_label = "World Concert Hall"
    channel = "broadcast"
    fixture_ext = "json"

    def fetch_raw(self) -> Any:
        text = self._get(RSS_URL).text
        feed = feedparser.parse(text)
        toots = []
        for entry in feed.entries:
            body = _strip_html(entry.get("summary") or entry.get("title") or "")
            if not body:
                continue
            toots.append({
                "text": body,
                "url": entry.get("link"),
                "published": entry.get("published"),
            })
        return {"toots": toots}

    def parse(self, raw: Any) -> list[Event]:
        # Offline fixture path: already-structured events.
        if isinstance(raw, dict) and "events" in raw:
            return [self._build(r) for r in raw["events"]]
        if isinstance(raw, list):
            return [self._build(r) for r in raw]
        # Live path: LLM-extract each toot (cached by toot URL).
        cache = self._load_cache()
        dirty = False
        events: list[Event] = []
        for toot in raw.get("toots", []):
            key = toot.get("url") or toot["text"][:120]
            if key in cache:
                extracted = cache[key]
            else:
                extracted = self._extract(toot)
                cache[key] = extracted
                dirty = True
            if extracted and extracted.get("title"):
                extracted = dict(extracted)
                extracted["url"] = toot.get("url")
                extracted["start"] = toot.get("published")
                events.append(self._build(extracted))
        if dirty:
            self._save_cache(cache)
        return events

    def _load_cache(self) -> dict:
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self, cache: dict) -> None:
        try:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=1)
        except OSError:
            pass  # cache is an optimization, never fatal

    def _build(self, r: dict) -> Event:
        return Event(
            title=r["title"].strip(),
            start=dtparse.parse(r["start"]),
            venue=r.get("venue") or "Live broadcast",
            url=r.get("url"),
            description=r.get("description"),
            category="Live broadcast",
            source=self.source_label,
        )

    def _extract(self, toot: dict) -> dict | None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "WorldConcertHall live extraction needs ANTHROPIC_API_KEY "
                "(run with --offline to use the fixture instead)."
            )
        prompt = _EXTRACT_PROMPT.format(text=toot["text"], published=toot["published"])
        resp = httpx.post(
            API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = "".join(b.get("text", "") for b in resp.json().get("content", []))
        try:
            data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        except (json.JSONDecodeError, ValueError):
            return None
        return data


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
