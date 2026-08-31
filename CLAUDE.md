# Project context

Aggregates classical-music events across Omaha (and Lincoln) into a
subscribable `.ics`, an RSS feed, and a static site. Runs free on GitHub
Actions + Pages. Full detail is in `README.md`; this file is the orientation
for picking the work up.

## How to run

```bash
pip install -r requirements.txt
python main.py --offline --fail-under 10   # fixtures, no network
python main.py                             # live fetch, all sources
python main.py --only vesper               # one adapter, diagnostic, writes nothing
python scripts/check_robots.py             # are we allowed to fetch these?
python scripts/check_secrets.py            # before making the repo public
python tests/test_robots.py
```

Windows: use `py -m pip install -r requirements.txt` and `py main.py`.

## Architecture in one line

`sources → adapters → normalize (dedupe + classify) → SQLite → publish`

Every adapter returns `list[Event]` (`models.py`); nothing downstream knows
how an event was obtained. Adding a source = one adapter + one line in
`SOURCES` (`pipeline.py`). Tabs/feeds are data-driven from `CHANNELS`
(`config.py`) — adding a channel adds a tab and an `.ics` automatically.

Adapter families, in order of preference:
1. **Official feed** — `ICSFeedAdapter` (UNL, Omaha Conservatory),
   `EventsCalendarRest` (KVNO, Orchestra Omaha), `LocalistAdapter` (UNO).
   Three sources share the Events Calendar adapter; check the platform
   before writing anything new.
2. **HTML parse** — Symphony, Vesper, Opera Omaha, Lincoln's Symphony,
   Juilliard. Symphony/Vesper/Opera Omaha selectors were rewritten against
   the live pages 2026-08-31 and verified (37 / 7 / 9 events); Lincoln's
   Symphony worked live as written. Juilliard still 403s (see below).
3. **LLM extraction** — `LLMPageExtractAdapter` (Omaha Chamber Music),
   `WorldConcertHallAdapter` (Mastodon RSS). Needs `ANTHROPIC_API_KEY`.
   Content-hash cached, so re-runs are free.

## State: what is and isn't verified

Everything so far was built and tested **offline against fixtures captured
by hand on 2026-08-30**. The published snapshot is real data, but the live
network path is largely unexercised. Current counts: In Omaha 44, Online 4,
In Lincoln 15, Broadcasts 3.

A live per-source smoke test on 2026-08-31 exercised every non-LLM source:
all pass except Juilliard (403, expected). The Symphony, Vesper, and Opera
Omaha parsers were rewritten against the live HTML that day. The Omaha
Conservatory feed was *empty* (their REST API confirms 0 upcoming events
published) — recheck when their fall season posts. Iterate per-source with
`--only <name>`; it publishes nothing, though it does upsert fetched events
into `events.db`.

## Open items

- **Juilliard returns 403** to our User-Agent. robots.txt *permits* the path,
  so this is a WAF, not policy. Do **not** spoof a browser User-Agent — see
  the note below. Fix by putting a real contact in `USER_AGENT` and emailing
  boxoffice@juilliard.edu for an allowance.
- **Placeholders**: resolved 2026-08-31. `USER_AGENT` (`adapters/base.py`)
  carries mailto:omahaadultpianoclub@gmail.com and `SITE_URL` (`pipeline.py`)
  is https://hartmajr.github.io/omahaclassicalcal (GitHub user `hartmajr`,
  repo `omahaclassicalcal`).
- **Creighton and Oberlin** are disallowed by robots.txt; both are
  commented out / absent with explanation. Only re-enable with a sanctioned
  feed or permission.
- **Unchecked sources** from Orchestra Omaha's Local Arts Links: Nebraska
  Wind Symphony, Intergeneration Orchestra of Omaha, River City Mixed
  Chorus, Papillion Area Concert Band, Soli Deo Gloria Cantorum, 1st
  Nebraska Volunteers Brass Band. Omaha Area Youth Orchestra's site is stale
  (2016). Omaha Symphonic Chorus lists only a gala right now.
- **Deploy**: repo → Settings → Pages → Source "GitHub Actions" → add the
  `ANTHROPIC_API_KEY` secret → run the workflow manually once.

## Conventions that matter

- **Respect robots.txt.** Deliberate exceptions go in
  `config.ROBOTS_EXCEPTIONS` with a written, dated justification and must
  meet the bar stated there. Never work around a refusal by disguising the
  client — that principle has shaped several decisions here and is the
  reason presenters would be comfortable with this project existing.
- **Fixtures are demo data.** `fixtures/README.md` records the provenance of
  every file, including what is captured versus reconstructed. Offline builds
  render a visible banner so they can't be mistaken for live output. Keep
  that honesty if you regenerate them.
- **Publishing is guarded.** `--fail-under N` aborts before writing if the
  calendar collapses; pruning only trusts sources that returned events, so a
  parser returning `[]` can't silently delete a season. Don't loosen these.
- **The classifier is a transparent heuristic** in `config.py` — category
  rules first, then composer/keyword signals, then hard and soft vetoes.
  Real data has repeatedly exposed gaps (Carmina Burana filed under a pops
  series; a jazz night reaching the classical feed because the adapter
  discarded its genre tags; contemporary-classical composers missing). When
  adding a source, check its verdicts against the published list.
- **Cross-platform dates**: use `dateformat.fmt`, not `%-d`/`%-I`, which
  break on Windows.
