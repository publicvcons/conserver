# Source profile schema

Every ingest source in PublicVCons gets exactly one YAML profile in this directory. The profile is the registry entry for that source: it tells the Conserver pipeline where to get media, what to record about it, and what lawful basis applies. No vcon is assembled from a source that does not have a profile here.

Profiles are versioned by edits to this folder, not by file name. The `id` field is the stable handle that vcons reference.

## Top level fields

`id` (string, required). Stable slug, lowercase with underscores. Used as the canonical source identifier on every vcon produced from this source. Never change this once a vcon has been published referencing it.

`name` (string, required). Human readable name for site and dataset UIs.

`kind` (enum, required). One of `live` or `backfill`. Backfill profiles carry an extra `sourced_from` block.

`status` (enum, required). One of `active`, `paused`, `retired`. Pipeline skips non-active sources.

`description` (string, required). One or two sentences explaining what this source covers.

`url_pattern` (string, required). The canonical access URL or pattern. For HLS or YouTube, the live stream URL. For backfill, a template with placeholders such as `{date}` or `{nara_id}`.

`refresh_cadence` (string, required). ISO 8601 duration or a cron expression. Examples: `PT5M`, `0 */1 * * *`, `event_driven`.

`acquisition` (block, required). How to pull media.
- `tool` (string): `yt-dlp`, `ffmpeg`, `httpx`, etc.
- `args` (list of strings): default arguments
- `output_audio_format` (string): expected after normalization, default `wav_16k_mono`
- `output_video_format` (string): expected after normalization, default `mp4_h264_aac`

`normalization` (block, optional, defaults from project policy).
- `audio_sample_rate_hz` (int): default 16000
- `audio_channels` (int): default 1
- `video_container` (string): default `mp4`
- `video_codec` (string): default `h264`
- `audio_codec` (string): default `aac`

`transcription` (block, optional).
- `model` (string): default `whisper.cpp:large-v3`
- `language_hint` (string): default `en`
- `word_timestamps` (bool): default true

`diarization` (block, optional).
- `engine` (string): default `pyannote.audio:3.x`
- `min_speakers` (int, nullable)
- `max_speakers` (int, nullable)

`speaker_identification` (block, optional). How to attach names to anonymous diarizer labels.
- `strategy` (enum): `enrollment_library`, `congressional_record`, `witness_list`, `none`
- `metadata_source` (string, optional): URL or pattern for the metadata feed used by the strategy

`analysis` (block, optional).
- `model` (string): default `llama3.1:8b-instruct-q4`
- `tasks` (list): default `[summary, topics, entities, neutral_editorial_summary]`

`participants_schema` (block, required). Defaults for parties on each vcon from this source.
- `default_role` (string): for example `legislator`, `witness`, `briefer`
- `affiliation_required` (bool): default true
- `anonymous_by_default` (bool): default false
- `metadata_keys` (list of strings): expected per-party metadata keys

`lawful_basis` (block, required). Default lawful basis applied to every vcon from this source. Pipeline refuses to assemble a vcon without a populated lawful basis attachment.
- `basis` (enum): one of `consent`, `contract`, `legal_obligation`, `vital_interest`, `public_task`, `legitimate_interests`
- `justification` (string): freeform legal reasoning, cited
- `purpose_grants` (list of strings): default `[public_transparency, research, journalism]`
- `expiration` (ISO 8601 string or null): null means permanent retention under public records rules
- `terms_of_service` (URL): always `https://policy.publicvcons.org/terms` unless this source publishes its own incompatible terms
- `registry` (URL): always `https://scitt.publicvcons.org`
- `proof_mechanisms` (string): always `scitt_statement_chain`
- `citations` (list of strings): URLs or statute references that anchor the justification

`rate_limits` (block, optional). Pipeline self-imposed throttling.
- `requests_per_minute` (int)
- `concurrent_downloads` (int)
- `notes` (string)

`distribution_channels` (block, optional). Defaults that flow through to the publish stage.
- `bluesky_post` (bool): default true
- `huggingface_include_audio` (bool): default false
- `huggingface_include_transcripts` (bool): default true

`media_storage` (block, optional).
- `target` (string): default `digital_ocean_spaces://publicvcons/media`
- `cdn` (URL): default `https://media.publicvcons.org`

`sourced_from` (block, required only for `kind: backfill`). Provenance of historical material.
- `archive` (string): NARA, CSPAN_Video_Library, Internet_Archive, Oyez, AAPB, Miller_Center, presidential_library, etc.
- `archive_identifier` (string): the archive's stable ID for the item
- `obtained_at` (ISO 8601 string): when we pulled the source media
- `source_media_sha256` (string): hash of the as-obtained media, set per item not per profile
- `notes` (string)

## Lifecycle expectations

Every vcon produced from a profile in this folder emits the full lifecycle SCITT statement sequence. For `live` sources: `created`, `transcribed`, `analyzed`, `published`. For `backfill` sources: `imported`, `normalized`, `transcribed`, `analyzed`, `published`. Corrections add an `amended` statement.

## File naming

`<slug>.yaml`, where `<slug>` matches the `id` field exactly. Example: `cspan_house_floor.yaml` for `id: cspan_house_floor`.
