"""The pipeline: collect -> dedupe -> classify -> store -> publish.

This is the whole flow in one readable place. Each source is just an entry
in SOURCES; the rest of the function never needs to know how any given
event was obtained. Adding a source = add one line to SOURCES.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from adapters.events_calendar import EventsCalendarRest, ICSFeedAdapter
from adapters.juilliard import JuilliardAdapter
from adapters.llm_extract import LLMPageExtractAdapter
from adapters.localist import LocalistAdapter
from adapters.lied_center import LiedCenterAdapter
from adapters.lincoln_symphony import LincolnSymphonyAdapter
from adapters.opera_omaha import OperaOmahaAdapter
from adapters.symphony import SymphonyAdapter
from adapters.vesper import VesperAdapter
from adapters.world_concert_hall import WorldConcertHallAdapter  # noqa: F401 (retired source, see SOURCES)
from config import CHANNELS
from normalize import classify, dedupe
from publish.ics import write_ics
from publish.rss import write_rss
from publish.site import write_site
from store import Store

SITE_TITLE = "Omaha Classical Calendar"
SITE_URL = "https://hartmajr.github.io/omahaclassicalcal"
OUT_DIR = Path(__file__).resolve().parent / "public"
RSS_NAME = "feed.xml"

# The source registry. Local Omaha sources feed the "In Omaha" tab; the
# online sources are configured online_only, so they contribute just their
# streamed performances to the "Online" tab.
SOURCES = [
    # --- Local (in-person, Omaha area) ---
    LocalistAdapter(
        name="uno_localist",
        source_label="UNO School of Music",
        base_url="https://events.unomaha.edu",
        group_id=47382944493642,
        type_ids=[39447356775896],
    ),
    EventsCalendarRest(
        name="kvno",
        source_label="KVNO Arts Calendar",
        base_url="https://kvno.org",
    ),
    # Uses the .ics export. omahacm.org's "Disallow: /*?" catches this URL,
    # but that is a stock SEO rule about parameterised duplicates, not a
    # decision about their calendar feed -- which they publish with a
    # subscribe button precisely so software can fetch it. Documented in
    # config.ROBOTS_EXCEPTIONS; see the bar for adding entries there.
    ICSFeedAdapter(
        name="omaha_conservatory",
        source_label="Omaha Conservatory of Music",
        feed_url="https://omahacm.org/events/?ical=1",
    ),
    SymphonyAdapter(),
    # Orchestra Omaha runs The Events Calendar -- the same plugin as KVNO and
    # the Conservatory -- so it needs no new adapter code, just this entry.
    EventsCalendarRest(
        name="orchestra_omaha",
        source_label="Orchestra Omaha",
        base_url="https://orchestraomaha.org",
    ),
    VesperAdapter(),
    OperaOmahaAdapter(),
    # No feed and no regular markup -- concerts live in prose across two
    # series pages -- so this uses the reusable LLM page extractor.
    LLMPageExtractAdapter(
        name="omaha_chamber_music",
        source_label="Omaha Chamber Music Society",
        urls=["https://www.omahachambermusic.org/heritage-series",
              "https://www.omahachambermusic.org/summer-concert-series"],
        category="Chamber Music",
        series_hint="Omaha Chamber Music Society",
        default_venue="Omaha Conservatory of Music",
    ),

    # --- Lincoln (about an hour down I-80) ---
    # UNL publishes an official ICS feed, so the generic feed adapter serves
    # it with no new code -- same as the Omaha Conservatory.
    ICSFeedAdapter(
        name="unl_music",
        source_label="UNL Glenn Korff School of Music",
        feed_url="https://events.unl.edu/music/upcoming/?format=ics&limit=-1",
        channel="lincoln",
    ),
    LincolnSymphonyAdapter(),
    # UNL's presenting venue: touring classical acts mixed with Broadway,
    # comedy, and pop, so the classifier filters hard here (default verdict
    # is non-classical -- see SOURCE_PRIORITY). Day-precision dates publish
    # as all-day events; LSO co-presentations are skipped in favour of
    # LSO's own adapter.
    LiedCenterAdapter(),

    # --- Online (streamed institutional performances) ---
    # Oberlin is DISABLED, not forgotten: calendar.oberlin.edu's robots.txt
    # disallows automated access, and a daily job must not hammer a URL we've
    # been asked not to fetch. Re-enable only after confirming a sanctioned
    # path (their Localist /api/2/events, or a feed they point you to).
    # LocalistAdapter(
    #     name="oberlin_localist",
    #     source_label="Oberlin Conservatory",
    #     base_url="https://calendar.oberlin.edu",
    #     type_ids=[19263, 17936],
    #     online_only=True,
    #     channel="online",
    # ),
    JuilliardAdapter(online_only=True),

    # --- Broadcasts: RETIRED 2026-09-01 ---
    # World Concert Hall curates same-day/near-term broadcasts, which only
    # make sense with a daily build. The calendar now updates weekly, so the
    # channel was dropped rather than publish mostly-stale listings.
    # Re-enable by restoring this line, the "broadcast" entry in
    # config.CHANNELS, and the daily cron in .github/workflows/build.yml.
    # WorldConcertHallAdapter(),
]


def run(offline: bool = False, fail_under: int | None = None,
        only: str | None = None, publish: bool = True) -> dict:
    OUT_DIR.mkdir(exist_ok=True)
    run_started = datetime.now().isoformat()

    # 1. Collect from every source (resilient: one bad source can't sink the run).
    raw_events = []
    per_source = {}
    sources_ok: list[str] = []
    sources = SOURCES
    if only:
        sources = [a for a in SOURCES
                   if only.lower() in (a.source_label.lower() + " " + a.name.lower())]
        if not sources:
            raise SystemExit(f"No source matches {only!r}. Available: "
                             + ", ".join(a.name for a in SOURCES))
    for adapter in sources:
        try:
            evs = adapter.collect(offline=offline)
            per_source[adapter.source_label] = len(evs)
            warn = getattr(adapter, "truncated", None)
            if warn:
                per_source[adapter.source_label] = (
                    f"{len(evs)} events -- WARNING: source reports {warn[1]} "
                    f"but query-free mode fetched only {warn[0]}. Robots.txt "
                    "forbids pagination here; ask the site for a feed.")
            # Only a source that returned events counts as healthy. A broken
            # parser returns [] WITHOUT raising -- if that counted as "ok",
            # pruning would silently delete every event the source had.
            # A source that is legitimately empty simply keeps its old events
            # until it reports something again, which is the safe direction.
            if evs:
                sources_ok.append(adapter.source_label)
            raw_events.extend(evs)
        except Exception as exc:  # noqa: BLE001
            per_source[adapter.source_label] = f"ERROR: {exc}"

    # 2. Dedupe across sources, then 3. classify classical-vs-other.
    deduped = dedupe(raw_events)
    classified = classify(deduped)

    # 4. Persist (tracks newly-seen events for the RSS feed), then drop
    #    future events a healthy source stopped listing (= cancelled).
    store = Store()
    new_uids = store.upsert(classified)
    pruned = store.prune_missing(sources_ok, run_started)

    # 5. Publish from the store (the source of truth), one output per channel.
    #    --only is a DIAGNOSTIC mode: running one adapter must never overwrite
    #    the published site with a near-empty calendar built from one source.
    if only and publish:
        publish = False
    generated = datetime.now()
    groups = []
    for channel_id, label, ics_name in CHANNELS:
        events = store.upcoming(classical_only=True, channel=channel_id)
        groups.append({"id": channel_id, "label": label,
                       "ics": ics_name, "events": events})

    # Publish gate: abort BEFORE writing anything if the calendar has
    # collapsed. In CI this fails the job, so the previously deployed site
    # stays up instead of being replaced by an empty one.
    total = sum(len(g["events"]) for g in groups)
    if fail_under is not None and total < fail_under:
        raise RuntimeError(
            f"Refusing to publish: only {total} upcoming events "
            f"(threshold {fail_under}). Per-source results: {per_source}"
        )

    if not publish:
        return {
            "mode": "diagnostic (--only): no files written",
            "per_source": per_source,
            "collected": len(raw_events),
            "after_dedupe": len(deduped),
            "by_channel": {g["label"]: len(g["events"]) for g in groups},
        }

    for g in groups:
        write_ics(g["events"], OUT_DIR / g["ics"], f"{SITE_TITLE} — {g['label']}")

    all_upcoming = [e for g in groups for e in g["events"]]
    new_events = [e for e in store.by_uids(new_uids) if e.is_classical] or all_upcoming[:15]
    write_rss(new_events, OUT_DIR / RSS_NAME, title=SITE_TITLE, site_url=SITE_URL)
    import os as _os
    # UNLISTED=1 keeps the site out of search results while leaving the .ics
    # feeds fetchable -- calendar apps cannot authenticate, so a genuinely
    # access-controlled page would break every subscription.
    unlisted = _os.environ.get("UNLISTED") == "1"
    write_site(groups, OUT_DIR / "index.html", title=SITE_TITLE,
               rss_name=RSS_NAME, generated=generated, demo=offline,
               demo_note=_os.environ.get("SNAPSHOT_NOTE"), unlisted=unlisted)
    (OUT_DIR / "robots.txt").write_text(
        "User-agent: *\nDisallow: /\n" if unlisted
        else "User-agent: *\nAllow: /\n")

    return {
        "per_source": per_source,
        "collected": len(raw_events),
        "after_dedupe": len(deduped),
        "by_channel": {g["label"]: len(g["events"]) for g in groups},
        "newly_seen": len(new_uids),
        "pruned_cancelled": pruned,
        "out_dir": str(OUT_DIR),
    }
