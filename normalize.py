"""Normalize: dedupe across sources, then classify each event as classical.

This is the brain of the pipeline. Adapters are dumb on purpose -- they
just fetch and shape. All the judgement lives here:

  dedupe()   -- the same concert can arrive from a primary source AND from
                KVNO's aggregator feed. Collapse on (title, date, venue),
                keeping the highest-priority source's copy (config.py).

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
from models import Event


def dedupe(events: list[Event]) -> list[Event]:
    best: dict[tuple[str, str, str], Event] = {}
    for ev in events:
        key = ev.match_key
        incumbent = best.get(key)
        if incumbent is None or _priority(ev) < _priority(incumbent):
            best[key] = ev
    return list(best.values())


def classify(events: list[Event]) -> list[Event]:
    for ev in events:
        ev.is_classical = _is_classical(ev)
        ev.tags = _tags(ev)
    return events


def _priority(ev: Event) -> int:
    return SOURCE_PRIORITY.get(ev.source, DEFAULT_PRIORITY)


def _is_classical(ev: Event) -> bool:
    cat = (ev.category or "").strip()
    haystack = f"{ev.title} {ev.category or ''} {ev.description or ''}".lower()
    has_composer = any(c in haystack for c in COMPOSER_KEYWORDS)
    has_classical_kw = any(good in haystack for good in CLASSICAL_KEYWORDS)

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
    if any(bad in haystack for bad in NON_CLASSICAL_KEYWORDS):
        return False
    # 4. Soft keyword vetoes, rescuable by any classical signal.
    if any(soft in haystack for soft in SOFT_NON_CLASSICAL_KEYWORDS) and not has_classical_kw:
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
