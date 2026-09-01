"""Preflight: verify every source URL is allowed by its site's robots.txt.

Run before deploying, and whenever you add a source. A scheduled job hits
these URLs every day forever, so "am I allowed to fetch this?" deserves an
explicit answer.

    python scripts/check_robots.py

Exits nonzero only when a site's robots.txt genuinely DISALLOWS a URL, so it
can gate CI.

Why this fetches robots.txt itself instead of just using RobotFileParser:
urllib's parser treats a 401/403 *on robots.txt* as "disallow everything",
which is indistinguishable from a proxy, firewall, or outage blocking the
request. Reporting a network problem as a site's decision is the kind of
false alarm that gets a safety check ignored, so unreachable robots.txt is
reported as UNKNOWN (exit 0, but visible) rather than BLOCKED.

Real surprises this has caught:
  - kvno.org allows its HTML calendar but DISALLOWS its own ?ical=1 export.
  - calendar.oberlin.edu disallows its event search entirely (source disabled).
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from adapters.base import USER_AGENT  # noqa: E402
from config import ROBOTS_EXCEPTIONS  # noqa: E402

# Every endpoint the pipeline actually requests -- INCLUDING the query
# strings the adapters append at runtime. Checking bare paths is not enough:
# a site with "Disallow: /*?" permits /wp-json/... but forbids
# /wp-json/...?page=1, and only the second is what we really fetch.
URLS = [
    ("UNO School of Music (Localist API, as requested)",
     "https://events.unomaha.edu/api/2/events?days=365&pp=100&page=1"),
    ("KVNO (Events Calendar REST, as requested)",
     "https://kvno.org/wp-json/tribe/events/v1/events?page=1&per_page=50&start_date=now"),
    ("KVNO (REST, bare path fallback)",
     "https://kvno.org/wp-json/tribe/events/v1/events"),
    ("Omaha Conservatory (REST, bare path)",
     "https://omahacm.org/wp-json/tribe/events/v1/events"),
    ("Omaha Conservatory (.ics export -- known blocked by /*?)",
     "https://omahacm.org/events/?ical=1"),
    ("Omaha Symphony (season page)",
     "https://www.omahasymphony.org/season/2026-27-season"),
    ("Orchestra Omaha (REST, as requested)",
     "https://orchestraomaha.org/wp-json/tribe/events/v1/events?page=1&per_page=50&start_date=now"),
    ("Orchestra Omaha (REST, bare path fallback)",
     "https://orchestraomaha.org/wp-json/tribe/events/v1/events"),
    ("Vesper Concerts (season page)",
     "https://vesperconcerts.org/"),
    ("Omaha Chamber Music (Heritage series page)",
     "https://www.omahachambermusic.org/heritage-series"),
    ("Opera Omaha (season page)",
     "https://operaomaha.org/26-27-season/"),
    ("UNL Music (official ICS feed)",
     "https://events.unl.edu/music/upcoming/?format=ics&limit=-1"),
    ("Lincoln's Symphony (season page)",
     "https://lincolnsymphony.com/season-at-a-glance/"),
    ("Lied Center (events listing)",
     "https://www.liedcenter.org/events-page"),
    ("Juilliard (calendar, as requested)",
     "https://www.juilliard.edu/stage-beyond/performance/calendar?page=1"),
    ("World Concert Hall (Mastodon RSS)",
     "https://mastodon.world/@WConcertHall.rss"),
]

ALLOWED, BLOCKED, UNKNOWN = "ALLOWED", "BLOCKED", "UNKNOWN"


def _wildcard_disallows(robots_text: str, url: str) -> str | None:
    """Catch Google-style wildcard rules that stdlib robotparser ignores.

    urllib's RobotFileParser does not implement `*` inside a path or a
    trailing `$`, so a rule like `Disallow: /*?ical=1` reads as "allowed" --
    and that is precisely the rule blocking KVNO's .ics export. Missing the
    one case we already know about would make this check worthless, so
    wildcard rules under `User-agent: *` are matched here as a supplement.

    Returns the matching rule, or None.
    """
    import re

    path = urlparse(url).path + (f"?{urlparse(url).query}" if urlparse(url).query else "")
    applies = False
    for raw in robots_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            applies = value == "*"
        elif field == "disallow" and applies and value and ("*" in value or value.endswith("$")):
            pattern = re.escape(value)
            pattern = pattern.replace(r"\*", ".*")
            pattern = pattern[:-2] + "$" if pattern.endswith(r"\$") else pattern + ".*"
            if re.match(pattern, path):
                return value
    return None


def check(url: str) -> tuple[str, str]:
    """Return (verdict, detail)."""
    parts = urlparse(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        resp = httpx.get(robots_url, headers={"User-Agent": USER_AGENT},
                         timeout=20, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        return UNKNOWN, f"could not reach robots.txt ({type(exc).__name__})"

    if resp.status_code in (401, 403):
        return UNKNOWN, (f"robots.txt returned {resp.status_code} -- could be a "
                         "real restriction or a proxy/firewall; check manually")
    if resp.status_code >= 400:
        # No robots.txt (404 etc.) conventionally means everything allowed.
        return ALLOWED, f"no robots.txt ({resp.status_code})"

    rp = RobotFileParser()
    rp.parse(resp.text.splitlines())
    if not rp.can_fetch(USER_AGENT, url):
        return BLOCKED, "disallowed by robots.txt"
    wildcard = _wildcard_disallows(resp.text, url)
    if wildcard:
        return BLOCKED, f"disallowed by wildcard rule: Disallow: {wildcard}"
    return ALLOWED, "permitted by robots.txt"


def main() -> int:
    results = [(label, url, *check(url)) for label, url in URLS]
    for label, url, verdict, detail in results:
        print(f"{verdict:8} {label}\n         {url}\n         {detail}")

    excepted = [r for r in results if r[2] == BLOCKED and r[1] in ROBOTS_EXCEPTIONS]
    blocked = [r for r in results if r[2] == BLOCKED and r[1] not in ROBOTS_EXCEPTIONS]
    unknown = [r for r in results if r[2] == UNKNOWN]
    print()
    if unknown:
        print(f"{len(unknown)} URL(s) UNKNOWN -- robots.txt unreachable. Not "
              "treated as failure, but verify before trusting a live run.")
    if excepted:
        print(f"{len(excepted)} URL(s) blocked by robots.txt but covered by a "
              "documented exception in config.ROBOTS_EXCEPTIONS:")
        for label, url, _, _ in excepted:
            print(f"  - {label}\n    {ROBOTS_EXCEPTIONS[url][:120]}...")
        print()
    if blocked:
        print("DISALLOWED -- do not fetch these on a schedule:")
        for label, url, _, _ in blocked:
            print(f"  - {label}: {url}")
        print("Find a sanctioned feed, or contact the site, before enabling.")
        return 1
    print("No source URL is disallowed by robots.txt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
