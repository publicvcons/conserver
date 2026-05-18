# PublicVCons cloud deployment — operations runbook

The live topology, the decisions behind it, where secrets live (paths
only — never values), and the outstanding manual steps. This is the
shared record; keep it accurate when the deployment changes.

/ Verify anything here against the live system before relying on it —
IPs, the DID, and counts are derivable and may have changed. /

## Topology (live)

| Surface | Where | Notes |
|---|---|---|
| publicvcons.org, www | Cloudflare Pages `publicvcons-site` | static viewer (seed/site) |
| policy.publicvcons.org | Cloudflare Pages `publicvcons-policy` | seed/policy/site |
| scitt.publicvcons.org | DO droplet `publicvcons-svc` :8000 | SCITT service, **canonical** |
| api.publicvcons.org | same droplet :8001 | MCP streamable-http (seed/mcp) |
| media.publicvcons.org | DO Spaces `publicvcons-media` (nyc3) CDN | proxied CNAME |
| pds.publicvcons.org | DO droplet `publicvcons-pds` | ATPROTO PDS (bluesky-social/pds) |

- DNS zone: Cloudflare, zone id `ae1366feaab1f43fc92fc88b709072a3`
  (registrar = Cloudflare; NS is locked there).
- `publicvcons-svc`: s-1vcpu-2gb, nyc3. Caddy auto-TLS reverse-proxies
  scitt→127.0.0.1:8000 and api→:8001. systemd units `pvcons-scitt`,
  `pvcons-api`. scitt/api A records are grey-cloud (DNS-only) so
  Caddy can ACME.
- `publicvcons-pds`: s-1vcpu-2gb, nyc3. Official installer stack
  (Docker + its own Caddy, data dir `/pds`). Admin tooling on the
  box: `pdsadmin` and `docker exec pds goat pds admin`.
- The droplet IPs change if a droplet is recreated — get them live:
  `doctl compute droplet list --format Name,PublicIPv4 --no-header`.

## Decisions that aren't obvious from the code

- **SCITT is canonical in the cloud (option A).** The mini's
  `/Volumes/publicvcons/scitt-ledger/log.jsonl` + the *service* key
  were copied to `publicvcons-svc`; same leaves + same key ⇒ same
  Merkle root, so every receipt already committed to publicvcons/vcons
  still verifies. New anchors append in the cloud. **The mini's local
  ledger is now a stale read-only copy — do not anchor to it.** The
  *issuer* key stays on the mini (statements are signed there).
- Pipeline anchors at the cloud by default: `orchestrate.py`
  `--scitt-url` / `PVCONS_SCITT_URL` default = `https://scitt.publicvcons.org`
  (also set in `hearing_daily.sh` and the hearing plist).
- `@publicvcons.org` is a domain handle. The PDS only supports
  `.pds.publicvcons.org` handles, so the account was created as
  `publicvcons.pds.publicvcons.org`, then `_atproto.publicvcons.org`
  TXT set to its DID and the handle admin-switched to the apex.
  Account DID: `did:plc:ggmcza2pysqfgevwahtheoxh` (verify live via
  `resolveHandle` / plc.directory). PDS admin email:
  ghostofbasho@gmail.com.

## Secrets & keys (locations only — never commit values)

- `~/.publicvcons.env` (gitignored, mini): `CLOUDFLARE_API_TOKEN`,
  `SPACES_ACCESS_KEY` / `SPACES_SECRET_KEY` / `SPACES_BUCKET` /
  `SPACES_REGION`, `BLUESKY_HANDLE` / `BLUESKY_APP_PASSWORD`
  (optional `BLUESKY_PDS_URL`). Deploy scripts `source` it; it is
  never printed.
- `~/.publicvcons/scitt_ed25519.jwk` — SCITT **issuer** key, stays on
  the mini.
- `~/.publicvcons/scitt_service_ed25519.jwk` — SCITT **service** key;
  copied to `publicvcons-svc:/opt/publicvcons/keys/`.
- PDS admin password lives only on `publicvcons-pds` in
  `/pds/pds.env`; read there at runtime, never surfaced off-box.
- SSH: this mini's key is registered on DO as `opens-mac-mini`
  (fpr `73:28:74:3f:68:ba:7a:b2:7e:31:92:b8:80:35:91:4d`). Droplets
  also authorize "Thomas MBP" and "Thomass-MacBook-Air".

## Deploy scripts (gated, idempotent, run by a human)

The harness blocks agent-run production cloud mutations, so each stage
is a prepared script you run; every billable create is behind a y/N
gate and a checkpoint state file.

- `cloud_stage1_dns_static.sh` — Cloudflare DNS + Pages (free).
- `cloud_stage2_droplets.sh` — `publicvcons-svc` + SCITT option-A
  migration + Spaces. State: `~/.publicvcons.stage2.state`.
- `cloud_stage3_pds.sh` — `publicvcons-pds` + PDS install + account +
  handle bind. State: `~/.publicvcons.stage3.state`,
  DID cached at `~/.publicvcons.stage3.did`.

## Bot / ATPROTO publishing

- `seed/atproto/bot/publisher.py` — builds + lexicon-validates the
  `org.publicvcons.*` records and a feed post per vCon; live when
  `BLUESKY_HANDLE`+`BLUESKY_APP_PASSWORD` are set, else offline
  dry-run. State (published uuids): `/Volumes/publicvcons/state/atproto_posted.json`.
- `deploy/publish_atproto.sh` — sources creds from `~/.publicvcons.env`,
  runs the publisher; called by `house_daily.sh` and `hearing_daily.sh`
  after a successful ingest. Logged no-op if creds/SDK/corpus missing;
  never fails the ingest.
- `seed/atproto/bot/setup_profile.py` — one-time(ish) profile record
  (display name / description / optional avatar). Idempotent.
- Throughput: each daily runner ingests at most the single newest
  qualifying upload, so ≤2 new vCons/day (1 House floor + 1 E&C
  hearing); 0 on recess days.

## Outstanding / manual

- Relay crawl for bsky.app visibility (one-time, on the PDS droplet):
  `pdsadmin request-crawl bsky.network`. Indexing then lags minutes→~1h.
- Rotate the PDS account password (it was once pasted in a chat). The
  bot uses an app password, so a rotation does not break it:
  `pdsadmin account reset-password did:plc:ggmcza2pysqfgevwahtheoxh`.
- `sources/house_committee_youtube.yaml` is still untracked in
  publicvcons/conserver — commit it so the hearing source profile is
  reproducible.
- Corpus git / Hugging Face mirroring is still a deliberate reviewed
  step, not automated (§8 keeps the mini closed).

## Verify the deployment

```
curl -sS https://scitt.publicvcons.org/                       # tree_size, status ok
curl -sS https://scitt.publicvcons.org/.well-known/transparency-configuration
curl -sI https://publicvcons.org/ | head -1                    # 200
curl -sS https://pds.publicvcons.org/xrpc/_health              # {"version":...}
curl -sS 'https://pds.publicvcons.org/xrpc/com.atproto.identity.resolveHandle?handle=publicvcons.org'
curl -sS 'https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor=publicvcons.org&limit=5'
```

## Teardown (DESTRUCTIVE, stops billing)

```
doctl compute droplet delete publicvcons-svc
doctl compute droplet delete publicvcons-pds
# Spaces bucket + Pages projects are removed from their dashboards.
```
