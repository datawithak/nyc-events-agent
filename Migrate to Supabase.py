#!/usr/bin/env python3
"""
Migrate events from local SQLite to Supabase PostgreSQL.
Run this once to backfill your 5,517 existing events.

Usage:
    python3 migrate_to_supabase.py
"""
import sqlite3
import sys
from pathlib import Path

try:
    import psycopg2
except ImportError:
    print("Install psycopg2: pip install psycopg2-binary")
    sys.exit(1)

# Config
SQLITE_DB = Path("/Users/zuby/AI Building/nyc-events-agent/events.db")
SUPABASE_URL = input("Enter SUPABASE_URL from .env: ").strip()

if not SUPABASE_URL:
    print("SUPABASE_URL required")
    sys.exit(1)

if not SQLITE_DB.exists():
    print(f"SQLite DB not found: {SQLITE_DB}")
    sys.exit(1)

print(f"Reading from: {SQLITE_DB}")
print(f"Writing to:   Supabase")
print()

# Read from SQLite
sqlite_conn = sqlite3.connect(SQLITE_DB)
sqlite_conn.row_factory = sqlite3.Row
sqlite_cur = sqlite_conn.cursor()
sqlite_cur.execute("SELECT COUNT(*) FROM events")
total = sqlite_cur.fetchone()[0]
print(f"Found {total} events in SQLite")

# Connect to Supabase
try:
    pg_conn = psycopg2.connect(SUPABASE_URL)
    pg_cur = pg_conn.cursor()
except Exception as e:
    print(f"Failed to connect to Supabase: {e}")
    print("Check your SUPABASE_URL and ensure schema is initialized.")
    sys.exit(1)

# Migrate
sqlite_cur.execute("SELECT * FROM events")
migrated = 0
failed = 0

for row in sqlite_cur.fetchall():
    try:
        # Map SQLite columns to PostgreSQL
        pg_cur.execute(
            """
            INSERT INTO events
            (hash, source, source_id, title, description, url, image_url,
             start_utc, end_utc, start_local, venue_name, address, borough,
             lat, lon, is_free, price_min, price_max, currency, categories,
             audiences, age_min, age_max, raw, first_seen_utc, last_seen_utc)
            VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
             %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (hash) DO NOTHING
            """,
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
                row["first_seen_utc"],
                row["last_seen_utc"],
            ),
        )
        migrated += 1
        if migrated % 500 == 0:
            pg_conn.commit()
            print(f"  ✓ {migrated}/{total}")
    except Exception as e:
        failed += 1
        print(f"  ✗ Failed to insert: {e}")

pg_conn.commit()
sqlite_conn.close()
pg_conn.close()

print()
print(f"Done! Migrated {migrated} events ({failed} failed)")
