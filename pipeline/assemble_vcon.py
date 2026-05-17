#!/usr/bin/env python3
"""Assemble an IETF vcon with a lawful-basis attachment.

Hard rule: this script refuses to emit a vcon without a populated
lawful_basis attachment.

Inputs come from the run manifest (env file) plus the merged transcript
and analysis JSON. Emits vcon.json and a sidecar lawful_basis.json (the
attachment is also inlined in the vcon, per the publicvcons/vcons
convention).
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

VCON_VERSION = "0.0.2"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def build_lawful_basis(meta) -> dict:
    """Public-domain US federal proceeding obtained from a CC0 archive.

    The underlying conversation is a US government work in the public
    domain (17 USC 105); the Internet Archive item is additionally
    dedicated CC0. Basis is public_task: publishing transparent records
    of federal proceedings is a task carried out in the public interest.
    """
    return {
        "lawful_basis": "public_task",
        "justification": (
            "The recorded event is a proceeding of the US House of "
            "Representatives, a work of the US government in the public "
            "domain under 17 USC 105. The source item on the Internet "
            f"Archive ({meta['ia_id']}) is additionally dedicated to the "
            "public domain under CC0 1.0. Publishing a transparent, "
            "verifiable record of federal proceedings is a task carried "
            "out in the public interest, supporting government "
            "transparency and accountability."
        ),
        "purpose_grants": ["public_transparency", "research", "journalism"],
        "expiration": None,
        "terms_of_service": "https://policy.publicvcons.org/terms",
        "registry": "https://scitt.publicvcons.org",
        "proof_mechanisms": "scitt_statement_chain",
        "citations": [
            "https://www.law.cornell.edu/uscode/text/17/105",
            "https://creativecommons.org/publicdomain/zero/1.0/",
            meta["ia_url"],
        ],
        "source": {
            "archive": "Internet_Archive",
            "archive_identifier": meta["ia_id"],
            "source_url": meta["ia_url"],
            "source_media_url": meta["src_media_url"],
            "source_media_sha256": meta["src_media_sha256"],
            "obtained_at": meta["obtained_at"],
            "segment_start_s": meta["seg_start"],
            "segment_duration_s": meta["seg_dur"],
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript-json", required=True)
    ap.add_argument("--analysis-json", required=True)
    ap.add_argument("--uuid", required=True)
    ap.add_argument("--recording-date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--ia-id", required=True)
    ap.add_argument("--ia-url", required=True)
    ap.add_argument("--src-media-url", required=True)
    ap.add_argument("--src-media-sha256", required=True)
    ap.add_argument("--obtained-at", required=True)
    ap.add_argument("--seg-start", type=float, required=True)
    ap.add_argument("--seg-dur", type=float, required=True)
    ap.add_argument("--out-vcon", required=True)
    ap.add_argument("--out-lawful-basis", required=True)
    args = ap.parse_args()

    tj = json.loads(Path(args.transcript_json).read_text())
    aj = json.loads(Path(args.analysis_json).read_text())

    speakers = tj["speakers"]
    parties = [
        {"name": f"Speaker {i + 1}",
         "role": "speaker",
         "meta": {"diarization_label": s, "identified": False}}
        for i, s in enumerate(speakers)
    ]
    spk_idx = {s: i for i, s in enumerate(speakers)}

    transcript_body = {
        "speakers": speakers,
        "segments": tj["segments"],
    }

    created = f"{args.recording_date}T00:00:00.000Z"
    dialog = [{
        "type": "recording",
        "start": created,
        "duration": args.seg_dur,
        "parties": list(range(len(parties))),
        "mediatype": "video/mp4",
        "filename": f"{args.ia_id}.mp4",
        "url": args.src_media_url,
        "content_hash": f"sha256-{args.src_media_sha256}",
        "meta": {
            "note": ("Times in the transcript are offsets into the "
                     "original source media. This vcon covers a "
                     f"{int(args.seg_dur)}s segment beginning at "
                     f"{int(args.seg_start)}s."),
        },
    }]

    analysis = [
        {
            "type": "transcript",
            "dialog": 0,
            "vendor": "publicvcons",
            "product": "whisper.cpp large-v3 + pyannote.audio 3.1",
            "encoding": "json",
            "body": transcript_body,
        },
        {
            "type": "summary",
            "dialog": 0,
            "vendor": "publicvcons",
            "product": aj.get("_model", "local-llm"),
            "encoding": "json",
            "body": {
                "summary": aj.get("summary", ""),
                "topics": aj.get("topics", []),
                "entities": aj.get("entities", {}),
                "bill_references": aj.get("bill_references", []),
                "vote_references": aj.get("vote_references", []),
                "neutral_editorial_summary":
                    aj.get("neutral_editorial_summary", ""),
            },
        },
    ]

    meta = {
        "ia_id": args.ia_id,
        "ia_url": args.ia_url,
        "src_media_url": args.src_media_url,
        "src_media_sha256": args.src_media_sha256,
        "obtained_at": args.obtained_at,
        "seg_start": args.seg_start,
        "seg_dur": args.seg_dur,
    }
    lawful_basis = build_lawful_basis(meta)

    # Hard rule enforcement.
    required = ["lawful_basis", "purpose_grants", "terms_of_service",
                "registry", "proof_mechanisms"]
    missing = [k for k in required if not lawful_basis.get(k)]
    if missing:
        raise SystemExit(f"refusing to assemble: lawful_basis missing "
                          f"{missing}")

    vcon = {
        "vcon": VCON_VERSION,
        "uuid": args.uuid,
        "created_at": created,
        "updated_at": now_iso(),
        "subject": "House of Representatives Law.Gov Event (May 25, 2010)",
        "parties": parties,
        "dialog": dialog,
        "analysis": analysis,
        "attachments": [{
            "type": "lawful_basis",
            "encoding": "json",
            "body": lawful_basis,
        }],
    }

    Path(args.out_lawful_basis).write_text(
        json.dumps(lawful_basis, indent=2))
    Path(args.out_vcon).write_text(json.dumps(vcon, indent=2))
    print(f"wrote vcon -> {args.out_vcon}")
    print(f"wrote lawful_basis -> {args.out_lawful_basis}")
    print(f"parties={len(parties)} segments={len(tj['segments'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
