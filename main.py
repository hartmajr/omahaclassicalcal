"""Entry point.

    python main.py            # fetch live from every source
    python main.py --offline  # run against captured fixtures (no network)

Writes calendar.ics, feed.xml, and index.html into ./public/.
"""

from __future__ import annotations

import argparse
import json

from pipeline import run


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Omaha classical calendar.")
    ap.add_argument("--offline", action="store_true",
                    help="use fixtures instead of hitting the network")
    ap.add_argument("--fail-under", type=int, default=None, metavar="N",
                    help="exit nonzero WITHOUT publishing if fewer than N "
                         "upcoming events (guards against a broken source "
                         "wiping a live site)")
    ap.add_argument("--only", metavar="NAME",
                    help="run just one source (substring match), e.g. "
                         "--only juilliard. Useful for checking a single "
                         "adapter live without fetching everything.")
    args = ap.parse_args()

    summary = run(offline=args.offline, fail_under=args.fail_under, only=args.only)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
