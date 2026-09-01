"""Normalize: dedupe across sources, then classify each event as classical.

This is the brain of the pipeline. Adapters are dumb on purpose -- they
just fetch and shape. All the judgement lives here:

  dedupe()   -- the same concert can arrive from a primary source AND from
                KVNO's aggregator feed. Two passes: collapse exact
                (title, date, venue) matches, then collapse events at the
                same instant and compatible venue whose titles are merely
                similar -- live data showed the aggregator's copies rarely
                match verbatim ("La bohème" vs "La bohème (Nov 13)"; "The
                Valencia Bryton [sic] Project to Perform" vs "The Valencia
                Baryton Project"). Highest-priority source wins (config.py).
                Also normalizes every start/end to naive Omaha local time
                first: sources disagree (UNL publishes UTC, most others
                local), which breaks date-keyed matching and text-ordered
                SQL sorting for evening events.

  classify() -- decide is_classical. Category wins when we know it
                (Symphony series), otherwise fall back to keyword signals.
                KVNO is broad arts, so unmatched KVNO events default to
                non-classical rather than slipping through.

The classifier is intentionally a transparent heuristic. It's also the
exact seam where you'd later drop in an LLM call for the messy sources
(Chamber Music Society) -- same input (an Event), same output (is_classical
+ tags), just a smarter implementation.
"""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from functools import lru_cache

from config import (
    CLASSICAL_CATEGORIES,
    CLASSICAL_KEYWORDS,
    COMPOSER_KEYWORDS,
    DEFAULT_PRIORITY,
    NON_CLASSICAL_CATEGORIES,
    NON_CLASSICAL_KEYWORDS,
    SOFT_NON_CLASSICAL_CATEGORIES,
    SOFT_NON_CLASSICAL_KEYWORDS,
    SOURCE_PRIORITY,
)
from models import Event, _slug

try:
    from zoneinfo import ZoneInfo
    _LOCAL_TZ = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover
    _LOCAL_TZ = None


def _localize(ev: Event) -> None:
    """Normalize start/end to naive Omaha wall-clock time.

    Sources disagree: UNL's feed publishes UTC (+00:00), Localist uses
    -05:00 offsets, HTML parses are naive local. Mixed forms break both
    match_key (a 7:30pm concert lands on tomorrow's UTC date) and the
    store's text ORDER BY start (UTC strings interleave wrongly with local
    ones -- the bug that scrambled the Lincoln tab, 2026-09-01).
    """
    if _LOCAL_TZ is None:
        return
    if ev.start.tzinfo is not None:
        ev.start = ev.start.astimezone(_LOCAL_TZ).replace(tzinfo=None)
    if ev.end is not None and ev.end.tzinfo is not None:
        ev.end = ev.end.astimezone(_LOCAL_TZ).replace(tzinfo=None)


def dedupe(events: list[Event]) -> list[Event]:
    for ev in events:
        _localize(ev)
    # Pass 1: exact (slugged title, date, venue) match.
    best: dict[tuple[str, str, str], Event] = {}
    for ev in events:
        key = ev.match_key
        incumbent = best.get(key)
        if incumbent is None or _priority(ev) < _priority(incumbent):
            best[key] = ev
    # Pass 2: two listings at the same minute with compatible venues and
    # merely-similar titles are the same concert seen through different
    # sources' copy. Only CROSS-source pairs collapse: one source listing
    # two events at the same instant is asserting they're distinct (UNL
    # lists its Symphony Orchestra and University Orchestra concerts at the
    # same time -- similar titles, different events). Skipped for all-day
    # events, whose midnight "start" is a fabrication -- two all-day events
    # on one day are genuinely distinct.
    survivors: list[Event] = []
    by_start: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for ev in best.values():
        if ev.all_day:
            survivors.append(ev)
        else:
            by_start[(ev.start.isoformat(), ev.channel)].append(ev)
    for group in by_start.values():
        kept: list[Event] = []
        for ev in sorted(group, key=_priority):
            if not any(k.source != ev.source and _same_event(ev, k)
                       for k in kept):
                kept.append(ev)
        survivors.extend(kept)
    return survivors


def _same_event(a: Event, b: Event) -> bool:
    """Same start instant is a given; require venue compatibility (one slug
    contains the other, or one is missing) and title similarity (containment
    or difflib ratio) before calling two listings the same concert."""
    va, vb = _slug(a.venue), _slug(b.venue)
    if va and vb and va not in vb and vb not in va:
        return False
    ta, tb = _slug(a.title), _slug(b.title)
    if ta in tb or tb in ta:
        return True
    return SequenceMatcher(None, ta, tb).ratio() >= 0.6


def classify(events: list[Event]) -> list[Event]:
    for ev in events:
        ev.is_classical = _is_classical(ev)
        ev.tags = _tags(ev)
    return events


def _priority(ev: Event) -> int:
    return SOURCE_PRIORITY.get(ev.source, DEFAULT_PRIORITY)


@lru_cache(maxsize=None)
def _pattern(keywords: frozenset[str]) -> re.Pattern:
    """One compiled alternation per keyword set, matched at word boundaries.

    Plain substring matching kept misfiring on real data: 'part' (Arvo Pärt)
    matched 'participants', 'glass' (Philip Glass) matched 'Douglass',
    'new music' matched 'new musical', 'organ' matched 'organization'.
    (?<!\\w)/(?!\\w) instead of \\b so keywords ending in punctuation
    ('canceled:') still work.
    """
    alternation = "|".join(sorted(re.escape(k) for k in keywords))
    return re.compile(r"(?<!\w)(?:" + alternation + r")(?!\w)")


def _has_any(keywords: set[str], haystack: str) -> bool:
    return _pattern(frozenset(keywords)).search(haystack) is not None


def _is_classical(ev: Event) -> bool:
    cat = (ev.category or "").strip()
    haystack = f"{ev.title} {ev.category or ''} {ev.description or ''}".lower()
    has_composer = _has_any(COMPOSER_KEYWORDS, haystack)
    has_classical_kw = _has_any(CLASSICAL_KEYWORDS, haystack)

    # 1. Trust an explicit, known category first.
    if cat in CLASSICAL_CATEGORIES.get(ev.source, set()):
        return True
    if cat in NON_CLASSICAL_CATEGORIES.get(ev.source, set()):
        return False
    # 2. Soft category (e.g. Symphony's LIVE series, a pops/film mixed bag):
    #    non-classical unless a canonical composer name appears. Instrument
    #    words can't rescue here -- every LIVE blurb says "Symphony".
    if cat in SOFT_NON_CLASSICAL_CATEGORIES.get(ev.source, set()):
        return has_composer
    # 3. Firm keyword vetoes.
    if _has_any(NON_CLASSICAL_KEYWORDS, haystack):
        return False
    # 4. Soft keyword vetoes, rescuable by any classical signal.
    if _has_any(SOFT_NON_CLASSICAL_KEYWORDS, haystack) and not has_classical_kw:
        return False
    # 5. Positive signal.
    if has_classical_kw:
        return True
    # 6. Default by source type.
    return _priority(ev) == 0


def _tags(ev: Event) -> list[str]:
    tags = []
    if ev.is_classical:
        tags.append("classical")
    else:
        tags.append("other-arts")
    if ev.category:
        tags.append(ev.category.lower().replace(" ", "-"))
    return tags
