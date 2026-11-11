# Project context

Aggregates classical-music events across Omaha (and Lincoln) into a
subscribable `.ics`, an RSS feed, and a static site. Runs free on GitHub
Actions + Pages. Full detail is in `docs/DEVELOPMENT.md`; this file is the orientation
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
   before writing anything new. The Lied Center reads its own calendar on
   UNL Events (`events.unl.edu/Lied_Center`, JSON for the link back to
   each Lied event page) since 2026-11-10; see Open items for why.
2. **HTML parse** — Symphony, Vesper, Opera Omaha, Lincoln's Symphony,
   Nebraska Chamber Players, Lincoln Friends of Chamber Music, Juilliard.
   Symphony/Vesper/Opera Omaha selectors were
   rewritten against the live pages 2026-08-31 and verified (37 / 7 / 9
   events); Lincoln's Symphony worked live as written. LFCM (2026-11-10,
   4 concerts) reads its homepage, which carries the whole current season;
   the season's own page moves every year (`/2026-2027-season/`), so it is
   never hardcoded. Nebraska Chamber Players was
   built and verified live 2026-09-22 (6 events; Squarespace event list,
   whose URL slugs are recycled between seasons and must never be trusted
   for dates). Nebraska Wind Symphony (2026-09-23, 7 events) reads its
   prose season page through WordPress's REST API, because the page's slug
   changes every season (`season50`, `season51`, …) and a hardcoded URL
   would silently serve last year. Gallery 1516 (2026-10-27, 5 events)
   reads only its "Bagels & Sometimes Bach" Sunday series off a page of
   hand-typed text blocks; dates carry no year, so the stated weekday picks
   it. Juilliard still 403s (see below).
3. **LLM extraction** — `LLMPageExtractAdapter` (Omaha Chamber Music),
   `WorldConcertHallAdapter` (Mastodon RSS; retired with the Broadcasts
   channel 2026-09-01). Needs `ANTHROPIC_API_KEY`. Content-hash cached,
   so re-runs are free.

## State: what is and isn't verified

**Deployed and live since 2026-09-01** at
https://hartmajr.github.io/omahaclassicalcal/ (repo
`hartmajr/omahaclassicalcal`, public; Pages source "GitHub Actions";
`ANTHROPIC_API_KEY` secret configured; weekly build Mondays 11:00 UTC).
The workflow commits `events.db`, the LLM caches, and `public/` back to
the repo each run. Each run also publishes `public/status.json` (per-source
counts or error strings) — check https://hartmajr.github.io/omahaclassicalcal/status.json
after a run instead of digging through Actions logs. Transient fetch
failures on GitHub's runners are real (2 of the first 4 runs lost a
source); `Adapter._get` retries them with backoff, never a 403. The Broadcasts channel + World Concert Hall source
were retired 2026-09-01 when the build went weekly (same-day broadcast
picks need a daily build); both are commented out for easy revival.

A live per-source smoke test on 2026-08-31 exercised every non-LLM source:
all pass except Juilliard (403, expected). The Symphony, Vesper, and Opera
Omaha parsers were rewritten against the live HTML that day. The Omaha
Conservatory feed was *empty* that day (0 upcoming events published); their
fall season posted by 2026-09-14 and the source now returns events
normally. Iterate per-source with `--only <name>`; it publishes nothing,
though it does upsert fetched events into `events.db`.

## Open items

- **Juilliard returns 403 — to our HTTP client, not our User-Agent.**
  robots.txt *permits* the path. Retested 2026-09-23: `curl` sending our
  exact User-Agent gets 200 while the adapter's `httpx`, same UA, same
  machine, gets 403 — so Cloudflare's bot management is fingerprinting the
  client library (TLS/headers), not reading the UA and not blocking GitHub's
  IPs. **Do not switch clients or mimic a fingerprint Cloudflare lets
  through**: that is disguising the client to get past a refusal, the same
  line as spoofing a browser UA, and it would break on Cloudflare's next
  update anyway. The fix is permission: a Cloudflare skip rule for our UA,
  or a feed. Request drafted 2026-09-23 for news@juilliard.edu (the press
  office handles calendar listings and can route the Cloudflare question
  to web/IT); page fetches are now spaced 10s apart, as that request
  promises. Until then the Online channel publishes 0 events (Juilliard is
  its only enabled source) — left visible by decision.
- **Lied Center: liedcenter.org is off limits; read from UNL Events since
  2026-11-10.** From 2026-10-26 every liedcenter.org URL, robots.txt
  included, answered our client with a Cloudflare 403 "Just a moment..."
  page (runners and residential alike); 2026-10-19 was the last good
  fetch. We asked (2026-11-02, text in `docs/REQUESTS.md`); the Lied's
  press office replied that after a hosting change they cannot allow
  particular crawlers, and pointed us to `/events-feed`, an RSS view that
  is challenged too and lists only the 10 latest-posted events with no
  performance dates. Ask, don't disguise: we stopped reading their site.
  The Lied's marketing office posts its own season to UNL's events
  calendar (`Lied_Center`, case-sensitive short name; lowercase
  `liedcenter` is an empty calendar), which serves us normally, so the
  adapter reads that. It carries real showtimes and halls but **no rental
  events** — which is how LFCM's concerts used to arrive (see below).
  Hall names match the old adapter's, so 47 of 53 event uids carried over
  (of the classical ones only CARMEN.maquia changed: UNL drops the accent
  in "Hispánico"). LFCM's "Johnny Carson Theater at the Lied" is published
  as "Carson Theater" for the same reason.
  A thank-you to the press office saying we'll use the UNL listing, and
  asking whether it is kept current all season, is drafted in
  `docs/REQUESTS.md`.
- **Placeholders**: resolved 2026-08-31. `USER_AGENT` (`adapters/base.py`)
  carries mailto:omahaadultpianoclub@gmail.com and `SITE_URL` (`pipeline.py`)
  is https://hartmajr.github.io/omahaclassicalcal (GitHub user `hartmajr`,
  repo `omahaclassicalcal`).
- **Creighton and Oberlin** are disallowed by robots.txt; both are
  commented out / absent with explanation. Only re-enable with a sanctioned
  feed or permission.
- **KVNO retired 2026-09-03**: kvno.org rewrote its robots.txt into a
  deliberate policy (feeds, pagination, and all query strings disallowed;
  AI bots blocked by name), which failed the preflight and the build. Not
  the generic-boilerplate case the exceptions bar covers. After dedupe it
  contributed one unique event. Commented out in `SOURCES`; its rows were
  purged from `events.db`. KVNO is Omaha's classical station — asking them
  for a sanctioned feed is the path to revival.
- **Unchecked sources** from Orchestra Omaha's Local Arts Links:
  Intergeneration Orchestra of Omaha, River City Mixed
  Chorus, Papillion Area Concert Band, Soli Deo Gloria Cantorum, 1st
  Nebraska Volunteers Brass Band. Omaha Area Youth Orchestra's site is stale
  (2016). Omaha Symphonic Chorus lists only a gala right now.
- **Lincoln Friends of Chamber Music became a source 2026-11-10.** Until
  then it was deliberately not one: its concerts arrived incidentally via
  the Lied's own listing. The Lied's UNL calendar carries no rentals, so
  that coverage ended exactly the way this note used to warn it might —
  silently. `adapters/lfcm.py` reads the lfcm.us homepage (WordPress page
  builder, no feed, stock robots.txt), one column per concert, classical
  by category. **When Season 63 posts (expect mid-2027)**, check the
  homepage still carries the whole season in the same layout; the
  per-concert pages move to a new `/YYYY-YYYY-season/` path each year.
- **LSO and Orchestra Omaha share a host, and it blocked us once
  (2026-10-05 to by 2026-10-12, lifted on its own).** Both sites sit on the
  same SiteGround account (same `Host-Header` hash, both in 35.206.0.0/16
  on Google Cloud; LSO's contact page even leaks a `*.sg-host.com` staging
  address), so they fail together. Through 2026-09 the pair only *timed
  out* together on GitHub's runners (2026-09-07, 2026-09-21) while
  answering sub-second from a residential connection. On 2026-10-05 the
  23:40 UTC run still got 11 + 2 events, but the 00:54 UTC run 75 minutes
  later got a non-JSON reply and 0 events, and from a residential
  connection every URL on both domains -- robots.txt and homepages
  included -- returned a static nginx 403 ("Access to this page is
  forbidden") to our identified client while a real browser from the same
  IP loaded them fine: the host refusing the client, the Juilliard
  situation. The prune guard held (LSO's `[]` untrusted, Orchestra Omaha
  errored), so their stored events stayed published. By the 2026-10-12
  scheduled run the block was gone (13 + 2 events), and that day every URL
  answered 200 to our UA from both curl and httpx, residential connection.
  Requests drafted 2026-10-05 in `docs/REQUESTS.md` (gitignored; names
  recipients; maintainer's machine only) were not needed -- keep them in
  case it recurs. If it does: a 403 to our client means ask, don't
  disguise; a timeout of the pair on the runners means try spacing the two
  fetches apart, not lengthening the timeout.
- **Possible NWS/UNO duplicate on 2026-12-06.** NWS's December concert is
  joint with the UNO University Band. If UNO's calendar lists it, the venues
  are compatible for dedupe, but the copies merge only if UNO's title
  contains or resembles "Nebraska Wind Symphony". Check the In Omaha list
  once UNO posts December.
- **Deploy**: done 2026-09-01 (see State above). Nothing left to configure;
  the daily schedule keeps it fresh.
- **In Lincoln looks thin** (9 of 19 collected events classified classical).
  LSO publishes no series labels, so pops/film nights are vetoed by title
  keywords only — audit the verdicts against LSO's season and tune
  `config.py` if real concerts are being dropped.

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
