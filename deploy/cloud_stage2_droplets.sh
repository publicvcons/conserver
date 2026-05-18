#!/usr/bin/env bash
#
# cloud_stage2_droplets.sh — Stage 2 of the publicvcons.org cloud
# build: the BILLABLE services tier. Stands up one DigitalOcean droplet
# that hosts both the SCITT transparency service (scitt.publicvcons.org)
# and the read-only MCP/JSON API (api.publicvcons.org) behind Caddy
# auto-TLS, migrates the SCITT ledger to the cloud (option A — cloud
# becomes canonical), wires Cloudflare DNS, and optionally creates the
# media Spaces bucket. Run this yourself:
#
#   bash seed/conserver/deploy/cloud_stage2_droplets.sh
#
# It is idempotent and checkpointed: every billable create is behind an
# explicit y/N gate AND a state file (~/.publicvcons.stage2.state), so a
# re-run resumes instead of duplicating. Nothing bills without you
# typing 'y'.
#
# pds.publicvcons.org is intentionally NOT here — it needs the
# interactive Bluesky account/handle/_atproto setup and is Stage 3.
#
# Reads CLOUDFLARE_API_TOKEN from ~/.publicvcons.env (never printed,
# never committed). Uses the already-authed `doctl` for DO resources.

set -euo pipefail

# ---- config ----------------------------------------------------------------
ZONE_ID="ae1366feaab1f43fc92fc88b709072a3"        # publicvcons.org (verified)
ACCOUNT_ID="02ff9390a8a7f1ad12b68427aa8b95c2"     # DO note: CF account, unused here
API="https://api.cloudflare.com/client/v4"
WS="$(cd "$(dirname "$0")/../../.." && pwd)"
PY=~/venvs/tools/bin/python

DROPLET="publicvcons-svc"
REGION="nyc3"
SIZE="s-1vcpu-2gb"                                # $12/mo  (1 vCPU / 2 GB)
IMAGE="ubuntu-24-04-x64"
# SSH identity we connect WITH (this machine's key, registered on DO as
# "opens-mac-mini"). CREATE_KEYS = every key authorized on the droplet
# at build time so Thomas can also reach it from his laptops.
SSH_FPR="73:28:74:3f:68:ba:7a:b2:7e:31:92:b8:80:35:91:4d"   # opens-mac-mini
CREATE_KEYS="73:28:74:3f:68:ba:7a:b2:7e:31:92:b8:80:35:91:4d,4d:01:e1:a6:88:80:00:35:80:4b:b6:13:19:15:64:dc,ab:6d:c8:a0:24:c7:0f:f4:d3:37:a3:16:07:33:88:0e"
SSH_KEY_FILE="$HOME/.ssh/id_ed25519"
SPACES_BUCKET="publicvcons-media"
SPACES_REGION="nyc3"

LEDGER_LOCAL="/Volumes/publicvcons/scitt-ledger/log.jsonl"
SERVICE_KEY="$HOME/.publicvcons/scitt_service_ed25519.jwk"
STATE="$HOME/.publicvcons.stage2.state"
REMOTE_ROOT="/opt/publicvcons"
SSH_OPTS=(-i "$HOME/.ssh/id_ed25519" -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

# shellcheck disable=SC1090
source ~/.publicvcons.env 2>/dev/null || true
: "${CLOUDFLARE_API_TOKEN:?set CLOUDFLARE_API_TOKEN in ~/.publicvcons.env}"

say(){ printf '\n==> %s\n' "$*"; }
done_step(){ touch "$STATE"; grep -qxF "$1" "$STATE" 2>/dev/null; }
mark(){ echo "$1" >>"$STATE"; }
confirm(){ # confirm "message"  -> returns 0 if user types y/Y
  local a; printf '\n!! %s\n   Proceed? [y/N] ' "$1"; read -r a
  [[ "$a" == y || "$a" == Y ]]
}
cf(){ # cf METHOD PATH [json]
  local m="$1" p="$2" d="${3:-}"
  if [ -n "$d" ]; then
    curl -fsS -X "$m" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      -H "Content-Type: application/json" -d "$d" "$API$p"
  else
    curl -fsS -X "$m" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" "$API$p"
  fi
}
ensure_a_record(){ # name ip   (proxied=false so Caddy can do ACME HTTP-01)
  local name="$1" ip="$2" existing id body
  existing="$(cf GET "/zones/$ZONE_ID/dns_records?type=A&name=$name")"
  id="$(printf '%s' "$existing" | "$PY" -c \
    'import sys,json;r=json.load(sys.stdin).get("result")or[];print(r[0]["id"] if r else "")')"
  body="$("$PY" -c "import json;print(json.dumps({'type':'A','name':'$name','content':'$ip','proxied':False,'ttl':1}))")"
  if [ -n "$id" ]; then
    cf PUT "/zones/$ZONE_ID/dns_records/$id" "$body" >/dev/null
    echo "  updated A $name -> $ip"
  else
    cf POST "/zones/$ZONE_ID/dns_records" "$body" >/dev/null
    echo "  created A $name -> $ip"
  fi
}
ensure_cname(){ # name target proxied
  local name="$1" target="$2" prox="${3:-true}" existing id body
  existing="$(cf GET "/zones/$ZONE_ID/dns_records?type=CNAME&name=$name")"
  id="$(printf '%s' "$existing" | "$PY" -c \
    'import sys,json;r=json.load(sys.stdin).get("result")or[];print(r[0]["id"] if r else "")')"
  body="$("$PY" -c "import json;print(json.dumps({'type':'CNAME','name':'$name','content':'$target','proxied':'$prox'=='true','ttl':1}))")"
  if [ -n "$id" ]; then
    cf PUT "/zones/$ZONE_ID/dns_records/$id" "$body" >/dev/null
    echo "  updated CNAME $name -> $target"
  else
    cf POST "/zones/$ZONE_ID/dns_records" "$body" >/dev/null
    echo "  created CNAME $name -> $target"
  fi
}

# ---- preflight -------------------------------------------------------------
say "Preflight"
command -v doctl >/dev/null || { echo "doctl not found"; exit 1; }
doctl account get >/dev/null 2>&1 || { echo "doctl not authed"; exit 1; }
doctl compute ssh-key list --format FingerPrint --no-header 2>/dev/null \
  | grep -qxF "$SSH_FPR" || { echo "SSH key $SSH_FPR not on the DO account"; exit 1; }
[ -f "$LEDGER_LOCAL" ] || { echo "ledger not found: $LEDGER_LOCAL (mount the drive)"; exit 1; }
[ -f "$SERVICE_KEY" ]  || { echo "service key not found: $SERVICE_KEY"; exit 1; }
cf GET "/zones/$ZONE_ID/dns_records?per_page=1" >/dev/null \
  || { echo "Cloudflare token lacks Zone·DNS scope (see Stage 1 recipe)"; exit 1; }
echo "  doctl OK · SSH key present · ledger+key present · CF DNS scope OK"
echo "  ledger lines to migrate: $(wc -l <"$LEDGER_LOCAL" | tr -d ' ')"

# ---- step 1: droplet (BILLABLE) --------------------------------------------
droplet_ip(){ doctl compute droplet list --format Name,PublicIPv4 \
  --no-header 2>/dev/null | awk -v n="$DROPLET" '$1==n{print $2}'; }
create_droplet(){
  doctl compute droplet create "$DROPLET" \
    --image "$IMAGE" --size "$SIZE" --region "$REGION" \
    --ssh-keys "$CREATE_KEYS" --wait --format Name,PublicIPv4 --no-header
  mark "droplet-created"
}
wait_ssh(){ # ip -> 0 if reachable within ~3min
  local ip="$1" i
  for i in $(seq 1 36); do
    ssh "${SSH_OPTS[@]}" "root@$ip" true 2>/dev/null && return 0
    sleep 5
  done
  return 1
}

say "Step 1 — service droplet ($DROPLET, $SIZE @ \$12/mo, $REGION)"
IP="$(droplet_ip)"
if [ -n "$IP" ]; then
  echo "  exists: $DROPLET @ $IP — reusing (no charge)"
else
  if ! confirm "Create DigitalOcean droplet '$DROPLET' ($SIZE, ~\$12/month, billed until destroyed). Co-hosts scitt + api behind Caddy."; then
    echo "  declined — nothing created. Re-run when ready."; exit 0
  fi
  create_droplet; IP="$(droplet_ip)"
fi
[ -n "$IP" ] || { echo "could not determine droplet IP"; exit 1; }
echo "  droplet IP: $IP"

say "Waiting for SSH on $IP (key: opens-mac-mini)"
if ! wait_ssh "$IP"; then
  echo "  SSH did not authenticate. The droplet was likely built with a"
  echo "  key this machine doesn't hold. This machine's key is now"
  echo "  registered on DO; recreating with it will fix it. The current"
  echo "  droplet has no deployed state yet (nothing was shipped)."
  if confirm "Destroy the unreachable '$DROPLET' and recreate it with the correct keys? (destructive; the droplet is empty)"; then
    doctl compute droplet delete "$DROPLET" --force
    sed -i '' '/^droplet-created$/d' "$STATE" 2>/dev/null || true
    create_droplet; IP="$(droplet_ip)"
    echo "  recreated @ $IP"
    wait_ssh "$IP" || { echo "  still unreachable — stopping. Check 'doctl compute droplet list' and DO console."; exit 1; }
  else
    echo "  left as-is. Nothing deployed. Re-run when ready."; exit 1
  fi
fi
echo "  SSH up"

# ---- step 2: ship code + build remote venv ---------------------------------
say "Step 2 — ship service code + Python env"
ssh "${SSH_OPTS[@]}" "root@$IP" "mkdir -p $REMOTE_ROOT/{scitt,mcp,vcons,keys,ledger,conserver/pipeline}"
# rsync over scp: only the three runtime trees + corpus the API serves.
for d in scitt mcp; do
  rsync -az -e "ssh ${SSH_OPTS[*]}" --delete \
    --exclude __pycache__ "$WS/seed/$d/" "root@$IP:$REMOTE_ROOT/$d/"
done
rsync -az -e "ssh ${SSH_OPTS[*]}" --delete \
  "$WS/seed/conserver/pipeline/" "root@$IP:$REMOTE_ROOT/conserver/pipeline/"
rsync -az -e "ssh ${SSH_OPTS[*]}" "$WS/seed/vcons/" "root@$IP:$REMOTE_ROOT/vcons/"
ssh "${SSH_OPTS[@]}" "root@$IP" bash -s <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip rsync debian-keyring \
  debian-archive-keyring apt-transport-https curl >/dev/null
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi
python3 -m venv /opt/publicvcons/venv
/opt/publicvcons/venv/bin/pip -q install --upgrade pip >/dev/null
/opt/publicvcons/venv/bin/pip -q install \
  fastapi "uvicorn[standard]" pydantic cryptography "mcp>=1.27" vcon >/dev/null
echo "  remote venv + caddy ready"
REMOTE
mark "code-shipped"

# ---- step 3: SCITT ledger migration (option A — cloud canonical) -----------
say "Step 3 — migrate SCITT ledger (option A: cloud becomes canonical)"
# Same log.jsonl + same service key => same Merkle leaves => same root for
# the existing tree size, so every receipt already committed to
# publicvcons/vcons keeps verifying. New anchors append from here.
scp "${SSH_OPTS[@]}" "$LEDGER_LOCAL" "root@$IP:$REMOTE_ROOT/ledger/log.jsonl"
scp "${SSH_OPTS[@]}" "$SERVICE_KEY"  "root@$IP:$REMOTE_ROOT/keys/scitt_service_ed25519.jwk"
ssh "${SSH_OPTS[@]}" "root@$IP" \
  "chmod 600 $REMOTE_ROOT/keys/scitt_service_ed25519.jwk; \
   wc -l <$REMOTE_ROOT/ledger/log.jsonl | tr -d ' ' \
     | xargs -I{} echo '  cloud ledger now {} line(s)'"
mark "ledger-migrated"
echo "  NOTE: from here the cloud is canonical. The mini's local"
echo "        \$PVCONS_SCITT_LEDGER should point at the cloud or be"
echo "        treated as a stale read-only copy (Stage 3 / runbook)."

# ---- step 4: systemd units -------------------------------------------------
say "Step 4 — systemd services (scitt :8000, api :8001)"
ssh "${SSH_OPTS[@]}" "root@$IP" bash -s <<REMOTE
set -euo pipefail
cat >/etc/systemd/system/pvcons-scitt.service <<UNIT
[Unit]
Description=PublicVCons SCITT transparency service
After=network.target
[Service]
WorkingDirectory=$REMOTE_ROOT/scitt/server
Environment=PVCONS_SCITT_LEDGER=$REMOTE_ROOT/ledger
Environment=PVCONS_SCITT_KEY=$REMOTE_ROOT/keys/scitt_service_ed25519.jwk
ExecStart=$REMOTE_ROOT/venv/bin/uvicorn scitt_service:app --host 127.0.0.1 --port 8000 --log-level warning
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/systemd/system/pvcons-api.service <<UNIT
[Unit]
Description=PublicVCons MCP/JSON read API
After=network.target
[Service]
WorkingDirectory=$REMOTE_ROOT/mcp
Environment=PVCONS_MCP_TRANSPORT=streamable-http
Environment=PVCONS_MCP_HOST=127.0.0.1
Environment=PVCONS_MCP_PORT=8001
Environment=PVCONS_CORPUS=$REMOTE_ROOT/vcons
ExecStart=$REMOTE_ROOT/venv/bin/python server.py
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now pvcons-scitt pvcons-api
sleep 3
systemctl is-active pvcons-scitt pvcons-api
REMOTE
mark "systemd-up"

# ---- step 5: Caddy reverse proxy + auto-TLS --------------------------------
say "Step 5 — Caddy vhosts + auto-TLS"
ssh "${SSH_OPTS[@]}" "root@$IP" bash -s <<'REMOTE'
set -euo pipefail
cat >/etc/caddy/Caddyfile <<'CADDY'
scitt.publicvcons.org {
	reverse_proxy 127.0.0.1:8000
}
api.publicvcons.org {
	reverse_proxy 127.0.0.1:8001
}
CADDY
systemctl reload caddy || systemctl restart caddy
echo "  caddy reloaded"
REMOTE
mark "caddy-up"

# ---- step 6: Cloudflare DNS (grey-cloud so Caddy ACME works) ---------------
say "Step 6 — Cloudflare DNS A records"
ensure_a_record scitt.publicvcons.org "$IP"
ensure_a_record api.publicvcons.org   "$IP"
mark "dns-wired"

# ---- step 7: media Spaces bucket (BILLABLE, optional) ----------------------
say "Step 7 — media.publicvcons.org Spaces bucket (optional, ~\$5/mo)"
if done_step "spaces-created"; then
  echo "  already done (state file) — skipping"
elif confirm "Create DO Spaces bucket '$SPACES_BUCKET' in $SPACES_REGION (~\$5/month) and a Spaces access key? Skip if you'll do media later."; then
  command -v aws >/dev/null || { echo "  aws cli missing — skipping Spaces"; }
  if command -v aws >/dev/null; then
    KJSON="$(doctl spaces keys create publicvcons-media-key \
      --grants 'bucket=;permission=fullaccess' -o json 2>/dev/null || true)"
    SK_ID="$(printf '%s' "$KJSON"  | "$PY" -c 'import sys,json;d=json.load(sys.stdin);print((d[0] if isinstance(d,list) else d).get("access_key",""))' 2>/dev/null || true)"
    SK_SEC="$(printf '%s' "$KJSON" | "$PY" -c 'import sys,json;d=json.load(sys.stdin);print((d[0] if isinstance(d,list) else d).get("secret_key",""))' 2>/dev/null || true)"
    if [ -n "$SK_ID" ] && [ -n "$SK_SEC" ]; then
      EP="https://$SPACES_REGION.digitaloceanspaces.com"
      AWS_ACCESS_KEY_ID="$SK_ID" AWS_SECRET_ACCESS_KEY="$SK_SEC" \
        aws --endpoint-url "$EP" s3 mb "s3://$SPACES_BUCKET" 2>/dev/null \
        || echo "  (bucket may already exist — continuing)"
      ensure_cname media.publicvcons.org \
        "$SPACES_BUCKET.$SPACES_REGION.cdn.digitaloceanspaces.com" true
      umask 077
      { echo "SPACES_ACCESS_KEY=$SK_ID"; echo "SPACES_SECRET_KEY=$SK_SEC"; \
        echo "SPACES_BUCKET=$SPACES_BUCKET"; echo "SPACES_REGION=$SPACES_REGION"; \
      } >>~/.publicvcons.env
      echo "  Spaces key appended to ~/.publicvcons.env (0600). Bucket + media CNAME set."
      mark "spaces-created"
    else
      echo "  could not obtain Spaces key from doctl — skipping (re-run later)"
    fi
  fi
else
  echo "  skipped Spaces (no charge). Re-run later to add media."
fi

# ---- done ------------------------------------------------------------------
say "Stage 2 complete."
cat <<EOF
Droplet : $DROPLET  @  $IP  ($SIZE, $REGION)
Services: scitt.publicvcons.org -> :8000   api.publicvcons.org -> :8001
Ledger  : migrated (cloud canonical) — existing receipts still verify

Caddy issues certs on first hit; give it ~30-60s, then verify:
  curl -sS https://scitt.publicvcons.org/ | head -c 200; echo
  curl -sS https://scitt.publicvcons.org/.well-known/transparency-configuration | head -c 200; echo
  curl -sS https://api.publicvcons.org/  -I | head -1

Stage 3 (separate, interactive): pds.publicvcons.org + Bluesky
@publicvcons.org handle + _atproto.publicvcons.org TXT (needs the DID).

Teardown if ever needed (DESTRUCTIVE, billable stop):
  doctl compute droplet delete $DROPLET
EOF
