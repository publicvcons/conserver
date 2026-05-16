# publicvcons/conserver

Conserver deployment, ingest plugins, and source profiles for PublicVCons.

Part of the PublicVCons project.

## What is here

- `sources/*.yaml`: per source ingest profiles. Each profile defines URL patterns, refresh cadence, default lawful basis, default participants schema, and rate limits.
- `plugins/`: project specific Conserver plugins for transcription, diarization, analysis, and SCITT signing
- `deploy/`: deployment configuration for the Mac mini workhorse

The Conserver itself comes from the vcon-dev org as an upstream dependency. Do not fork it. Our customization lives here.

## Hard rule

Every vcon assembled by this pipeline carries a lawful basis attachment and emits a SCITT statement for each lifecycle stage. No exceptions. Defaults are wired in `sources/*.yaml`.

## License

Apache 2.0.
