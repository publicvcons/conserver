# Unattended deployment (Phase 1)

PROTOTYPE_PLAN.md Phase 1: *"Conserver based pipeline producing one
vcon per House floor session per day, fully unattended."*

## Two ways the chain runs

The link modules in `../links/` follow the upstream vcon-server
contract. They run in either environment, unchanged:

1. **Deployed vcon-server (Phase 1 cloud).** Point a vcon-server
   instance at `../config.yml`. It consumes the `publicvcons_ingress`
   Redis list and runs the `publicvcons` chain. vcon-server is an
   upstream dependency — not in this repo.
2. **Offline Mac mini (now).** `../orchestrate.py` runs the same link
   modules in `config.yml` order without Redis (filesystem vCon store),
   plus ingress (acquire + normalize + initial vCon with lawful_basis)
   and egress (corpus write + SCITT). The mini stays closed (§8).

## Unattended daily run

- `house_daily.sh` — polls the Office of the Clerk YouTube channel for
  the day's "US House Floor Proceedings" upload (public-domain primary
  source; C-SPAN is WAF-blocked) and, if not already ingested, runs it
  through `orchestrate.py --scitt`. Idempotent via markers in
  `$PVCONS_STATE`.
- `com.publicvcons.house-daily.plist` — launchd agent that runs
  `house_daily.sh` at 23:30 local daily.

Install:

```
cp deploy/com.publicvcons.house-daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.publicvcons.house-daily.plist
```

## Scope / honest status

- The link chain (lawful_basis gate → whisper.cpp → diarize →
  analyze_local) is **validated end to end** by `orchestrate.py` on a
  real artifact (see `tests/`).
- `house_daily.sh` + the plist are the unattended scheduler. The
  YouTube path in `orchestrate.py` is implemented but a full multi-hour
  live House session has **not** been ingested in anger yet — set
  `PVCONS_SEG_DUR` while shaking it out.
- Corpus git/Hugging Face mirroring is intentionally **not** automated
  here (a reviewed push step; §8 keeps the mini closed).
- SCITT is still the local ed25519 stand-in (`pipeline/scitt_sign.py`).
  Phase 1 target is the upstream `scitt` link against
  scitt.publicvcons.org — see `config.yml` and project task “Stand up
  SCITT service”.
