"""Central config — env vars, paths, scrape window, NYC bounding box."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# Supabase PostgreSQL connection string (direct, port 5432)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
if not SUPABASE_URL:
    raise ValueError(
        "SUPABASE_URL not set in .env. "
        "Get it from Supabase dashboard: Settings → Database → Psycopg2"
    )

# Optional: Transaction Pooler URL (port 6543, IPv4) — required for GitHub Actions.
# Get from Supabase → Settings → Database → Connection string → Transaction pooler.
# If set, db.py uses it instead of the direct URL.
SUPABASE_POOLER_URL = os.getenv("SUPABASE_POOLER_URL", "").strip()

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# How far ahead to fetch events (days).
LOOKAHEAD_DAYS = int(os.getenv("LOOKAHEAD_DAYS", "90"))

# NYC bounding box (rough): SW (40.4774, -74.2591) → NE (40.9176, -73.7004).
NYC_BBOX = {
    "south": 40.4774,
    "west": -74.2591,
    "north": 40.9176,
    "east": -73.7004,
}

# Per-source HTTP defaults.
USER_AGENT = (
    "nyc-events-agent/0.1 (+https://example.com/contact; respectful crawler)"
)
HTTP_TIMEOUT = 20

API_KEYS = {
    "ticketmaster": os.getenv("TICKETMASTER_API_KEY", "").strip(),
    "seatgeek": os.getenv("SEATGEEK_CLIENT_ID", "").strip(),
    "seatgeek_secret": os.getenv("SEATGEEK_CLIENT_SECRET", "").strip(),
    "yelp": os.getenv("YELP_API_KEY", "").strip(),
    "nyc_open_data": os.getenv("NYC_OPEN_DATA_APP_TOKEN", "").strip(),
    "eventbrite": os.getenv("EVENTBRITE_OAUTH_TOKEN", "").strip(),
    "predicthq": os.getenv("PREDICTHQ_API_KEY", "").strip(),
    "bandsintown": os.getenv("BANDSINTOWN_APP_ID", "").strip(),
}
