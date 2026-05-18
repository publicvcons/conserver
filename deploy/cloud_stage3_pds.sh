#!/usr/bin/env bash
#
# cloud_stage3_pds.sh — Stage 3 of the publicvcons.org cloud build:
# the ATPROTO Personal Data Server at pds.publicvcons.org plus the
# @publicvcons.org Bluesky domain handle. Run this yourself:
#
#   bash seed/conserver/deploy/cloud_stage3_pds.sh
#
# Same model as Stage 2: idempotent, checkpointed
# (~/.publicvcons.stage3.state), every billable create behind an
# explicit y/N gate. It automates the deterministic infra (droplet +
# DNS + the official Bluesky PDS installer, run non-interactively) and
# *guides* the two irreducibly interactive bits — creating the account
# (you choose the password) and binding the @publicvcons.org handle to
# the account DID via the _atproto TXT record.
#
# The PDS is its own droplet on purpose: the bluesky-social/pds
# installer wants a dedicated host (Docker + its own Caddy, data dir
# fixed at /pds). It is NOT co-located with scitt/api.
#
# Reads CLOUDFLARE_API_TOKEN from ~/.publicvcons.env (never printed).

set -euo pipefail

ZONE_ID="ae1366feaab1f43fc92fc88b709072a3"        # publicvcons.org (verified)
API="https://api.cloudflare.com/client/v4"
WS="$(cd "$(dirname "$0")/../../.." && pwd)"
PY=~/venvs/tools/bin/python

DROPLET="publicvcons-pds"
REGION="nyc3"
SIZE="s-1vcpu-2gb"                                # $12/mo  (PDS min is modest)
IMAGE="ubuntu-24-04-x64"
PDS_HOST="pds.publicvcons.org"
HANDLE="publicvcons.org"                           # the @-handle we want
DEFAULT_ADMIN_EMAIL="thomas.howe@strolid.com"
INSTALLER_URL="https://raw.githubusercontent.com/bluesky-social/pds/main/installer.sh"

SSH_FPR="73:28:74:3f:68:ba:7a:b2:7e:31:92:b8:80:35:91:4d"   # opens-mac-mini
CREATE_KEYS="73:28:74:3f:68:ba:7a:b2:7e:31:92:b8:80:35:91:4d,4d:01:e1:a6:88:80:00:35:80:4b:b6:13:19:15:64:dc,ab:6d:c8:a0:24:c7:0f:f4:d3:37:a3:16:07:33:88:0e"
STATE="$HOME/.publicvcons.stage3.state"
SSH_OPTS=(-i "$HOME/.ssh/id_ed25519" -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

# shellcheck disable=SC1090
source ~/.publicvcons.env 2>/dev/null || true
: "${CLOUDFLARE_API_TOKEN:?set CLOUDFLARE_API_TOKEN in ~/.publicvcons.env}"

say(){ printf '\n==> %s\n' "$*"; }
done_step(){ touch "$STATE"; grep -qxF "$1" "$STATE" 2>/dev/null; }
mark(){ echo "$1" >>"$STATE"; }
confirm(){ local a; printf '\n!! %s\n   Proceed? [y/N] ' "$1"; read -r a
  [[ "$a" == y || "$a" == Y ]]; }
cf(){ local m="$1" p="$2" d="${3:-}"
  if [ -n "$d" ]; then
    curl -fsS -X "$m" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      -H "Content-Type: application/json" -d "$d" "$API$p"
  else
    curl -fsS -X "$m" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" "$API$p"
  fi; }
ensure_a_record(){ # name ip  (DNS-only: the PDS's own Caddy does ACME)
  local name="$1" ip="$2" existing id body
  existing="$(cf GET "/zones/$ZONE_ID/dns_records?type=A&name=$name")"
  id="$(printf '%s' "$existing" | "$PY" -c \
    'import sys,json;r=json.load(sys.stdin).get("result")or[];print(r[0]["id"] if r else "")')"
  body="$("$PY" -c "import json;print(json.dumps({'type':'A','name':'$name','content':'$ip','proxied':False,'ttl':1}))")"
  if [ -n "$id" ]; then cf PUT "/zones/$ZONE_ID/dns_records/$id" "$body" >/dev/null
    echo "  updated A $name -> $ip"
  else cf POST "/zones/$ZONE_ID/dns_records" "$body" >/dev/null
    echo "  created A $name -> $ip"; fi; }
ensure_txt(){ # name value
  local name="$1" val="$2" existing id body
  existing="$(cf GET "/zones/$ZONE_ID/dns_records?type=TXT&name=$name")"
  id="$(printf '%s' "$existing" | "$PY" -c \
    'import sys,json;r=json.load(sys.stdin).get("result")or[];print(r[0]["id"] if r else "")')"
  body="$("$PY" -c "import json,sys;print(json.dumps({'type':'TXT','name':sys.argv[1],'content':sys.argv[2],'ttl':1}))" "$name" "$val")"
  if [ -n "$id" ]; then cf PUT "/zones/$ZONE_ID/dns_records/$id" "$body" >/dev/null
    echo "  updated TXT $name = $val"
  else cf POST "/zones/$ZONE_ID/dns_records" "$body" >/dev/null
    echo "  created TXT $name = $val"; fi; }

droplet_ip(){ doctl compute droplet list --format Name,PublicIPv4 \
  --no-header 2>/dev/null | awk -v n="$DROPLET" '$1==n{print $2}'; }
create_droplet(){
  doctl compute droplet create "$DROPLET" --image "$IMAGE" --size "$SIZE" \
    --region "$REGION" --ssh-keys "$CREATE_KEYS" --wait \
    --format Name,PublicIPv4 --no-header
  mark "droplet-created"; }
wait_ssh(){ local ip="$1" i
  for i in $(seq 1 36); do
    ssh "${SSH_OPTS[@]}" "root@$ip" true 2>/dev/null && return 0
    sleep 5; done
  return 1; }

# ---- preflight -------------------------------------------------------------
say "Preflight"
command -v doctl >/dev/null && doctl account get >/dev/null 2>&1 \
  || { echo "doctl missing/not authed"; exit 1; }
SSHKEYS="$(doctl compute ssh-key list --format FingerPrint --no-header 2>/dev/null || true)"
if [ -z "$SSHKEYS" ]; then
  echo "Could not query DO SSH keys (transient API error?). Re-run this script."; exit 1
fi
printf '%s\n' "$SSHKEYS" | grep -qxF "$SSH_FPR" \
  || { echo "SSH key $SSH_FPR (opens-mac-mini) not on DO account"; exit 1; }
cf GET "/zones/$ZONE_ID/dns_records?per_page=1" >/dev/null \
  || { echo "Cloudflare token lacks Zone·DNS scope"; exit 1; }
ADMIN_EMAIL="${PVCONS_PDS_ADMIN_EMAIL:-}"
if [ -z "$ADMIN_EMAIL" ]; then
  printf '\nPDS admin email [%s]: ' "$DEFAULT_ADMIN_EMAIL"; read -r ADMIN_EMAIL
  ADMIN_EMAIL="${ADMIN_EMAIL:-$DEFAULT_ADMIN_EMAIL}"
fi
echo "  doctl OK · SSH key present · CF DNS scope OK · admin=$ADMIN_EMAIL"

# ---- step 1: PDS droplet (BILLABLE) ----------------------------------------
say "Step 1 — PDS droplet ($DROPLET, $SIZE @ \$12/mo, $REGION)"
IP="$(droplet_ip)"
if [ -n "$IP" ]; then
  echo "  exists: $DROPLET @ $IP — reusing (no charge)"
else
  confirm "Create DigitalOcean droplet '$DROPLET' ($SIZE, ~\$12/month, billed until destroyed) to host the ATPROTO PDS." \
    || { echo "  declined — nothing created."; exit 0; }
  create_droplet; IP="$(droplet_ip)"
fi
[ -n "$IP" ] || { echo "could not determine droplet IP"; exit 1; }
echo "  droplet IP: $IP"

say "Waiting for SSH on $IP (key: opens-mac-mini)"
if ! wait_ssh "$IP"; then
  echo "  SSH did not authenticate (droplet built with a key this"
  echo "  machine lacks). The current droplet has no PDS state yet."
  if confirm "Destroy the unreachable '$DROPLET' and recreate with correct keys? (destructive; empty droplet)"; then
    doctl compute droplet delete "$DROPLET" --force
    sed -i '' '/^droplet-created$/d' "$STATE" 2>/dev/null || true
    create_droplet; IP="$(droplet_ip)"
    echo "  recreated @ $IP"
    wait_ssh "$IP" || { echo "  still unreachable — stopping."; exit 1; }
  else echo "  left as-is. Re-run when ready."; exit 1; fi
fi
echo "  SSH up"

# ---- step 2: DNS (apex + wildcard, DNS-only) -------------------------------
# The installer's Caddy serves "$PDS_HOST" AND "*.$PDS_HOST" and gets
# its own certs, so both A records must exist (grey-cloud) BEFORE the
# install, and we then give DNS a few minutes to propagate.
say "Step 2 — Cloudflare DNS for the PDS"
ensure_a_record "$PDS_HOST"   "$IP"
ensure_a_record "*.$PDS_HOST" "$IP"
mark "dns-wired"
echo "  waiting 180s for DNS propagation before the installer (it ACMEs)..."
sleep 180

# ---- step 3: official Bluesky PDS installer (non-interactive) --------------
say "Step 3 — install the Bluesky PDS (official installer)"
if done_step "pds-installed"; then
  echo "  already installed (state file) — skipping"
else
  ssh "${SSH_OPTS[@]}" "root@$IP" \
    "curl -fsSL '$INSTALLER_URL' -o /root/pds_installer.sh && \
     bash /root/pds_installer.sh /pds '$PDS_HOST' '$ADMIN_EMAIL'"
  mark "pds-installed"
fi
echo "  PDS up. Health:"
for i in 1 2 3 4 5 6; do
  c="$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' \
       "https://$PDS_HOST/xrpc/_health" 2>/dev/null || echo 000)"
  echo "    /xrpc/_health try $i: $c"; [ "$c" = 200 ] && break; sleep 15
done

# ---- step 4: create the account -------------------------------------------
# The PDS only supports handles under .pds.publicvcons.org, so the
# account is created with a sub-handle; Step 5 sets the _atproto TXT
# and admin-switches the handle to the apex @publicvcons.org. The
# generated password is printed ONCE for you to store — it is not
# saved anywhere by this script.
SUB_HANDLE="publicvcons.$PDS_HOST"
DIDFILE="$HOME/.publicvcons.stage3.did"
say "Step 4 — create the $SUB_HANDLE account"
if done_step "account-created" && [ -s "$DIDFILE" ]; then
  DID="$(cat "$DIDFILE")"
  echo "  already created (state) — DID $DID"
else
  echo "  running: pdsadmin account create $ADMIN_EMAIL $SUB_HANDLE"
  OUT="$(ssh "${SSH_OPTS[@]}" "root@$IP" \
        "pdsadmin account create '$ADMIN_EMAIL' '$SUB_HANDLE'" 2>&1)"
  echo "------------------------------------------------------------------"
  echo "$OUT"
  echo "------------------------------------------------------------------"
  echo "  ^ SAVE the password above now — it is shown only once."
  DID="$(printf '%s' "$OUT" | grep -oE 'did:plc:[a-z0-9]+' | head -1)"
  case "$DID" in
    did:plc:*) printf '%s' "$DID" >"$DIDFILE"; chmod 600 "$DIDFILE"
               mark "account-created"; echo "  account DID: $DID" ;;
    *) echo "  could not parse a DID from output (account may already"
       echo "  exist). Fix/inspect on the droplet, then re-run."; exit 1 ;;
  esac
fi

# ---- step 5: bind @publicvcons.org to the account DID ----------------------
say "Step 5 — bind @$HANDLE -> $DID"
ensure_txt "_atproto.$HANDLE" "did=$DID"
mark "txt-set"
echo "  TXT set; allowing 60s for DNS before the admin handle switch..."
sleep 60
# Admin handle switch. The admin password is read FROM /pds/pds.env on
# the droplet itself and never leaves it / never printed here.
if done_step "handle-switched"; then
  echo "  handle already switched (state) — skipping"
else
  ssh "${SSH_OPTS[@]}" "root@$IP" bash -s "$HANDLE" "$DID" <<'REMOTE'
set -euo pipefail
NEWH="$1"; DID="$2"
AP="$(grep -E '^PDS_ADMIN_PASSWORD=' /pds/pds.env | cut -d= -f2-)"
docker exec -e PDS_ADMIN_PASSWORD="$AP" pds \
  goat pds admin account update --pds-host http://localhost:3000 \
  --handle "$NEWH" "$DID"
echo "  handle updated to $NEWH"
REMOTE
  mark "handle-switched"
fi
echo "  verify (give DNS + PLC a couple minutes):"
echo "    curl -sS 'https://$PDS_HOST/xrpc/com.atproto.identity.resolveHandle?handle=$HANDLE'"
echo "    dig +short TXT _atproto.$HANDLE"

# ---- done ------------------------------------------------------------------
say "Stage 3 complete."
cat <<EOF
PDS     : https://$PDS_HOST   (droplet $DROPLET @ $IP, $REGION)
Handle  : @$HANDLE  ->  $DID  (via _atproto TXT)
Admin   : $ADMIN_EMAIL ; pdsadmin on the droplet (ssh root@$IP)

Next: set the Bluesky bot's PDS + handle in publicvcons/atproto, then
the live ATPROTO publishing path is end to end. The vcon corpus
already carries org.publicvcons.* lexicon records.

Teardown if ever needed (DESTRUCTIVE, billable stop):
  doctl compute droplet delete $DROPLET
EOF
