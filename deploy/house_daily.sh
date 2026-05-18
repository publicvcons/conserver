#!/usr/bin/env bash
#
# house_daily.sh — unattended daily House-floor ingest (Phase 1).
#
# Run once per day by launchd (see com.publicvcons.house-daily.plist).
# Polls the Office of the Clerk's official YouTube channel for that
# day's "US House Floor Proceedings (<date>)" upload (the public-domain
# primary source; C-SPAN is WAF-blocked, see source profiles), and if a
# new session is present that we have not already ingested, runs it
# through orchestrate.py end to end and signs the SCITT chain.
#
# Idempotent: a marker under $STATE_DIR records ingested YouTube ids so
# re-runs (or a catch-up run) do not double-process a session.
#
# This script does not push to the cloud; corpus git/HF mirroring is a
# separate, reviewed step (PROTOTYPE_PLAN.md §8 keeps the mini closed).

set -euo pipefail

CONSERVER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS_PY="$HOME/venvs/tools/bin/python"
YT_DLP="$HOME/venvs/tools/bin/yt-dlp"
STATE_DIR="${PVCONS_STATE:-/Volumes/publicvcons/state}"
LOG_DIR="${PVCONS_LOGS:-/Volumes/publicvcons/logs}"
CHANNEL="https://www.youtube.com/USHouseClerk/videos"
SOURCE="house_clerk_youtube"

mkdir -p "$STATE_DIR" "$LOG_DIR"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] $*" | tee -a "$LOG_DIR/house_daily.log"; }

if [[ ! -d /Volumes/publicvcons ]]; then
  log "external drive not mounted; skipping"
  exit 0
fi

# Newest upload on the Clerk channel.
read -r VID TITLE DUR UPDATE < <(
  "$YT_DLP" --no-warnings --flat-playlist --playlist-end 1 \
    --print "%(id)s\t%(title)s\t%(duration)s\t%(upload_date)s" \
    "$CHANNEL" 2>>"$LOG_DIR/house_daily.log" | head -1 \
    | awk -F'\t' '{print $1, $1, $3, $4}') || true

NEWEST_ID="$VID"
if [[ -z "${NEWEST_ID:-}" ]]; then
  log "could not resolve newest Clerk upload; will retry next run"
  exit 0
fi

MARKER="$STATE_DIR/ingested_${NEWEST_ID}"
if [[ -f "$MARKER" ]]; then
  log "already ingested $NEWEST_ID; nothing to do"
  exit 0
fi

# Resolve duration + a recording date from the upload metadata.
META="$("$YT_DLP" --no-warnings --skip-download \
  --print "%(duration)s\t%(upload_date)s\t%(title)s" \
  "https://www.youtube.com/watch?v=$NEWEST_ID" 2>>"$LOG_DIR/house_daily.log")"
DUR="$(echo "$META" | cut -f1)"
UPDATE="$(echo "$META" | cut -f2)"
TITLE="$(echo "$META" | cut -f3)"
REC_DATE="${UPDATE:0:4}-${UPDATE:4:2}-${UPDATE:6:2}"

log "ingesting Clerk session $NEWEST_ID ($TITLE) dur=${DUR}s date=$REC_DATE"

# Full session can be hours; default cap keeps a daily run tractable.
SEG_DUR="${PVCONS_SEG_DUR:-$DUR}"

set +e
"$TOOLS_PY" "$CONSERVER_DIR/orchestrate.py" \
  --source "$SOURCE" \
  --youtube-url "https://www.youtube.com/watch?v=$NEWEST_ID" \
  --recording-date "$REC_DATE" \
  --segment-start 0 \
  --segment-dur "$SEG_DUR" \
  --subject "$TITLE" \
  --scitt >>"$LOG_DIR/house_daily.log" 2>&1
rc=$?
set -e

if [[ $rc -eq 0 ]]; then
  touch "$MARKER"
  log "ingest OK for $NEWEST_ID"
  "$(dirname "$0")/publish_atproto.sh" || true
else
  log "ingest FAILED rc=$rc for $NEWEST_ID (no marker; will retry)"
fi
exit $rc
