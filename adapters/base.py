"""Base class every source adapter inherits.

The contract is deliberately tiny:
  - fetch_raw()      hits the live source over the network
  - parse(raw)       turns raw bytes/json into list[Event] (pure, testable)
  - fixture_path     points at a captured sample so the whole pipeline can
                     run offline (in CI, in a sandbox, or just to develop
                     without hammering the real sites)

collect(offline=...) ties them together. Keeping fetch and parse separate
means the fragile part (network) and the logic part (parsing) can be
tested independently, and the same parser runs over live data or fixtures.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from models import Event

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
USER_AGENT = (
    "OmahaClassicalCalendar/0.1 (+https://hartmajr.github.io/omahaclassicalcal/; "
    "mailto:omahaadultpianoclub@gmail.com; "
    "a non-commercial community calendar that links back to each source)"
)


class Adapter(ABC):
    name: str            # short id, also the fixture filename stem
    source_label: str    # human-readable, stored on each Event.source
    channel: str = "local"   # which tab/output; overridden per source
    fixture_ext: str = "json"

    @abstractmethod
    def fetch_raw(self) -> Any:
        ...

    @abstractmethod
    def parse(self, raw: Any) -> list[Event]:
        ...

    def fixture_path(self) -> Path:
        return FIXTURES / f"{self.name}.{self.fixture_ext}"

    def load_fixture(self) -> Any:
        # Explicit UTF-8: Windows defaults read_text to cp1252, which chokes
        # on curly quotes in captured prose.
        text = self.fixture_path().read_text(encoding="utf-8")
        return json.loads(text) if self.fixture_ext == "json" else text

    def collect(self, offline: bool = False) -> list[Event]:
        raw = self.load_fixture() if offline else self.fetch_raw()
        events = self.parse(raw)
        for ev in events:
            ev.source = self.source_label
            ev.channel = self.channel
        return events

    # Shared HTTP helper with a polite, identifying User-Agent.
    def _get(self, url: str, **params: Any) -> httpx.Response:
        resp = httpx.get(
            url,
            params=params or None,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
            follow_redirects=True,
        )
        if resp.status_code in (401, 403):
            raise PermissionError(
                f"{self.source_label}: {resp.status_code} for {url}. The site "
                "refused our identified bot. Check robots.txt "
                "(python scripts/check_robots.py); if it disallows this path, "
                "disable the source. If robots.txt permits it, this is likely "
                "bot protection -- ask the site for a sanctioned feed or "
                "permission. Do NOT disguise the User-Agent as a browser: "
                "evading a refusal is exactly what this project avoids."
            )
        resp.raise_for_status()
        return resp
