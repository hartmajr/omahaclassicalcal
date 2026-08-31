"""Tests for the robots preflight, including the wildcard rules that
Python's stdlib RobotFileParser silently ignores.

    python tests/test_robots.py
"""
import importlib.util
import sys
from pathlib import Path
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from adapters.base import USER_AGENT  # noqa: E402

spec = importlib.util.spec_from_file_location("cr", ROOT / "scripts/check_robots.py")
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)

CASES = [
    ("allows all", "User-agent: *\nDisallow:\n", "https://x.org/events", True),
    ("wildcard blocks ical (real KVNO pattern)",
     "User-agent: *\nDisallow: /*?ical=1\nDisallow: /search\n",
     "https://x.org/artscalendar/list/?ical=1", False),
    ("wildcard does not over-block the html calendar",
     "User-agent: *\nDisallow: /*?ical=1\n", "https://x.org/artscalendar/list/", True),
    ("blocks search only", "User-agent: *\nDisallow: /search/\n",
     "https://x.org/api/2/events", True),
    ("blocks everything", "User-agent: *\nDisallow: /\n", "https://x.org/anything", False),
    ("trailing $ rule", "User-agent: *\nDisallow: /*.pdf$\n", "https://x.org/a/b.pdf", False),
    ("$ rule ignores non-match", "User-agent: *\nDisallow: /*.pdf$\n",
     "https://x.org/a/b.html", True),
    ("rule under another agent does not apply",
     "User-agent: BadBot\nDisallow: /*?ical=1\n", "https://x.org/list/?ical=1", True),
]


def allowed(body: str, url: str) -> bool:
    rp = RobotFileParser()
    rp.parse(body.splitlines())
    return rp.can_fetch(USER_AGENT, url) and not cr._wildcard_disallows(body, url)


def main() -> int:
    failures = 0
    for name, body, url, want in CASES:
        got = allowed(body, url)
        if got != want:
            failures += 1
            print(f"FAIL {name}: expected {want}, got {got}")
        else:
            print(f"PASS {name}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
