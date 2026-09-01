"""Configuration knobs kept in one place so behaviour is easy to tune.

Classifier design (shaped by real captured data):
  1. Known-classical categories always win (Masterworks, Symphony Joslyn,
     KVNO's Classical).
  2. HARD non-classical categories always lose (Family, Community, Forte).
  3. SOFT non-classical categories (the Symphony's LIVE series) lose UNLESS
     a canonical composer name appears -- real data showed LIVE is a mixed
     bag: mostly film/pops nights, but also Carmina Burana. "Orff" rescues
     Carmina; "John Williams" is deliberately NOT a rescue signal, so film
     nights stay out.
  4. Firm keyword vetoes, then soft keyword vetoes (festival), then
     positive keywords (instruments/forms/composers), then source default.
"""

from __future__ import annotations

# Lower number = higher priority when collapsing duplicates.
SOURCE_PRIORITY: dict[str, int] = {
    "Omaha Symphony": 0,
    "UNO School of Music": 0,
    "Omaha Conservatory of Music": 0,
    "Juilliard": 0,
    "Oberlin Conservatory": 0,
    "Orchestra Omaha": 0,
    "Vesper Concerts": 0,
    "Opera Omaha": 0,
    "Omaha Chamber Music Society": 0,
    "UNL Glenn Korff School of Music": 0,
    "Lincoln's Symphony Orchestra": 0,
    "World Concert Hall": 0,        # curated classical-only broadcasts
    # Mixed presenter (Broadway/comedy/pop alongside classical): nonzero so
    # unmatched events default to NON-classical, and so a dedicated source's
    # copy of the same concert wins any dedupe tie.
    "Lied Center for Performing Arts": 2,
    "KVNO Arts Calendar": 5,        # aggregator -> lowest priority
}
DEFAULT_PRIORITY = 3

# The tabs / outputs, in display order.
CHANNELS: list[tuple[str, str, str]] = [
    ("local",     "In Omaha",   "calendar.ics"),
    ("online",    "Online",     "online.ics"),
    ("lincoln",   "In Lincoln", "lincoln.ics"),
    # Broadcasts retired 2026-09-01 with the World Concert Hall source --
    # same-day broadcast picks don't fit a weekly build (see pipeline.SOURCES).
    # ("broadcast", "Broadcasts", "broadcasts.ics"),
]

# Series/categories that are unambiguously classical, by source.
CLASSICAL_CATEGORIES = {
    "Omaha Symphony": {"Masterworks", "Symphony Joslyn", "Symphony Cathedral"},
    "KVNO Arts Calendar": {"Classical"},
}
# HARD: always non-classical, no rescue.
NON_CLASSICAL_CATEGORIES = {
    "Omaha Symphony": {"Family", "Community Concerts", "Forte"},
    # KVNO carries venue programming that is not music at all (Lauritzen
    # Gardens craft workshops, Samuel Bak Museum lectures). Category rules
    # run before keyword matching, so a stray musical word in a blurb can't
    # rescue a candlemaking class. Live data 2026-09-01 showed exactly that.
    "KVNO Arts Calendar": {"Workshop", "Crafts", "Education", "Lecture",
                           "Photography", "Art Gallery", "Animals"},
}
# SOFT: non-classical unless a composer name appears (see module docstring).
SOFT_NON_CLASSICAL_CATEGORIES = {
    "Omaha Symphony": {"LIVE with the Omaha Symphony"},
}

# Canonical classical composers -- a strong positive signal, and the only
# signal that can rescue a SOFT category. Film composers (John Williams,
# Elfman, Stothart) are deliberately absent. Diacritic variants included.
COMPOSER_KEYWORDS = {
    "bach", "beethoven", "mozart", "brahms", "mahler", "dvořák", "dvorak",
    "sibelius", "schubert", "stravinsky", "rachmaninoff", "haydn",
    "mendelssohn", "orff", "wagner", "verdi", "puccini", "tchaikovsky",
    "handel", "händel", "vivaldi", "chopin", "liszt", "schumann",
    "bartók", "bartok", "gershwin", "strauss", "saint-saëns", "saint-saens",
    "shostakovich", "prokofiev", "debussy", "ravel", "elgar", "grieg",
    "franck", "monteverdi", "purcell", "bruckner", "berlioz", "bizet",
    "buxtehude", "byrd", "gibbons", "kabalevsky", "gregson", "reich",
    # Composers whose surnames are everyday words carry their first names:
    # even with word-boundary matching (normalize._pattern), live data caught
    # "a glass of wine" (Philip Glass) and "participants" (Arvo Pärt)
    # rescuing non-concerts on the KVNO feed.
    "philip glass", "john adams", "pärt", "arvo part", "messiaen", "ligeti",
    "britten", "copland",
}

# Instrument/form keywords -- positive signal (cannot rescue SOFT categories).
CLASSICAL_KEYWORDS = {
    "classical", "symphony", "orchestra", "orchestral", "chamber", "recital",
    "quartet", "quintet", "trio", "sonata", "concerto", "philharmonic",
    "opera", "choral", "chorale", "choir", "baroque", "string", "cello",
    "violin", "viola", "piano", "oratorio", "cantata", "masterworks",
    "carillon", "organ", "woodwind", "brass ensemble", "early music",
    "historical performance", "baryton", "accordion", "lieder",
    "contemporary / new work", "new music", "sonatenabend",
} | COMPOSER_KEYWORDS

# Firm vetoes: always exclude, no rescue by incidental musical words.
NON_CLASSICAL_KEYWORDS = {
    # (word-boundary matched -- see normalize._pattern -- so "pop" no longer
    # needs a trailing space to dodge "popular")
    "tribute", "rock", "pop", "hip hop", "trap", "country", "dj", "jazz",
    "storytime", "scavenger", "birding", "mural", "exhibit", "gallery",
    "fireworks", "gala", "trivia", "comedy", "drag", "karaoke",
    "canceled:", "cancelled:", "postponed:", "convocation", "dedication",
    "star wars", "harry potter", "jurassic", "hollywood", "movie music",
    "film music", "video game", "deck the halls", "holiday pops",
    "volunteer", "letterpress", "art show", "open mic", "yoga",
    "photography", "book club", "reading series",
}
# Soft vetoes: exclude unless a classical keyword co-occurs
# (e.g. "Budapest Festival Orchestra" survives, "Family Festival" doesn't).
SOFT_NON_CLASSICAL_KEYWORDS = {
    "festival",
}


# Deliberate, reasoned exceptions to robots.txt.
#
# A blanket "obey robots.txt" is the right default, but it is a crawler
# protocol aimed at search indexing, and stock rules sometimes forbid things
# their author plainly meant to offer. Rather than either ignoring robots.txt
# silently or deferring to boilerplate against its own intent, exceptions are
# listed here with a written justification, so every one is visible, dated,
# and arguable.
#
# Bar for adding an entry:
#   - the resource is published expressly for machine consumption
#     (an .ics/RSS feed with a "subscribe" link), AND
#   - the blocking rule is evidently generic, not aimed at this resource, AND
#   - our access is low-frequency (about once a day) and identified.
# If any of those fails, do not add it -- ask the site instead.
ROBOTS_EXCEPTIONS: dict[str, str] = {
    "https://omahacm.org/events/?ical=1":
        "2026-08-30: omahacm.org publishes 'Disallow: /*?', a stock WordPress "
        "SEO rule that blocks all query strings to stop search engines "
        "indexing duplicate parameterised URLs. It incidentally catches this "
        ".ics export -- which the site itself offers via a subscribe button "
        "and which exists solely to be fetched automatically by calendar "
        "clients. One identified fetch per day is far below the load of a "
        "single human page view. Revisit if omahacm.org adds a rule naming "
        "this path or a bot directive.",
}
