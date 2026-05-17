#!/usr/bin/env python3
"""Assemble an IETF vcon with a lawful-basis attachment.

Uses the upstream `vcon` library (vcon-dev) as a dependency — we do not
hand-roll the vcon structure. The lawful-basis attachment is built with
the library's own implementation of the IETF lawful-basis extension
(Vcon.add_lawful_basis_attachment), which is the reference behaviour this
project exists to exercise.

Hard rule: this script refuses to emit a vcon without a populated
lawful_basis attachment.

Emits vcon.json (canonical, from the library) and a sidecar
lawful_basis.json (the attachment body, also inlined in the vcon).
"""
import argparse
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from vcon import Vcon
from vcon.party import Party
from vcon.dialog import Dialog
from vcon.extensions.lawful_basis.attachment import (
    RegistryInfo,
    ProofMechanism,
    ProofType,
)

LAWFUL_BASIS_PURPOSE = "lawful_basis"


def build_justification(meta) -> str:
    return (
        "The recorded event is a proceeding of the US House of "
        "Representatives, a work of the US government in the public "
        "domain under 17 USC 105. The source item on the Internet "
        f"Archive ({meta['ia_id']}) is additionally dedicated to the "
        "public domain under CC0 1.0. Publishing a transparent, "
        "verifiable record of federal proceedings is a task carried out "
        "in the public interest, supporting government transparency and "
        "accountability."
    )


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

    created = f"{args.recording_date}T00:00:00+00:00"
    v = Vcon.build_new(created_at=created)
    # Preserve our externally-referenced UUID so the corpus path is
    # stable; build_new mints a fresh one otherwise.
    v.vcon_dict["uuid"] = args.uuid
    v.vcon_dict["subject"] = ("House of Representatives Law.Gov Event "
                              "(May 25, 2010)")

    for i, s in enumerate(speakers):
        v.add_party(Party(
            name=f"Speaker {i + 1}",
            role="speaker",
            meta={"diarization_label": s, "identified": False},
        ))

    v.add_dialog(Dialog(
        type="recording",
        start=created,
        parties=list(range(len(speakers))),
        duration=args.seg_dur,
        mediatype="video/mp4",
        filename=f"{args.ia_id}.mp4",
        url=args.src_media_url,
        content_hash=f"sha256-{args.src_media_sha256}",
        meta={
            "note": ("Transcript times are offsets into the original "
                     "source media. This vcon covers a "
                     f"{int(args.seg_dur)}s segment beginning at "
                     f"{int(args.seg_start)}s."),
            "source_segment_start_s": args.seg_start,
        },
    ))

    v.add_analysis(
        type="transcript",
        dialog=0,
        vendor="publicvcons",
        product="whisper.cpp large-v3 + pyannote.audio 3.1",
        encoding="json",
        body={"speakers": speakers, "segments": tj["segments"]},
    )
    v.add_analysis(
        type="summary",
        dialog=0,
        vendor="publicvcons",
        product=aj.get("_model", "local-llm"),
        encoding="json",
        body={
            "summary": aj.get("summary", ""),
            "topics": aj.get("topics", []),
            "entities": aj.get("entities", {}),
            "bill_references": aj.get("bill_references", []),
            "vote_references": aj.get("vote_references", []),
            "neutral_editorial_summary":
                aj.get("neutral_editorial_summary", ""),
        },
    )

    meta = {"ia_id": args.ia_id}
    # Purpose grants in the IETF extension are structured records, not
    # bare strings. Public-domain federal material: all granted at the
    # moment we obtained it, no conditions.
    purpose_grants = [
        {"purpose": p, "granted": True, "granted_at": args.obtained_at}
        for p in ("public_transparency", "research", "journalism")
    ]

    v.add_lawful_basis_attachment(
        lawful_basis="public_task",
        expiration=None,
        purpose_grants=purpose_grants,
        terms_of_service="https://policy.publicvcons.org/terms",
        registry=RegistryInfo(
            registry_type="scitt",
            url="https://scitt.publicvcons.org",
        ),
        proof_mechanisms=[ProofMechanism(
            proof_type=ProofType.CRYPTOGRAPHIC_SIGNATURE,
            timestamp=args.obtained_at,
            proof_data={
                "mechanism": "scitt_statement_chain",
                "registry": "https://scitt.publicvcons.org",
                "stages": ["imported", "normalized", "transcribed",
                           "analyzed", "published"],
            },
        )],
        metadata={
            "justification": build_justification(meta),
            "citations": [
                "https://www.law.cornell.edu/uscode/text/17/105",
                "https://creativecommons.org/publicdomain/zero/1.0/",
                args.ia_url,
            ],
            "source": {
                "archive": "Internet_Archive",
                "archive_identifier": args.ia_id,
                "source_url": args.ia_url,
                "source_media_url": args.src_media_url,
                "source_media_sha256": args.src_media_sha256,
                "obtained_at": args.obtained_at,
                "segment_start_s": args.seg_start,
                "segment_duration_s": args.seg_dur,
            },
        },
    )

    # Hard-rule enforcement, via the library's own accessor.
    lb_attachments = v.find_lawful_basis_attachments()
    if not lb_attachments:
        raise SystemExit("refusing to assemble: no lawful_basis "
                         "attachment was produced")
    lb_body = lb_attachments[0].get("body") or {}
    required = ["lawful_basis", "purpose_grants", "terms_of_service",
                "registry", "proof_mechanisms"]
    missing = [k for k in required if not lb_body.get(k)]
    if missing:
        raise SystemExit(f"refusing to assemble: lawful_basis missing "
                         f"{missing}")

    valid, errors = v.is_valid()
    if not valid:
        raise SystemExit(f"refusing to assemble: vcon failed library "
                         f"validation: {errors}")

    Path(args.out_vcon).write_text(v.to_json())
    Path(args.out_lawful_basis).write_text(json.dumps(lb_body, indent=2))
    print(f"wrote vcon -> {args.out_vcon} (vcon spec "
          f"{v.vcon_dict.get('vcon')}, uuid {v.uuid})")
    print(f"wrote lawful_basis -> {args.out_lawful_basis}")
    print(f"parties={len(v.parties)} segments={len(tj['segments'])} "
          f"lawful_basis={lb_body.get('lawful_basis')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
