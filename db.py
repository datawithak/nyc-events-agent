"""Supabase PostgreSQL layer.

Two connectivity modes
─────────────────────
1. psycopg2 (direct)  — used locally; Supabase's DB host is IPv6-only so
   this fails on GitHub-hosted runners that can't route IPv6.
2. REST API (fallback) — Supabase's PostgREST endpoint runs on HTTPS/443
   which is always IPv4-reachable. Requires SUPABASE_API_URL + SUPABASE_ANON_KEY.
   The anon role must have INSERT/UPDATE/DELETE grants (done once from local Mac).
"""
from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from typing import Iterable, Iterator

import psycopg2
from psycopg2.extras import execute_values
from psycopg2.pool import SimpleConnectionPool

from config import SUPABASE_ANON_KEY, SUPABASE_API_URL, SUPABASE_POOLER_URL, SUPABASE_URL
from models import Event

log = logging.getLogger("nyc_events")

# ── REST API client (lazy) ─────────────────────────────────────────────────────
_rest_client = None
_rest_mode   = False   # set to True once psycopg2 fails and REST succeeds


def _get_rest_client():
    """Return a supabase-py client for REST API access (IPv4-safe fallback)."""
    global _rest_client
    if _rest_client is not None:
        return _rest_client
    if not SUPABASE_API_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError(
            "REST API fallback requires SUPABASE_API_URL and SUPABASE_ANON_KEY env vars. "
            "Add them to GitHub Secrets."
        )
    from supabase import create_client  # imported lazily so psycopg2-only installs still work
    _rest_client = create_client(SUPABASE_API_URL, SUPABASE_ANON_KEY)
    log.info("Supabase REST API client initialized (IPv4 fallback mode)")
    return _rest_client

# Connection pool for Supabase
_pool: SimpleConnectionPool | None = None


def _build_pooler_urls(url: str) -> list[str]:
    """Auto-derive candidate Supabase transaction-pooler URLs from a direct DB URL.

    Direct:  postgresql://postgres:PASS@db.REF.supabase.co:5432/postgres
    Pooler:  postgresql://postgres.REF:PASS@aws-0-REGION.pooler.supabase.com:6543/postgres

    The transaction pooler (port 6543) uses IPv4 and is reachable from
    GitHub Actions, whereas the direct DB (port 5432) may be IPv6-only.
    We try all Supabase AWS regions; each attempt is nearly instant because
    the pooler server accepts the TCP connection and responds with "tenant not
    found" in ~100 ms rather than timing out.
    """
    m = re.match(
        r"(postgresql|postgres)://([^:@]+):([^@]+)"
        r"@db\.([a-z0-9]+)\.supabase\.co(?::\d+)?/(\S+)",
        url,
    )
    if not m:
        return []
    _scheme, _user, password, ref, dbname = m.groups()

    # All known Supabase AWS pooler regions (as of mid-2025), most-common first.
    regions = [
        "us-east-1",
        "us-west-1",
        "us-east-2",
        "us-west-2",
        "eu-west-1",
        "eu-west-2",
        "eu-west-3",
        "eu-central-1",
        "ap-southeast-1",
        "ap-southeast-2",
        "ap-northeast-1",
        "ap-south-1",
        "ca-central-1",
        "sa-east-1",
    ]
    return [
        f"postgresql://postgres.{ref}:{password}"
        f"@aws-0-{region}.pooler.supabase.com:6543/{dbname}"
        for region in regions
    ]


def _try_pool(url: str) -> SimpleConnectionPool:
    """Create a connection pool and verify it can reach the DB."""
    pool = SimpleConnectionPool(1, 10, url)
    # SimpleConnectionPool opens minconn=1 connections eagerly; if that
    # succeeded we have a live pool.  Return it directly.
    return pool


def _get_pool() -> SimpleConnectionPool:
    """Lazy-init connection pool.

    Connection priority:
      1. SUPABASE_POOLER_URL env var (explicit override — set this in
         GitHub Actions secrets to bypass IPv6 routing issues).
      2. SUPABASE_URL directly (works from local Mac / any IPv6-capable host).
      3. Auto-constructed pooler URL derived from SUPABASE_URL (fallback for
         GitHub-hosted runners which cannot reach Supabase port 5432 over IPv6).
    """
    global _pool
    if _pool is not None:
        return _pool

    # 1 — explicit pooler URL
    if SUPABASE_POOLER_URL:
        log.info("Connecting via explicit SUPABASE_POOLER_URL")
        _pool = _try_pool(SUPABASE_POOLER_URL)
        return _pool

    # 2 — direct connection
    try:
        _pool = _try_pool(SUPABASE_URL)
        return _pool
    except psycopg2.OperationalError as exc:
        err_lower = str(exc).lower()
        if not any(kw in err_lower for kw in ("unreachable", "timeout", "refused", "network")):
            raise  # unexpected error — surface it immediately
        log.warning(
            "Direct Supabase connection failed (%s); trying transaction pooler …", exc
        )

    # 3 — try all known Supabase pooler regions automatically
    pooler_candidates = _build_pooler_urls(SUPABASE_URL)
    if not pooler_candidates:
        raise RuntimeError(
            "SUPABASE_URL does not look like a Supabase psycopg2 URL. "
            "Check Settings → Database → Connection string → Psycopg2."
        )

    last_exc: Exception | None = None
    for candidate in pooler_candidates:
        # Extract region for logging only (never log the full URL with credentials)
        region_m = re.search(r"aws-0-([^.]+)", candidate)
        region_tag = region_m.group(1) if region_m else "?"
        try:
            _pool = _try_pool(candidate)
            log.info("Connected via Supabase transaction pooler (%s)", region_tag)
            return _pool
        except psycopg2.OperationalError as exc_p:
            log.debug("Pooler %s: %s", region_tag, exc_p)
            last_exc = exc_p
            _pool = None

    # 4 — fall through to REST API mode (no exception raised here; callers check _rest_mode)
    global _rest_mode
    log.warning(
        "All psycopg2 connection attempts failed. "
        "Switching to Supabase REST API mode (HTTPS/IPv4). "
        "DDL operations (init_db) will be skipped — run them locally once."
    )
    _rest_mode = True
    return None  # type: ignore[return-value]  — callers must check _rest_mode


def _is_rest_mode() -> bool:
    """Return True if the REST API fallback is active."""
    if _rest_mode:
        return True
    # Trigger lazy init so _rest_mode is set if needed
    _get_pool()
    return _rest_mode


@contextmanager
def connect() -> Iterator[psycopg2.extensions.connection]:
    """Get connection from pool (psycopg2 mode only)."""
    pool = _get_pool()
    if _rest_mode or pool is None:
        raise RuntimeError(
            "connect() called in REST API mode — use upsert_events() directly."
        )
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
    """Create schema if it doesn't exist.

    In REST API mode (GitHub Actions), schema DDL is skipped — the schema is
    expected to exist already from a prior local run.
    """
    if _is_rest_mode():
        log.info("REST API mode: skipping init_db (schema managed from local env)")
        return
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


_REST_BATCH = 200  # rows per POST in REST API mode


def upsert_events(events: Iterable[Event]) -> tuple[int, int]:
    """Upsert events, deduping by hash. Returns (inserted, updated).

    In psycopg2 mode  — checks existence then INSERT/UPDATE per row.
    In REST API mode  — batched upsert via PostgREST (on_conflict=hash).
    """
    events_list = list(events)
    if not events_list:
        return 0, 0

    if _is_rest_mode():
        return _rest_upsert(events_list)

    inserted = updated = 0
    with connect() as conn:
        with conn.cursor() as cur:
            for ev in events_list:
                row = ev.to_row()
                cur.execute("SELECT id FROM events WHERE hash = %s", (row["hash"],))
                existing = cur.fetchone()

                if existing:
                    cur.execute(
                        """
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
                        """,
                        (
                            row["title"], row["description"], row["url"],
                            row["image_url"], row["start_utc"], row["end_utc"],
                            row["start_local"], row["venue_name"],
                            row["address"], row["borough"], row["lat"], row["lon"],
                            row["is_free"], row["price_min"], row["price_max"],
                            row["currency"], row["categories"], row["audiences"],
                            row["age_min"], row["age_max"], row["raw"],
                            row["hash"],
                        ),
                    )
                    updated += 1
                else:
                    cur.execute(
                        """
                        INSERT INTO events
                        (hash, source, source_id, title, description, url, image_url,
                         start_utc, end_utc, start_local, venue_name, address, borough,
                         lat, lon, is_free, price_min, price_max, currency, categories,
                         audiences, age_min, age_max, raw)
                        VALUES
                        (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            row["hash"], row["source"], row["source_id"],
                            row["title"], row["description"], row["url"],
                            row["image_url"], row["start_utc"], row["end_utc"],
                            row["start_local"], row["venue_name"], row["address"],
                            row["borough"], row["lat"], row["lon"],
                            row["is_free"], row["price_min"], row["price_max"],
                            row["currency"], row["categories"], row["audiences"],
                            row["age_min"], row["age_max"], row["raw"],
                        ),
                    )
                    inserted += 1

    return inserted, updated


def _rest_upsert(events_list: list[Event]) -> tuple[int, int]:
    """Batch-upsert via Supabase REST API (PostgREST on_conflict=hash)."""
    client = _get_rest_client()
    total = 0
    for i in range(0, len(events_list), _REST_BATCH):
        batch = [ev.to_row() for ev in events_list[i : i + _REST_BATCH]]
        client.table("events").upsert(batch, on_conflict="hash").execute()
        total += len(batch)
    # REST upsert can't easily distinguish insert vs update — report as inserted
    return total, 0


def record_run(source: str, inserted: int, updated: int, errors: int, note: str = "") -> None:
    """Record a source run in source_runs table."""
    if _is_rest_mode():
        from datetime import datetime, timezone
        try:
            _get_rest_client().table("source_runs").insert({
                "source": source,
                "finished_utc": datetime.now(timezone.utc).isoformat(),
                "inserted": inserted,
                "updated": updated,
                "errors": errors,
                "note": note,
            }).execute()
        except Exception as e:
            log.warning("record_run (REST) failed: %s", e)
        return

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
    if _is_rest_mode():
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            result = (
                _get_rest_client()
                .table("events")
                .delete()
                .not_.is_("start_utc", "null")
                .lt("start_utc", now_iso)
                .execute()
            )
            return len(result.data) if result.data else 0
        except Exception as e:
            log.warning("purge_past_events (REST) failed: %s", e)
            return 0

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM events WHERE start_utc IS NOT NULL AND start_utc::timestamptz < NOW()"
            )
            return cur.rowcount


def event_counts() -> dict:
    """Get summary stats."""
    if _is_rest_mode():
        try:
            r = _get_rest_client().table("events").select("*", count="exact").execute()
            total = r.count or 0
            return {"total": total, "by_source": {}, "by_borough": {}, "free": "?"}
        except Exception as e:
            log.warning("event_counts (REST) failed: %s", e)
            return {"total": "?", "by_source": {}, "by_borough": {}, "free": "?"}

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
