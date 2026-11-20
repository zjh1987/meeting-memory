#!/bin/bash
set -euo pipefail

BASE=/opt/meeting-memory
DEST=/backup/meeting-memory/$(date +%F)
mkdir -p "$DEST"

sqlite3 "$BASE/data/app.db" ".backup '$DEST/app.db'"
rsync -a "$BASE/data/archive" "$BASE/site" "$DEST/"

find /backup/meeting-memory -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
