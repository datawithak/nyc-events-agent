#!/usr/bin/env bash
# Install the launchd job so the scraper runs every 6 hours.
set -euo pipefail

PLIST_SRC="$(cd "$(dirname "$0")" && pwd)/com.zuby.nyc-events.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.zuby.nyc-events.plist"

cp "$PLIST_SRC" "$PLIST_DEST"
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "Installed: $PLIST_DEST"
echo "To check status: launchctl list | grep nyc-events"
echo "To stop:         launchctl unload \"$PLIST_DEST\""
