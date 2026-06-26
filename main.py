"""Orchestrator: run every enabled source, enrich, upsert into SQLite."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from logging.handlers import RotatingFileHandler

from config import LOG_DIR
from db import event_counts, init_db, purge_past_events, record_run, upsert_events
from sources import all_sources
from sources.base import Source

log = logging.getLogger("nyc_events")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(LOG_DIR / "agent.log", maxBytes=2_000_000, backupCount=3),
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)


def run_source(src: Source) -> tuple[int, int, int]:
    """Fetch + enrich + upsert one source. Returns (inserted, updated, errors)."""
    errors = 0
    batch: list = []
    try:
        for ev in src.fetch():
            try:
                batch.append(Source.enrich(ev))
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] enrich failed: %s", src.name, e)
                errors += 1
    except Exception as e:  # noqa: BLE001
        log.exception("[%s] fetch failed: %s", src.name, e)
        errors += 1
    inserted, updated = upsert_events(batch)
    return inserted, updated, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape NYC events into SQLite.")
    parser.add_argument("--only", help="Comma-separated source names to run (default: all enabled).")
    parser.add_argument("--skip", help="Comma-separated source names to exclude from this run.")
    parser.add_argument("--list", action="store_true", help="List sources and exit.")
    parser.add_argument("--stats", action="store_true", help="Print DB stats and exit.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    init_db()

    sources = all_sources()
    if args.list:
        for s in sources:
            mark = "ON " if s.is_enabled() else "off"
            key = f" (needs {s.requires_key})" if s.requires_key else ""
            print(f"  [{mark}] {s.name}{key}")
        return 0

    if args.stats:
        c = event_counts()
        print(f"Total events:  {c['total']}")
        print(f"Free events:   {c['free']}")
        print("By source:")
        for k, v in c["by_source"].items():
            print(f"  {k:20s} {v}")
        print("By borough:")
        for k, v in c["by_borough"].items():
            print(f"  {k:20s} {v}")
        return 0

    only = set(args.only.split(",")) if args.only else None
    skip = set(args.skip.split(",")) if args.skip else set()
    to_run = [
        s for s in sources
        if (only is None or s.name in only) and s.name not in skip and s.is_enabled()
    ]
    skipped = [s for s in sources if s not in to_run]

    purged = purge_past_events()
    if purged:
        log.info("purged %d past events", purged)

    log.info("running %d sources, skipping %d", len(to_run), len(skipped))
    for s in skipped:
        reason = "filtered" if only and s.name not in only else f"missing key '{s.requires_key}'"
        log.info("  skip %s (%s)", s.name, reason)

    grand_ins = grand_upd = grand_err = 0
    for s in to_run:
        t0 = time.monotonic()
        ins, upd, err = run_source(s)
        record_run(s.name, ins, upd, err, note=f"took {time.monotonic()-t0:.1f}s")
        log.info("  %s: +%d new, ~%d updated, %d errors", s.name, ins, upd, err)
        grand_ins += ins
        grand_upd += upd
        grand_err += err

    log.info("DONE: +%d new, ~%d updated, %d errors total", grand_ins, grand_upd, grand_err)
    return 0 if grand_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
