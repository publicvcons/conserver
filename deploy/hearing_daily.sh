#!/usr/bin/env bash
#
# hearing_daily.sh — unattended daily committee-hearing ingest
# (PROTOTYPE_PLAN.md Phase 2: "first live source expansion to one
# daily hearing").
#
# Polls an official US House committee YouTube channel (default the
# Energy & Commerce committee, @EnergyCommerce — proceedings are US
# government works, public domain under 17 USC 105; the channel is not
# WAF-walled, unlike C-SPAN) for that day's newest full-length upload
# (>= min_duration_s in the source profile), and if a new hearing is
# present that we have not already ingested, runs it through
# orchestrate.py end to end and anchors the SCITT chain.
#
# Idempotent: a marker under $STATE_DIR records ingested YouTube ids,
# so re-runs / catch-up runs do not double-process a hearing.
#
# Override the committee by exporting PVCONS_HEARING_CHANNEL, e.g.
#   PVCONS_HEARING_CHANNEL=@HomelandDems

set -euo pipefail

CONSERVER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS_PY="$HOME/venvs/tools/bin/python"
YT_DLP="$HOME/venvs/tools/bin/yt-dlp"
STATE_DIR="${PVCONS_STATE:-/Volumes/publicvcons/state}"
LOG_DIR="${PVCONS_LOGS:-/Volumes/publicvcons/logs}"
CHANNEL="${PVCONS_HEARING_CHANNEL:-@EnergyCommerce}"
SOURCE="house_committee_youtube"
MIN_DUR="${PVCONS_HEARING_MIN_DUR:-1800}"
SCITT_URL="${PVCONS_SCITT_URL:-https://scitt.publicvcons.org}"
SEG_DUR="${PVCONS_SEG_DUR:-1500}"   # first-pass cap; raise for full

mkdir -p "$STATE_DIR" "$LOG_DIR"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] $*" | tee -a "$LOG_DIR/hearing_daily.log"; }

if [[ ! -d /Volumes/publicvcons ]]; then
  log "external drive not mounted; skipping"; exit 0
fi

# Newest full-length upload on the committee channel (scan a few; pick
# the first at/above the hearing length threshold).
PICK=""
while IFS='|' read -r vid dur title; do
  [[ -z "$vid" ]] && continue
  dur=${dur%.*}; dur=${dur:-0}
  if (( dur >= MIN_DUR )); then
    PICK="$vid"; PTITLE="$title"; PDUR="$dur"; break
  fi
done < <("$YT_DLP" --no-warnings --flat-playlist --playlist-end 15 \
          --print "%(id)s|%(duration)s|%(title)s" \
          "https://www.youtube.com/$CHANNEL/videos" \
          2>>"$LOG_DIR/hearing_daily.log")

if [[ -z "$PICK" ]]; then
  log "no full-length hearing (>= ${MIN_DUR}s) on $CHANNEL yet"
  exit 0
fi

MARKER="$STATE_DIR/hearing_ingested_${PICK}"
if [[ -f "$MARKER" ]]; then
  log "already ingested $PICK; nothing to do"; exit 0
fi

UPDATE="$("$YT_DLP" --no-warnings --skip-download \
  --print "%(upload_date)s" \
  "https://www.youtube.com/watch?v=$PICK" \
  2>>"$LOG_DIR/hearing_daily.log")"
REC_DATE="${UPDATE:0:4}-${UPDATE:4:2}-${UPDATE:6:2}"

log "ingesting $CHANNEL hearing $PICK ($PTITLE) dur=${PDUR}s date=$REC_DATE"

set +e
"$TOOLS_PY" "$CONSERVER_DIR/orchestrate.py" \
  --source "$SOURCE" \
  --youtube-url "https://www.youtube.com/watch?v=$PICK" \
  --recording-date "$REC_DATE" \
  --segment-start 0 \
  --segment-dur "$SEG_DUR" \
  --subject "$PTITLE" \
  --scitt --scitt-url "$SCITT_URL" \
  >>"$LOG_DIR/hearing_daily.log" 2>&1
rc=$?
set -e

if [[ $rc -eq 0 ]]; then
  touch "$MARKER"; log "ingest OK for $PICK"
  "$(dirname "$0")/publish_atproto.sh" || true
else
  log "ingest FAILED rc=$rc for $PICK (no marker; will retry)"
fi
exit $rc
