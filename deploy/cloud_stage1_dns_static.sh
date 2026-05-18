#!/usr/bin/env bash
#
# cloud_stage1_dns_static.sh — Stage 1 of the publicvcons.org cloud
# build: Cloudflare DNS + static hosting (Cloudflare Pages). Free,
# reversible, no billable resources. Run this yourself:
#
#   bash seed/conserver/deploy/cloud_stage1_dns_static.sh
#
# It is idempotent: re-running re-deploys the latest static content and
# reconciles DNS/custom-domains without duplicating anything.
#
# Reads CLOUDFLARE_API_TOKEN from ~/.publicvcons.env (never printed,
# never committed). Stage 2 (billable DO droplets + SCITT ledger
# migration) is a separate, separately-reviewed script.

set -euo pipefail

ZONE_ID="ae1366feaab1f43fc92fc88b709072a3"   # publicvcons.org (verified)
WS="$(cd "$(dirname "$0")/../../.." && pwd)"
POLICY_DIR="$WS/seed/policy/site"
SITE_DIR="$WS/seed/site"
API="https://api.cloudflare.com/client/v4"

# shellcheck disable=SC1090
source ~/.publicvcons.env 2>/dev/null || true
: "${CLOUDFLARE_API_TOKEN:?set CLOUDFLARE_API_TOKEN in ~/.publicvcons.env}"
export CLOUDFLARE_API_TOKEN
PY=~/venvs/tools/bin/python

say(){ printf '\n==> %s\n' "$*"; }
cf(){ # cf METHOD PATH [json]
  local m="$1" p="$2" d="${3:-}"
  if [ -n "$d" ]; then
    curl -fsS -X "$m" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      -H "Content-Type: application/json" -d "$d" "$API$p"
  else
    curl -fsS -X "$m" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      "$API$p"
  fi
}

# ---- preflight: probe EVERY required scope, fail fast & precise -------------
# Known ids (verified earlier); accounts-list is unreliable for scoped
# tokens so we probe the concrete endpoints the deploy actually uses.
ACCOUNT_ID="02ff9390a8a7f1ad12b68427aa8b95c2"

say "Preflight: Cloudflare token scopes"
ok_pages=0 ok_dns=0
probe(){ # url -> echoes 1 on success:true else 0, plus first error msg
  local r; r="$(curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" "$1")"
  printf '%s' "$r" | "$PY" -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: print("0|non-JSON response"); raise SystemExit
print(("1|" if d.get("success") else "0|")+(";".join(e.get("message","") for e in (d.get("errors") or [])) or "ok"))'
}
P="$(probe "$API/accounts/$ACCOUNT_ID/pages/projects?per_page=1")"
[ "${P%%|*}" = 1 ] && ok_pages=1
echo "  Account · Cloudflare Pages : $([ $ok_pages = 1 ] && echo 'OK' || echo "MISSING (${P#*|})")"
D="$(probe "$API/zones/$ZONE_ID/dns_records?per_page=1")"
[ "${D%%|*}" = 1 ] && ok_dns=1
echo "  Zone · DNS (publicvcons.org) : $([ $ok_dns = 1 ] && echo 'OK' || echo "MISSING (${D#*|})")"

if [ $ok_pages -ne 1 ] || [ $ok_dns -ne 1 ]; then
  cat <<EOF

!! Token is missing required scope(s). Do NOT edit the old token
   (editing has been dropping scopes). Create ONE fresh token:

   https://dash.cloudflare.com/profile/api-tokens
     → Create Token → Create Custom Token
     Permissions (add ALL of these rows):
       • Account · Cloudflare Pages · Edit
       • Zone    · DNS              · Edit
       • User    · Memberships      · Read
       • Account · Account Settings · Read
     Account Resources: Include → Ghostofbasho@gmail.com's Account
     Zone Resources:    Include → Specific zone → publicvcons.org
   Both resource scopes MUST be set — a Zone-only scope breaks the
   account-level Pages permission (that is the 10000 error).

   Then put it in ~/.publicvcons.env (var CLOUDFLARE_API_TOKEN) and
   re-run this script. Nothing was deployed.
EOF
  exit 1
fi
echo "  all required scopes present — proceeding"
PAGES_OK=1

# ---- helper: ensure a Cloudflare DNS record ---------------------------------
ensure_record(){ # type name content [proxied]
  local typ="$1" name="$2" content="$3" prox="${4:-true}"
  local existing id
  existing="$(cf GET "/zones/$ZONE_ID/dns_records?type=$typ&name=$name")"
  id="$(printf '%s' "$existing" | "$PY" -c \
    'import sys,json;r=json.load(sys.stdin).get("result")or[];print(r[0]["id"] if r else "")')"
  local body
  body="$("$PY" -c "import json;print(json.dumps({'type':'$typ','name':'$name','content':'$content','proxied':'$prox'=='true','ttl':1}))")"
  if [ -n "$id" ]; then
    cf PUT "/zones/$ZONE_ID/dns_records/$id" "$body" >/dev/null
    echo "  updated $typ $name -> $content"
  else
    cf POST "/zones/$ZONE_ID/dns_records" "$body" >/dev/null
    echo "  created $typ $name -> $content"
  fi
}

# ---- Stage 1b: Cloudflare Pages (static) ------------------------------------
deploy_pages(){ # project_name dir
  local proj="$1" dir="$2"
  npx --yes wrangler@latest pages project create "$proj" \
      --production-branch main 2>/dev/null || true
  CLOUDFLARE_ACCOUNT_ID="$ACCOUNT_ID" npx --yes wrangler@latest \
      pages deploy "$dir" --project-name "$proj" --branch main \
      --commit-dirty=true
}

add_pages_domain(){ # project domain
  local proj="$1" dom="$2"
  cf POST "/accounts/$ACCOUNT_ID/pages/projects/$proj/domains" \
     "$("$PY" -c "import json;print(json.dumps({'name':'$dom'}))")" \
     >/dev/null 2>&1 || true
  echo "  custom domain attached: $dom"
}

if [ "$PAGES_OK" = 1 ]; then
  say "Deploy policy.publicvcons.org (Cloudflare Pages)"
  deploy_pages publicvcons-policy "$POLICY_DIR"
  add_pages_domain publicvcons-policy policy.publicvcons.org
  ensure_record CNAME policy.publicvcons.org publicvcons-policy.pages.dev true

  say "Deploy publicvcons.org (Cloudflare Pages)"
  deploy_pages publicvcons-site "$SITE_DIR"
  add_pages_domain publicvcons-site publicvcons.org
  add_pages_domain publicvcons-site www.publicvcons.org
  ensure_record CNAME publicvcons.org publicvcons-site.pages.dev true
  ensure_record CNAME www.publicvcons.org publicvcons-site.pages.dev true
else
  say "Skipping Pages deploy (token not account-scoped). DNS only."
fi

# ---- Bluesky domain-handle TXT (placeholder, no DID yet) --------------------
say "Bluesky handle TXT"
echo "  Skipped: needs the account DID first (set _atproto.publicvcons.org"
echo "  TXT = 'did=did:plc:...' once the Bluesky account exists)."

say "Stage 1 complete."
echo "Verify in a minute or two:"
echo "  curl -sI https://policy.publicvcons.org/terms | head -1"
echo "  curl -sI https://publicvcons.org/ | head -1"
echo
echo "Note: the inert DigitalOcean DNS zone for publicvcons.org is"
echo "harmless (NS point at Cloudflare) but can be removed at your"
echo "discretion:  doctl compute domain delete publicvcons.org"
