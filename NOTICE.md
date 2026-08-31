# Notice on event data

The MIT licence above covers **this project's code only**.

It does not cover the event information this project collects. Concert
titles, dates, venues, programme notes and descriptions belong to the
presenting organisations — the Omaha Symphony, Opera Omaha, Vesper Concerts,
Orchestra Omaha, the Omaha Conservatory of Music, the Omaha Chamber Music
Society, KVNO, UNO, UNL, Lincoln's Symphony Orchestra, Juilliard and World
Concert Hall. They are reproduced here to point people at those concerts.

How this project tries to be a good guest:

- Every published event links back to its source page.
- Descriptions in the `.ics` feeds are capped at a short excerpt; the link
  carries the rest. The website shows only title, time, venue and source.
- Sources are fetched about once a day with an identified User-Agent.
- `robots.txt` is respected; the single deliberate exception is documented
  with its reasoning in `config.py` (`ROBOTS_EXCEPTIONS`).

The files in `fixtures/` are captured samples used to run the pipeline
offline for development and testing. They contain text from the sources
above. If you are one of those organisations and would like your material
removed or handled differently, please open an issue — it will be actioned.
