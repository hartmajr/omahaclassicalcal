# Omaha Classical Calendar

Aggregates classical-music events from across the Omaha area into a single
subscribable calendar (`.ics`), an RSS feed of newly announced concerts, and
a simple website. Built to run for free on a daily schedule via GitHub
Actions + GitHub Pages — no server.

## Quick start

```bash
pip install -r requirements.txt        # required first -- see note below
python main.py --offline               # build from captured sample data
python main.py                         # fetch live from every source
python main.py --only juilliard        # live, one adapter only (debugging)
```

**Windows (PowerShell):** use `py` and install into that interpreter:

```powershell
py -m pip install -r requirements.txt
py main.py --offline
```

A bare `pip install` can land in a different Python than the one `py` runs,
which shows up as `ModuleNotFoundError: No module named 'icalendar'`.
Running pip through `py -m pip` guarantees they match. Date formatting is
cross-platform (see `dateformat.py`); no other Windows-specific setup is
needed.

Outputs land in `public/`: `calendar.ics`, `online.ics`, `broadcasts.ics`,
`feed.xml`, and `index.html` (a tabbed site).

The `--offline` flag runs the entire pipeline against the fixtures in
`fixtures/` so you can develop and see output without hitting the live
sites. **Fixtures are demo data** — a mix of captured and constructed
entries whose links may be dead; see `fixtures/README.md` for exact
per-file provenance. Offline builds render a visible demo banner on the
site so they can't be mistaken for live output.

## How it works

```
sources → adapters → normalize (dedupe + classify) → store → publish
```

Every adapter, regardless of how it gets its data, returns a list of the same
`Event` object (`models.py`). Everything downstream is source-agnostic, so
adding a source is just writing one more adapter and adding a line to
`SOURCES` in `pipeline.py`.

- **`models.py`** — the shared `Event` shape and its stable `uid` (used both
  for cross-source dedupe and as the iCalendar UID).
- **`adapters/`** — one module per source style:
  - `localist.py` — UNO School of Music (Localist JSON API).
  - `events_calendar.py` — a reusable REST adapter (KVNO) **and** a generic
    `.ics` feed adapter (Omaha Conservatory). The `.ics` adapter works for any
    iCalendar feed, so it's also how you'd add Creighton once you have its feed
    URL.
  - `symphony.py` — Omaha Symphony, parsed from the server-rendered season page.
- **`normalize.py`** — dedupe across sources (keeping the highest-priority
  source's copy) and classify each event as classical vs other-arts.
- **`store.py`** — SQLite persistence; stamps `first_seen` so the RSS feed can
  show only newly announced concerts.
- **`publish/`** — `ics.py`, `rss.py`, `site.py`.
- **`pipeline.py` / `main.py`** — orchestration and CLI.

## Sources

| Source | How | Channel | Status |
|---|---|---|---|
| UNO School of Music | Localist JSON API | In Omaha | live adapter |
| KVNO Arts Calendar | The Events Calendar REST API | In Omaha | live adapter |
| Omaha Conservatory | The Events Calendar `.ics` export | In Omaha | live adapter (documented robots exception) |
| Omaha Symphony | season-page HTML parse | In Omaha | live adapter (verified 2026-08-31) |
| Orchestra Omaha | The Events Calendar REST API | In Omaha | live adapter |
| Vesper Concerts | season-page HTML parse | In Omaha | live adapter (verified 2026-08-31) |
| Opera Omaha | season-page HTML parse | In Omaha | live adapter (verified 2026-08-31) |
| UNL Glenn Korff School of Music | official UNL Events `?format=ics` feed | In Lincoln | live adapter |
| Lincoln's Symphony Orchestra | season-page HTML parse | In Lincoln | live adapter (verified 2026-08-31) |
| Oberlin Conservatory | Localist JSON API (webcast types) | Online | live adapter |
| Juilliard | Drupal calendar HTML parse (paginated) | Online | live adapter (verify selectors) |
| World Concert Hall | Mastodon RSS + LLM extraction | Broadcasts | live adapter (needs `ANTHROPIC_API_KEY`) |
| Creighton (Music) | their `.ics`/RSS feed | In Omaha | **TODO** — robots.txt blocks the HTML listing; use the sanctioned feed once confirmed |
| Omaha Chamber Music Society | LLM page extraction (`llm_extract`) | In Omaha | live adapter (needs `ANTHROPIC_API_KEY`) |

### Source triage (from Orchestra Omaha's Local Arts Links directory)

| Org | Platform | Verdict |
|---|---|---|
| Opera Omaha | WordPress, custom `production` type | **added** — 9 performances |
| Omaha Chamber Music Society | Squarespace, prose pages | **added** via LLM extraction — 3 dates |
| Omaha Symphonic Chorus | Wix + Wix Events | wait — only a fundraising gala listed now; concerts page still says 2023-24 |
| Omaha Area Youth Orchestra | static, **stale** | skip — oayo.org content dates to 2016; find their current home first |
| Nebraska Wind Symphony, Intergeneration Orchestra, Papillion Area Concert Band, River City Mixed Chorus, Soli Deo Gloria Cantorum, 1st Nebraska Volunteers Brass Band | unchecked | next round |
| Omaha Performing Arts / Ticket Omaha | large presenter | high value but mostly non-classical; needs hard filtering |
| Creighton Fine & Performing Arts | Drupal | blocked by robots.txt (see above) |
| Playhouse, Rose Theater, Sweet Adelines, Pathfinder Chorus, SING Omaha, Nebraska Arts Council | — | out of scope (drama / barbershop / funder) |

## Channels (tabs + calendars)

Every event carries a `channel`, set by its adapter. Channels are defined in
one place (`CHANNELS` in `config.py`) and drive everything: each becomes a
website tab and its own subscribable `.ics`. Adding a fourth channel is a
one-line config change plus tagging a source with it.

- **In Omaha** (`local`) — in-person concerts, `calendar.ics`.
- **Online** (`online`) — streamed institutional performances (Juilliard,
  Oberlin), `online.ics`. Localist modality comes from its `experience`
  field; Juilliard from "Live Streaming" type / Livestream venues.
- **In Lincoln** (`lincoln`) — concerts in Lincoln, about an hour down I-80,
  `lincoln.ics`. A separate tab so the Omaha calendar isn't diluted by
  events an hour away, while still being one subscribe click for those who
  make the drive.
- **Broadcasts** (`broadcast`) — curated global live broadcasts from World
  Concert Hall, `broadcasts.ics`.

### Juilliard pagination

The calendar's "Load More" button is JavaScript, but `?page=N` **does** work
server-side, so the adapter paginates with plain HTTP — no headless browser
needed. Each page covers roughly 2-3 weeks; `MAX_PAGES = 20` therefore
reaches roughly a full season.

**The committed fixture only covers pages 1-2 (Sep 2 - Oct 7).** That is a
limit of how the snapshot was captured, not of the adapter: the live run
paginates further and will pick up the October streams and beyond. To check
that quickly without fetching every other source:

```bash
python main.py --only juilliard        # live, just this adapter
```

The loop also **stops as soon as a page returns content it has already
seen**. That guard matters: if Juilliard ever changes the parameter, the
adapter stops after two fetches instead of re-parsing identical HTML a dozen
times and hammering their server. `page_url_template` is available as an
override if the endpoint ever moves.

There is no separate livestream feed — `juilliard.edu/live` is an
information page whose own FAQ confirms streamed performances are listed in
this same calendar.

### robots.txt: query strings matter

`scripts/check_robots.py` tests the URLs the adapters **actually request**,
query strings included. That distinction is not academic: omahacm.org
publishes `Disallow: /*?`, a blanket ban on query strings, which forbids both
their `?ical=1` export and any `?page=` pagination — while permitting the
same endpoints as bare paths. Checking bare paths alone would have reported
"ALLOWED" for a fetch that is in fact disallowed.

`EventsCalendarRest(no_query=True)` exists for sites where that matters: it
fetches the bare endpoint with no query string, and warns loudly if the
source reports more events than one page returned, so a robots-safe fetch
can never silently truncate.

The Conservatory itself is handled differently, via a **documented
exception** (`ROBOTS_EXCEPTIONS` in `config.py`). Their rule is stock
WordPress SEO boilerplate aimed at stopping search engines indexing
parameterised duplicate URLs; it incidentally catches an `.ics` export that
the site publishes with a subscribe button, whose entire purpose is
automated fetching by calendar software. Deferring to a generic rule against
its author's evident intent is literalism, not care. Every exception is
listed with a dated justification and a stated bar for adding more — the
resource must be published for machine consumption, the rule must be
evidently generic, and access must be low-frequency and identified. The
preflight reports these separately rather than passing them silently.

**Known issue: juilliard.edu returns 403 to this bot.** A live run currently
fails with `403 Forbidden` on the calendar URL. The site refuses our
identified User-Agent, most likely bot protection rather than a stated
policy — but a refusal is a refusal. The supported responses, in order:

**robots.txt permits this path** — verified with `scripts/check_robots.py`.
So the 403 is bot protection (a WAF filtering unknown User-Agents), not a
stated policy against crawling. That makes the situation ambiguous rather
than a clear refusal, and the honest response is to ask rather than guess:

1. Email Juilliard's box office (boxoffice@juilliard.edu) or web team,
   describe the project — a free, non-commercial community calendar that
   links every event back to them — and ask whether they can allow the
   User-Agent or offer a feed. They livestream ~700 performances a year
   specifically to reach audiences outside New York; this is aligned with
   that, not against it.
2. Put a real contact address in `USER_AGENT` (`adapters/base.py`) first. A
   WAF operator deciding whether to allow a bot wants to know who to
   contact; an anonymous bot is easy to keep blocking.
3. Until it is resolved, leave the source enabled or comment it out — either
   is safe. The run degrades cleanly: the error is caught per-source, the
   other ten sources publish normally, and the prune guard means Juilliard's
   stored events are not deleted.

**What this project will not do:** disguise the User-Agent as a browser to
get past the 403. Evading an explicit refusal is the same behaviour we
declined for Creighton and Oberlin, and doing it here would make the whole
"be a good citizen" posture meaningless. `ANTHROPIC_...`-style spoofing is
not a supported configuration. Adding a real contact address to the
User-Agent in `adapters/base.py` is encouraged — that helps a site decide to
allow you.

### Classifier note: sources without series labels

The Omaha Symphony tags concerts Masterworks / LIVE / Family, which makes
filtering reliable. Lincoln's Symphony publishes no series labels on its
season page, so pops and film nights can only be spotted from titles — hence
the film/pops keyword vetoes in `config.py` (`star wars`, `jurassic`,
`deck the halls`, ...). This works for the obvious cases but is inherently
incomplete: LSO's family concert "Lou, the Baby Dinosaur" currently
classifies as classical because nothing in its title says otherwise. Add
titles to the veto list, or fetch each concert's own page, if you want that
tightened.

### LLM page extraction (`adapters/llm_extract.py`)

`LLMPageExtractAdapter` is the reusable fallback for sources with no feed
and no regular markup: it fetches pages, strips them to readable text, and
asks a model for structured events. Point it at a list of URLs and it
works — no per-source parser. Three details make it cheap and safe:
boilerplate stripping (Squarespace repeats its whole nav several times per
page, which would otherwise dominate the prompt), **content-hash** caching
(the URL is constant and the content changes, so re-runs cost nothing until
a page is actually edited), and a prompt that requires an empty list rather
than inventing events — the usual failure mode of LLM extraction.

It handles the case where a series announces dates before programs: Omaha
Chamber Music's Heritage 2027 currently lists three Sundays with "Check back
soon for more information on programs and musicians", so the events publish
with placeholder titles and a TBA note rather than being dropped.

### World Concert Hall / LLM extraction

worldconcerthall.com publishes no feed and blocks scraping, but WCH posts
every pick to Mastodon, whose accounts expose a built-in RSS feed
(`https://mastodon.world/@WConcertHall.rss`). Those posts are free text, so
the adapter pairs the RSS with an LLM extraction step (Anthropic API) that
turns each post into structured event fields. Set `ANTHROPIC_API_KEY` to run
it live (in CI, add it as a repo secret — the workflow already wires it in);
`--offline` uses the fixture and makes no API call. This same RSS-plus-LLM
pattern is what the Omaha Chamber Music Society source will use.

## Classification

KVNO is a broad *arts* calendar, so most of what it carries is gallery
openings, theatre, and pop concerts. `normalize.py` filters to the classical
subset using (1) known source categories — e.g. the Symphony's Masterworks and
Symphony Joslyn series — and (2) keyword signals, with a firm non-classical
denylist. It's a transparent heuristic and deliberately the seam where a
smarter classifier (or an LLM call) slots in. Tune the lists in `config.py`.

## Notes / caveats

- **HTML selectors**: the Symphony, Vesper, and Opera Omaha parsers were
  rewritten against the live pages on 2026-08-31 and verified (37 / 7 / 9
  events respectively); each adapter documents the exact markup shape it
  relies on. If a site redesigns, the parser returns `[]` and the prune
  guard keeps the stored events safe.
- **Be a good citizen**: the HTTP client sends an identifying User-Agent, the
  schedule polls once a day, and every published event links back to its
  source. Respect each site's robots.txt (notably Creighton's) and prefer
  official feeds over scraping.


## Visibility: private repo, public feeds

**A calendar subscription URL must be publicly fetchable.** Google Calendar
and Apple Calendar poll `.ics` URLs from their own servers and cannot log in
to anything. So a genuinely access-controlled page would break every
subscription — the feature the whole project exists to provide.

What GitHub offers (verified Aug 2026):

| Setup | Repo | Site + `.ics` | Plan |
|---|---|---|---|
| Public repo, public site | visible | public | Free |
| **Private repo, public site** | **hidden** | **public** | **Pro / Team** |
| Private repo, private site | hidden | needs login — **breaks .ics** | Enterprise Cloud |

Repository visibility and site visibility are separate settings. The middle
row is almost certainly what you want: your code, `events.db` and caches stay
private, while the built site and feeds are reachable.

### Unlisted mode

If you want the feeds working but the page kept out of search results, set
`UNLISTED=1` when building:

```yaml
      - name: Build calendar (live fetch)
        run: python main.py --fail-under 10
        env:
          UNLISTED: "1"
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

That adds `<meta name="robots" content="noindex, nofollow">` to the page and
writes a `Disallow: /` robots.txt, while the `.ics` files remain fetchable.
Anyone with the URL can still open it — this is unlisted, not private. Do not
put anything sensitive in `public/`; everything there is world-readable.


## Keeping the API key out of a public repo

The key is never in your files. `${{ secrets.ANTHROPIC_API_KEY }}` is stored
encrypted by GitHub and injected as an environment variable into the runner
at execution time; the code reads it with `os.environ.get(...)`. Cloning a
public repo reveals only the secret's *name*, and GitHub masks the value in
logs if it ever surfaces.

The workflow triggers matter too. The usual way public repos leak secrets is
a workflow that runs on pull requests, where anyone can propose code that
prints the key. This workflow runs only on `schedule` and
`workflow_dispatch`, so untrusted code never executes with the key in scope.
Do not add `pull_request_target` to it.

The realistic risk is human — pasting the key into a file while debugging
locally. Before making the repo public:

```bash
python scripts/check_secrets.py
```

It scans for Anthropic/OpenAI/GitHub/AWS key shapes and assigned-secret
patterns, and warns about a stray `.env` (which is gitignored). Note it scans
the *working tree only*: git history is separate, so also check
`git log -p | grep -i 'sk-ant'`. **If a key was ever committed, rotate it** —
deleting the line does not remove it from history, and public repos are
scraped for keys within minutes.

For local runs, set the variable in your shell rather than in a file:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # PowerShell, this session only
py main.py
```


## Before making the repository public

A checklist, in rough order of consequence:

1. **Credentials.** `python scripts/check_secrets.py` for the working tree,
   then `git log -p | grep -i 'sk-ant'` for history. If a key was ever
   committed, rotate it — public repos are scraped within minutes.
2. **Replace the placeholders.** `USER_AGENT` in `adapters/base.py` and
   `SITE_URL` in `pipeline.py` both say `example.org`. Put your real site
   URL and a contact address in the User-Agent: it is how a presenter
   decides whether to allow your bot rather than block it, and it is the
   difference between an anonymous scraper and an identifiable neighbour.
   Note this publishes an email address — use one you are happy to expose,
   or a project alias.
3. **Third-party content.** The repo contains event text from the presenters
   (~50 KB across `fixtures/`, plus descriptions in `events.db` and the
   `.ics` feeds). Event *facts* — title, date, venue — are not copyrightable
   and are the substance of what this publishes. Promotional prose is the
   presenter's. Mitigations already in place: `.ics` descriptions are capped
   at a 240-character excerpt with a link to the source, the website shows no
   descriptions at all, and `NOTICE.md` states whose material it is and
   offers removal on request. If you would rather carry no third-party prose,
   set `MAX_DESC = 0` in `publish/ics.py`.
4. **Licensing.** `LICENSE` (MIT) covers the code only; `NOTICE.md` makes
   clear it does not extend to the event data. Without a licence file a
   public repo is "all rights reserved", which discourages the contributions
   that would help this project grow.
5. **Nothing else is sensitive.** `events.db` and the `*_cache.json` files
   hold public concert listings only — no personal data, no credentials, no
   attendee information.
