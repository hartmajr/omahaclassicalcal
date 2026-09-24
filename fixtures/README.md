# Fixture provenance — snapshot captured August 30, 2026

Every fixture here was rebuilt from **live data captured on August 30, 2026**,
replacing the July 10 snapshot. A live run (`python main.py`) ignores this
folder and re-fetches from source.

**omaha_symphony.json** — The real 2026/27 season (36 concerts) from
omahasymphony.org/season/2026-27-season. Since the July capture the Symphony
ADDED a new series, **Symphony Cathedral** (Handel's Water Music, Oct 10–11;
A Festival of Christmas Brass, Dec 17–20, both at Saint Cecilia Cathedral),
added "Sounds of the City" (Forte, Sep 18), and rewrote several blurbs.
CAVEAT: venues are inferred from series (Masterworks/LIVE/Family → Holland;
Symphony Joslyn → Joslyn; Symphony Cathedral → Saint Cecilia Cathedral); the
season page does not state venue per concert, and gives no curtain times.

**uno_localist.json** — The 6 real upcoming School of Music events (fall
semester now under way; this source was legitimately empty in July): the
Valencia Baryton Project pair (Sep 10), Joyce Yang masterclass (Sep 26), UNO
Choirs (Oct 13), Christine Beard flute recital (Oct 18), Keyboard Area
Project (Oct 26). Real titles, times, venues, URLs.

**kvno.json** — All 12 events from the live kvno.org/artscalendar list view
(Aug 30 – Sep 5 window), reshaped into the Events Calendar REST format.
Seven are daily instances of one recurring letterpress exhibit — a good
reminder that recurring exhibits dominate this feed. Categories are not in
the rendered list, so `categories` is empty. KVNO's `?ical=1` export remains
robots-disallowed even though the HTML list is not.

**omaha_conservatory.ics** — Deliberately EMPTY (a valid VCALENDAR with no
events). omahacm.org states "Currently no upcoming events"; the six July
events have all passed. The live feed goes further and answers HTTP 200 with
a completely empty body when nothing is listed, which the adapter treats as
zero events.

**world_concert_hall.json** — The 3 real broadcasts listed for Aug 30
(Schleswig Holstein Festival with Paavo Järvi; Benjamin Appl singing
Schubert's Die schöne Müllerin; Ingolstadt Organ Summer playing Buxtehude),
with GMT times as published. Obtained via search snippets of
worldconcerthall.com (the site and its Mastodon RSS were not directly
fetchable) and structured by Claude — the pipeline's LLM-extraction step
performed at capture time. URLs point to the WCH schedule page.

**oberlin_localist.json — ABSENT, intentionally.** calendar.oberlin.edu
remains robots-blocked, so no capture is possible. The adapter errors
gracefully and the run continues.

**vesper_concerts.json** — Vesper Concerts Season 38 (7 concerts) captured
from vesperconcerts.org on Aug 30, 2026: Emanuel Ax (Sep 8), PROJECT Trio
outdoor (Oct 4), Adam Hu (Nov 15), Cantus (Dec 1), Sterling Elliott (Jan 26),
Christine Beard (Feb 14), Texas Guitar Quartet (Apr 23). Real titles, dates,
times and URLs. All free; venue is Presbyterian Church of the Cross except
the outdoor concert, whose location the page doesn't state.

**orchestra_omaha.json** — All 3 upcoming Orchestra Omaha concerts from
orchestraomaha.org/events/ (Orchestral Idylls Sep 12, Scary Stories Oct 30,
Dvorak Symphony No. 6 Feb 6 2027), reshaped into Events Calendar REST format.
Real titles, times, venue (Simon Concert Hall), URLs and programs.

**opera_omaha.json** — Opera Omaha's full 26/27 season captured from
operaomaha.org/26-27-season/ on Aug 30, 2026: Will Liverman in Concert
(Sep 27), La bohème (Nov 13 & 15), The Pigeon Keeper (Jan 28/29/30 2027),
Ariadne auf Naxos (Mar 19 & 21), Alessandro (Apr 30). Real titles, dates,
times, venues, composers and URLs as published. Stored as productions with
a date list; the adapter expands them to one event per performance. Opera
Outdoors (Aug 29) is omitted as past.

**unl_music.ics** — 7 real events from UNL's official Music calendar ICS
feed (events.unl.edu/music/upcoming/?format=ics), captured Aug 30, 2026:
Nicholas May saxophone recital (Sep 1), the 2026 American Liszt Society
Festival (Sep 28-30, one entry per day as the feed publishes it), Symphony
Orchestra and University Orchestra with University Singers (both Sep 28),
and the Westbrook Music Building Dedication (Oct 1, filtered out as a
ceremony). Titles, times, venues, URLs and categories as published.

**lincoln_symphony.json** — Lincoln's Symphony Orchestra 26/27 season (10
cards, 12 performances) from lincolnsymphony.com/season-at-a-glance/,
captured Aug 30, 2026. Includes the two multi-performance cases the adapter
must handle: Organ Celebration on two dates, and Deck the Halls twice on one
day. Real titles, dates, times, venues and URLs. The page carries no series
labels, so pops/film nights are identified by title keywords only.

**omaha_chamber_music.json** — Extracted from omahachambermusic.org on
Aug 30, 2026. The Heritage 2027 page announces three Sundays (Jan 31,
Mar 14, May 16 2027, 3:00 p.m., Omaha Conservatory, Thomas Kluge artistic
director) but states "Check back soon for more information on programs and
musicians" — so titles are placeholders and descriptions note the program is
TBA. Dates, times, venue and artistic director are as published. The 2026
Summer Concert Series has finished (last concert June 28, 2026) and so
contributes nothing. Structured by Claude at capture time; live runs do the
same extraction via the API.

**juilliard.json** — 40 real events from calendar pages 1 and 2 (Sep 2 -
Oct 7, 2026), with verbatim venues and performance-type tags. Seven carry
the "Live Streaming" tag. Still a partial season, and deliberately marked so:
pages 3+ could not be captured because the capture tooling collapsed
`?page=3` onto `?page=1`. The live adapter has no such limit
(MAX_PAGES=20, ~a full season) and will pick up the October streams. Verify
with `python main.py --only juilliard`.

**lied_center.json** — All 55 event cards from liedcenter.org/events-page,
captured live September 22, 2026, each enriched with the hall and showtimes
read from its own /event/ page (54 carry a venue; 52 carry showtimes, 96 in
total). Titles, day-precision listing dates, teaser prose, event-type labels
and URLs are exactly as parsed. Includes the six Lincoln's Symphony
co-presentations so the adapter's skip rule is exercised, one card with no
venue published so the building-name fallback is exercised, and three
E.N. Thompson Forum lectures with no showtimes so the all-day fallback is
exercised. Nine events are matinee/evening double-headers on a single day
(Mamma Mia, Hamilton, Clue and others), which is what the time-labelled
titles are for. This replaces the September 1 capture of 49 cards, which
predated detail-page enrichment and so carried neither venue nor showtimes;
the past-dated "Metro Jazz Quintet" card noted there is no longer listed.

**nebraska_chamber_players.json** — All 6 upcoming performances from
nebraskachamberplayers.org/calendar, captured live September 22, 2026
(titles, dates, showtimes, venue line, repertoire prose and URLs exactly as
parsed from the Squarespace event list). Their 30th-anniversary season is
three programs, each played twice — Friday 7:30pm and Sunday 3:00pm — so
titles repeat across dates by design. The URLs are the site's own and are
genuinely misleading: Squarespace reuses event pages between seasons, so
November 2026's concert still lives at a 2025/10/31 Halloween slug. The
September 18 & 20, 2026 pair had already been performed at capture time and
is not included; the page lists past events in a separate section the
adapter does not read.

**nebraska_wind_symphony.json** — The season50 page ("50th Anniversary
Season – 2026-2027") exactly as nebraskawindsymphony.com's WordPress REST API
returned it on September 23, 2026: slug, link, last-modified stamp
(2026-09-14) and the rendered content HTML, unaltered. It is what
`fetch_raw()` returns, so offline runs exercise the full parser: seven dates,
one with no year ("Sunday, December 6") resolved by its stated weekday, three
time spellings, a date and time split across two <strong> tags, a "Summer
Concerts" heading over the two Swingtones dates, and an intro sentence
("See the flyer for this season's concerts.") that must not become a title.
