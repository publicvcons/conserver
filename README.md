# publicvcons/conserver

Conserver deployment, ingest plugins, and source profiles for PublicVCons.

Part of the PublicVCons project.

## What is here

- `sources/*.yaml`: per-source ingest profiles (URL patterns, cadence, default lawful basis, participants schema, rate limits). Schema in `sources/SCHEMA.md`.
- `links/`: project vcon-server links following the upstream contract — `lawful_basis` (hard-rule gate), `whisper_cpp`, `diarize`, `analyze_local`. `_base.py` resolves the vCon store (VconRedis when embedded, filesystem offline).
- `config.yml`: the upstream vcon-server config defining the `publicvcons` chain and local `storage.file`.
- `orchestrate.py`: unattended ingest driver that runs the same links offline (no Redis) — ingress (acquire + normalize + lawful_basis) → chain → egress (corpus + SCITT).
- `pipeline/`: the local compute scripts the links wrap (whisper.cpp, pyannote, Ollama, SCITT signer).
- `deploy/`: launchd job + `house_daily.sh` for the unattended daily House run, and a runbook.
- `requirements/`: pinned venv lock files (see its README for the Python 3.13 rationale).
- `tests/`: the Phase 0 acceptance runner (TEST_PLAN.md T1–T10).

vcon-server (and the `vcon` library) come from the vcon-dev org as upstream dependencies. Do not fork. Only our links, profiles, config, and orchestration live here. See `deploy/README.md` for the two ways the chain runs (deployed server vs. offline mini).

## Hard rule

Every vcon assembled by this pipeline carries a lawful basis attachment and emits a SCITT statement for each lifecycle stage. No exceptions. Defaults are wired in `sources/*.yaml`.

## License

Apache 2.0.
