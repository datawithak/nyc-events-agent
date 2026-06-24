# NYC Events Agent

A Python agent that scrapes events across all five NYC boroughs from multiple
sources, normalizes them, and stores them in a local SQLite database. It tags
each event with audience labels (kids, family, singles, parents, seniors,
LGBTQ+, 21+, etc.), categories (music, comedy, sports, food, arts, etc.), and
a price hint (free vs paid). Designed to keep running on a 6-hour schedule.

## Sources

API-first where the platform offers one. Keys are read from `.env`; sources
without their key are silently skipped.

### Enabled by default

| Source | Type | Needs key | Coverage |
|---|---|---|---|
| Ticketmaster Discovery | REST API | `TICKETMASTER_API_KEY` | concerts, sports, theater, family |
| SeatGeek | REST API | `SEATGEEK_CLIENT_ID` | concerts, sports, comedy |
| NYC Open Data (permits) | Socrata API | optional | parades, street fairs, festivals, block parties (free public events on city property) |
| Time Out NY | RSS | — | editorial roundups |
| Secret NYC | RSS | — | editorial roundups |

In a smoke test (no API keys configured), the default set pulled ~1,550
events spread across all five boroughs in under 15 seconds.

### Disabled by default (templates)

These adapters exist in `sources/` but are not auto-registered. They target
sites that sit behind anti-bot WAFs (Imperva/Incapsula) or use system-specific
calendar IDs we can't guess. Wire them in once you have a working endpoint:

| Source | Why it's off | What you need |
|---|---|---|
| NYC Parks | nycgovparks.org WAF returns HTML challenge instead of RSS | A partner feed URL or an authenticated path |
| NYPL | nypl.org calendar feed returns an Incapsula iframe | A LibCal calendar ID for `nypl.libcal.com` |
| Brooklyn Public Library | placeholder ICS URL is a guess | Calendar ID for `bklynlibrary.libcal.com` |
| Queens Public Library | same as BPL | Calendar ID for `queenslibrary.libcal.com` |
| Eventbrite RSS | RSS endpoints now redirect to HTML | Partner API or organizer-submitted ingestion |

Meetup, Bandsintown, and PredictHQ aren't included because their consumer
access requires paid or partner-only tiers. Add them as separate adapters if
you obtain access.

## Setup

```sh
cd "/Users/zuby/AI Building/nyc-events-agent"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in keys
```

Get free keys:
- Ticketmaster: https://developer-acct.ticketmaster.com/user/register
- SeatGeek: https://seatgeek.com/account/develop
- NYC Open Data app token (optional): https://data.cityofnewyork.us/profile/app_tokens

## Running

```sh
python main.py --list          # show which sources are enabled
python main.py                 # run all enabled sources
python main.py --only ticketmaster,nyc_parks
python main.py --stats         # event counts by source/borough
python main.py -v              # verbose logging
```

## Scheduling (macOS launchd)

```sh
./scripts/install_schedule.sh
```

Runs every night at 2:00 AM. Logs go to `logs/`. To stop:

```sh
launchctl unload ~/Library/LaunchAgents/com.zuby.nyc-events.plist
```

If you prefer cron, add this line to `crontab -e`:

```
0 2 * * * cd "/Users/zuby/AI Building/nyc-events-agent" && ./.venv/bin/python main.py >> logs/cron.log 2>&1
```

## Querying the data

```sh
sqlite3 events.db
```

```sql
-- free Brooklyn events this weekend
SELECT title, start_local, venue_name, url FROM events
WHERE is_free = 1 AND borough = 'Brooklyn'
  AND start_utc BETWEEN datetime('now') AND datetime('now', '+3 days')
ORDER BY start_utc;

-- singles events
SELECT title, start_local, borough FROM events
WHERE audiences LIKE '%singles%' AND start_utc > datetime('now')
ORDER BY start_utc;

-- kid-friendly across all boroughs
SELECT borough, title, start_local FROM events
WHERE audiences LIKE '%kids%' OR audiences LIKE '%family%'
ORDER BY start_utc;
```

## Schema notes

- `categories` and `audiences` are stored as JSON arrays.
- `start_utc` is ISO8601 UTC; `start_local` is America/New_York.
- Dedup is by `hash`: `(source, source_id)` when available, else
  `(source, title, venue_name, start_utc)`.
- `source_runs` tracks per-source run history with insert/update/error counts.

## Publishing considerations

You said you plan to share this. A few rules of thumb to keep it clean:

1. **Don't republish editorial article text verbatim** (Time Out, Secret NYC) —
   surface title + link + short snippet only.
2. **Cite each source** in your UI; some APIs (Ticketmaster, SeatGeek) require
   visible attribution.
3. **Honor robots.txt and rate limits.** Tenacity is configured to back off on
   429s. If you add new HTML scrapers, check `/robots.txt` first.
4. **Eventbrite is the riskiest source** — their TOS restricts automated
   collection. If your project goes public, drop this source or replace it
   with an organizer-submitted ingestion flow.

## Extending with new sources

Drop a new file in `sources/`:

```python
from sources.base import Source
from models import Event

class MyCalendar(Source):
    name = "my_calendar"
    # requires_key = "my_calendar"   # optional

    def fetch(self):
        # yield Event(...) for each event
        ...
```

Then add the import to `sources/__init__.py`. Enrichment (categories,
audiences, age bounds, free hint) runs automatically.
