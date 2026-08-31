"""SQLite persistence.

Two jobs:
  1. Remember events across runs so the pipeline is idempotent -- re-running
     doesn't create duplicates, and updated details overwrite cleanly
     (keyed by Event.uid).
  2. Stamp first_seen on each event. That's what powers the RSS feed's
     "newly announced" items: an event is 'new' the first run it appears.

A single-file SQLite db is plenty here and commits nicely into a repo, so
the GitHub Action carries state between scheduled runs for free.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from models import Event

DB_PATH = Path(__file__).resolve().parent / "events.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    uid          TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    start        TEXT NOT NULL,
    end          TEXT,
    venue        TEXT,
    url          TEXT,
    description  TEXT,
    category     TEXT,
    source       TEXT NOT NULL,
    is_classical INTEGER,
    channel      TEXT DEFAULT 'local',
    tags         TEXT,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path = DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        # Lightweight migration so older DBs gain the channel column.
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(events)")}
        if "channel" not in cols:
            self.conn.execute("ALTER TABLE events ADD COLUMN channel TEXT DEFAULT 'local'")
            self.conn.commit()

    def upsert(self, events: list[Event]) -> list[str]:
        """Insert/update events. Returns the uids that are newly seen."""
        now = datetime.now(timezone.utc).isoformat()
        new_uids: list[str] = []
        cur = self.conn.cursor()
        for ev in events:
            existing = cur.execute(
                "SELECT uid FROM events WHERE uid = ?", (ev.uid,)
            ).fetchone()
            if existing is None:
                new_uids.append(ev.uid)
                cur.execute(
                    """INSERT INTO events (uid,title,start,end,venue,url,
                       description,category,source,is_classical,channel,tags,
                       first_seen,last_seen)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (ev.uid, ev.title, ev.start.isoformat(),
                     ev.end.isoformat() if ev.end else None, ev.venue, ev.url,
                     ev.description, ev.category, ev.source,
                     int(bool(ev.is_classical)), ev.channel,
                     ",".join(ev.tags), now, now),
                )
            else:
                cur.execute(
                    """UPDATE events SET title=?,start=?,end=?,venue=?,url=?,
                       description=?,category=?,source=?,is_classical=?,
                       channel=?,tags=?,last_seen=? WHERE uid=?""",
                    (ev.title, ev.start.isoformat(),
                     ev.end.isoformat() if ev.end else None, ev.venue, ev.url,
                     ev.description, ev.category, ev.source,
                     int(bool(ev.is_classical)), ev.channel,
                     ",".join(ev.tags), now, ev.uid),
                )
        self.conn.commit()
        return new_uids

    def upcoming(self, classical_only: bool = True,
                 channel: str | None = None) -> list[Event]:
        q = "SELECT * FROM events WHERE start >= ?"
        if classical_only:
            q += " AND is_classical = 1"
        if channel is not None:
            q += " AND channel = ?"
        q += " ORDER BY start ASC"
        # "Today" must be Omaha's today, not the server's. A UTC-clocked
        # server crosses midnight at 6-7pm Central, which would make tonight's
        # concerts vanish from the published calendar every evening.
        try:
            from zoneinfo import ZoneInfo
            now_local = datetime.now(ZoneInfo("America/Chicago"))
        except Exception:  # pragma: no cover
            now_local = datetime.now()
        today = now_local.replace(hour=0, minute=0, second=0,
                                  microsecond=0, tzinfo=None).isoformat()
        params: tuple = (today,) if channel is None else (today, channel)
        rows = self.conn.execute(q, params).fetchall()
        return [_row_to_event(r) for r in rows]

    def prune_missing(self, sources_ok: list[str], run_started: str,
                      exclude_channels: tuple[str, ...] = ("broadcast",)) -> int:
        """Drop FUTURE events that a source stopped listing (= cancelled).

        Only prunes events from sources that fetched successfully this run
        (a network hiccup must never mass-delete a source's events), and
        never prunes excluded channels: WCH's Mastodon feed shows only the
        ~20 newest posts, so a broadcast falling out of the feed is normal,
        not a cancellation. Past events are always kept as history.
        """
        if not sources_ok:
            return 0
        src_marks = ",".join("?" * len(sources_ok))
        ch_marks = ",".join("?" * len(exclude_channels))
        now = datetime.now().isoformat()
        cur = self.conn.execute(
            f"""DELETE FROM events
                WHERE source IN ({src_marks})
                  AND channel NOT IN ({ch_marks})
                  AND start >= ?
                  AND last_seen < ?""",
            (*sources_ok, *exclude_channels, now, run_started),
        )
        self.conn.commit()
        return cur.rowcount

    def by_uids(self, uids: list[str]) -> list[Event]:
        if not uids:
            return []
        marks = ",".join("?" * len(uids))
        rows = self.conn.execute(
            f"SELECT * FROM events WHERE uid IN ({marks}) ORDER BY first_seen DESC",
            uids,
        ).fetchall()
        return [_row_to_event(r) for r in rows]


def _row_to_event(r: sqlite3.Row) -> Event:
    ev = Event(
        title=r["title"],
        start=datetime.fromisoformat(r["start"]),
        end=datetime.fromisoformat(r["end"]) if r["end"] else None,
        venue=r["venue"], url=r["url"], description=r["description"],
        category=r["category"], source=r["source"],
    )
    ev.is_classical = bool(r["is_classical"])
    ev.channel = r["channel"] if "channel" in r.keys() and r["channel"] else "local"
    ev.tags = r["tags"].split(",") if r["tags"] else []
    if "first_seen" in r.keys() and r["first_seen"]:
        ev.first_seen = datetime.fromisoformat(r["first_seen"])
    return ev
