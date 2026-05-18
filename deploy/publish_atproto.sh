#!/usr/bin/env bash
#
# publish_atproto.sh — publish newly-ingested vCons to the
# @publicvcons.org Bluesky/ATPROTO account. Called by the daily
# ingest runners after a successful ingest.
#
# Credentials are sourced from ~/.publicvcons.env (never committed):
#   BLUESKY_HANDLE=publicvcons.org
#   BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx   # an APP password
#   BLUESKY_PDS_URL=https://pds.publicvcons.org   # optional (default)
#
# Idempotent: publisher.py records published uuids in its state file,
# so this only posts vCons that are new. It is a deliberate no-op
# (logged) when creds are absent or the SDK/corpus is missing — a
# publish hiccup must never fail or block the ingest pipeline.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS_PY="$HOME/venvs/tools/bin/python"
PUBLISHER="${PVCONS_ATPROTO_PUBLISHER:-$HERE/../../atproto/bot/publisher.py}"
CORPUS="${PVCONS_CORPUS:-/Volumes/publicvcons/data}"
LOG_DIR="${PVCONS_LOGS:-/Volumes/publicvcons/logs}"

mkdir -p "$LOG_DIR"
ts(){ date -u +%Y-%m-%dT%H:%M:%SZ; }
log(){ echo "[$(ts)] [atproto] $*" | tee -a "$LOG_DIR/atproto_publish.log"; }

# shellcheck disable=SC1090
source ~/.publicvcons.env 2>/dev/null || true
export BLUESKY_HANDLE BLUESKY_APP_PASSWORD BLUESKY_PDS_URL

if [[ -z "${BLUESKY_HANDLE:-}" || -z "${BLUESKY_APP_PASSWORD:-}" ]]; then
  log "skipped: BLUESKY_HANDLE/BLUESKY_APP_PASSWORD not set in ~/.publicvcons.env"
  exit 0
fi
if [[ ! -f "$PUBLISHER" ]]; then
  log "skipped: publisher not found at $PUBLISHER"; exit 0
fi
if [[ ! -d "$CORPUS" ]]; then
  log "skipped: corpus dir $CORPUS not present"; exit 0
fi

log "publishing new vCons from $CORPUS as @${BLUESKY_HANDLE}"
set +e
"$TOOLS_PY" "$PUBLISHER" --corpus "$CORPUS" \
  >>"$LOG_DIR/atproto_publish.log" 2>&1
rc=$?
set -e
if [[ $rc -eq 0 ]]; then
  log "publish OK"
else
  log "publish FAILED rc=$rc (ingest unaffected; see atproto_publish.log)"
fi
exit 0   # never propagate a publish failure into the ingest job
