"""Supabase PostgreSQL layer. Schema is created on import; upserts dedupe by event hash."""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Iterable, Iterator

import psycopg2
from psycopg2.extras import execute_values
from psycopg2.pool import SimpleConnectionPool

from config import SUPABASE_URL
from models import Event

log = logging.getLogger("nyc_events")

# Connection pool for Supabase
_pool: SimpleConnectionPool | None = None


def _get_pool() -> SimpleConnectionPool:
    """Lazy-init connection pool."""
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(1, 10, SUPABASE_URL)
    return _pool


@contextmanager
def connect() -> Iterator[psycopg2.extensions.connection]:
    """Get connection from pool."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def init_db() -> None:
    """Create schema if it doesn't exist."""
    schema = """
    CREATE TABLE IF NOT EXISTS events (
        id              SERIAL PRIMARY KEY,
        hash            TEXT NOT NULL UNIQUE,
        source          TEXT NOT NULL,
        source_id       TEXT,
        title           TEXT NOT NULL,
        description     TEXT,
        url             TEXT,
        image_url       TEXT,
        start_utc       TEXT,
        end_utc         TEXT,
        start_local     TEXT,
        venue_name      TEXT,
        address         TEXT,
        borough         TEXT,
        lat             REAL,
        lon             REAL,
        is_free         INTEGER,
        price_min       REAL,
        price_max       REAL,
        currency        TEXT,
        categories      TEXT,
        audiences       TEXT,
        age_min         INTEGER,
        age_max         INTEGER,
        raw             TEXT,
        first_seen_utc  TIMESTAMP DEFAULT NOW(),
        last_seen_utc   TIMESTAMP DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_events_start_utc ON events(start_utc);
    CREATE INDEX IF NOT EXISTS idx_events_borough   ON events(borough);
    CREATE INDEX IF NOT EXISTS idx_events_source    ON events(source);
    CREATE INDEX IF NOT EXISTS idx_events_is_free   ON events(is_free);

    -- Allow Supabase REST API (anon/authenticated roles) to read events
    GRANT SELECT ON events TO anon;
    GRANT SELECT ON events TO authenticated;
    ALTER TABLE events DISABLE ROW LEVEL SECURITY;

    CREATE TABLE IF NOT EXISTS source_runs (
        id            SERIAL PRIMARY KEY,
        source        TEXT NOT NULL,
        started_utc   TIMESTAMP DEFAULT NOW(),
        finished_utc  TIMESTAMP,
        inserted      INTEGER DEFAULT 0,
        updated       INTEGER DEFAULT 0,
        errors        INTEGER DEFAULT 0,
        note          TEXT
    );
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
    log.info("Database schema initialized")


def upsert_events(events: Iterable[Event]) -> tuple[int, int]:
    """Upsert events, deduping by hash. Returns (inserted, updated)."""
    inserted = updated = 0
    events_list = list(events)
    if not events_list:
        return 0, 0

    with connect() as conn:
        with conn.cursor() as cur:
            for ev in events_list:
                row = ev.to_row()
                # Check if exists
                cur.execute("SELECT id FROM events WHERE hash = %s", (row["hash"],))
                existing = cur.fetchone()

                if existing:
                    # UPDATE
                    update_sql = """
                    UPDATE events SET
                        title=%s, description=%s, url=%s,
                        image_url=%s, start_utc=%s, end_utc=%s,
                        start_local=%s, venue_name=%s,
                        address=%s, borough=%s, lat=%s, lon=%s,
                        is_free=%s, price_min=%s, price_max=%s,
                        currency=%s, categories=%s, audiences=%s,
                        age_min=%s, age_max=%s, raw=%s,
                        last_seen_utc=NOW()
                    WHERE hash=%s
                    """
                    cur.execute(
                        update_sql,
                        (
                            row["title"],
                            row["description"],
                            row["url"],
                            row["image_url"],
                            row["start_utc"],
                            row["end_utc"],
                            row["start_local"],
                            row["venue_name"],
                            row["address"],
                            row["borough"],
                            row["lat"],
                            row["lon"],
                            row["is_free"],
                            row["price_min"],
                            row["price_max"],
                            row["currency"],
                            row["categories"],
                            row["audiences"],
                            row["age_min"],
                            row["age_max"],
                            row["raw"],
                            row["hash"],
                        ),
                    )
                    updated += 1
                else:
                    # INSERT
                    insert_sql = """
                    INSERT INTO events
                    (hash, source, source_id, title, description, url, image_url,
                     start_utc, end_utc, start_local, venue_name, address, borough,
                     lat, lon, is_free, price_min, price_max, currency, categories,
                     audiences, age_min, age_max, raw)
                    VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                     %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cur.execute(
                        insert_sql,
                        (
                            row["hash"],
                            row["source"],
                            row["source_id"],
                            row["title"],
                            row["description"],
                            row["url"],
                            row["image_url"],
                            row["start_utc"],
                            row["end_utc"],
                            row["start_local"],
                            row["venue_name"],
                            row["address"],
                            row["borough"],
                            row["lat"],
                            row["lon"],
                            row["is_free"],
                            row["price_min"],
                            row["price_max"],
                            row["currency"],
                            row["categories"],
                            row["audiences"],
                            row["age_min"],
                            row["age_max"],
                            row["raw"],
                        ),
                    )
                    inserted += 1

    return inserted, updated


def record_run(source: str, inserted: int, updated: int, errors: int, note: str = "") -> None:
    """Record a source run."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO source_runs (source, finished_utc, inserted, updated, errors, note)
                VALUES (%s, NOW(), %s, %s, %s, %s)
                """,
                (source, inserted, updated, errors, note),
            )


def purge_past_events() -> int:
    """Delete events whose start time has already passed. Returns count removed."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM events WHERE start_utc IS NOT NULL AND start_utc::timestamptz < NOW()"
            )
            return cur.rowcount


def event_counts() -> dict:
    """Get summary stats."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM events")
            total = cur.fetchone()[0]

            cur.execute(
                "SELECT source, COUNT(*) AS n FROM events GROUP BY source ORDER BY n DESC"
            )
            by_source = {r[0]: r[1] for r in cur.fetchall()}

            cur.execute(
                "SELECT borough, COUNT(*) AS n FROM events GROUP BY borough ORDER BY n DESC"
            )
            by_borough = {(r[0] or "unknown"): r[1] for r in cur.fetchall()}

            cur.execute("SELECT COUNT(*) FROM events WHERE is_free = 1")
            free = cur.fetchone()[0]

    return {"total": total, "by_source": by_source, "by_borough": by_borough, "free": free}
