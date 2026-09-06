# Omaha Classical Calendar

A free, subscribable calendar of classical-music events in Omaha and
Lincoln, Nebraska, gathered automatically from the presenters' own
listings and rebuilt every week.

**Website:** https://hartmajr.github.io/omahaclassicalcal/

## Subscribe

Add any of these URLs to Google Calendar, Apple Calendar, Outlook, or any
app that accepts an iCal subscription. They update themselves.

| Calendar | URL |
|---|---|
| In Omaha | `https://hartmajr.github.io/omahaclassicalcal/calendar.ics` |
| In Lincoln | `https://hartmajr.github.io/omahaclassicalcal/lincoln.ics` |
| Online (streamed) | `https://hartmajr.github.io/omahaclassicalcal/online.ics` |
| Newly announced (RSS) | `https://hartmajr.github.io/omahaclassicalcal/feed.xml` |

Every event links back to the presenter's page for tickets and details.

## About

The calendar is assembled by a small Python pipeline that reads each
presenter's published calendar, feed, or season page, keeps the classical
concerts, removes duplicates, and publishes the result to GitHub Pages.
It respects each site's `robots.txt`, identifies itself on every request,
and fetches once a week. Event facts belong to the presenters; see
[NOTICE.md](NOTICE.md).

Presenters: if you'd like a listing corrected or removed, or can offer a
calendar feed, email omahaadultpianoclub@gmail.com.

Developer documentation lives in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## License

Code is MIT licensed (see [LICENSE](LICENSE)). The license does not extend
to event data, which remains the presenters'.
