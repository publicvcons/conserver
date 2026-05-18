#!/usr/bin/env python3
"""PublicVCons unattended ingest orchestrator (Phase 1).

The Mac mini stays offline (PROTOTYPE_PLAN.md §8), so this driver runs
the *same* vcon-server link modules from config.yml without Redis:

  ingress  : load source profile -> acquire media -> ffmpeg normalize
             -> build initial vCon with the lawful_basis attachment from
             the profile (hard rule enforced at ingress)
  chain    : run the config.yml `publicvcons` chain links in order
             (lawful_basis gate, whisper_cpp, diarize, analyze_local)
  egress   : write vcon.json + lawful_basis.json to the local corpus,
             sign the SCITT lifecycle chain, optionally mirror to the
             vcons git repo

When vcon-server is deployed in Phase 1 cloud, the chain half is run by
the server from config.yml instead; ingress/egress stay here on the
mini. Same link code, two runners.

Examples:
  # backfill an Internet Archive item end to end, sign + stage to corpus
  orchestrate.py --source ia_gov_house --archive-id gov.house.20100525 \
      --recording-date 2010-05-25 --segment-start 120 --segment-dur 1500 \
      --scitt

  # reuse cached intermediates (fast pipeline re-validation)
  orchestrate.py --source ia_gov_house --archive-id gov.house.20100525 \
      --recording-date 2010-05-25 --segment-start 120 --segment-dur 1500 \
      --reuse-work /Volumes/publicvcons/work/<uuid> --scitt
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid as uuidlib
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))            # for `import links.<name>`
sys.path.insert(0, str(HERE / "links"))  # for `_base`
from _base import init_logger, load_source_profile  # noqa: E402

logger = init_logger("pvcons.orchestrate")

DRIVE = Path(os.environ.get("PUBLICVCONS_ROOT", "/Volumes/publicvcons"))
DATA_ROOT = DRIVE / "data"
MEDIA_ROOT = DRIVE / "media"
WORK_ROOT = DRIVE / "work"
TOOLS_PY = os.path.expanduser("~/venvs/tools/bin/python")
SCITT = HERE / "pipeline" / "scitt_sign.py"
CHAIN = ["lawful_basis", "whisper_cpp", "diarize", "analyze_local"]
BACKFILL_STAGES = ["imported", "normalized", "transcribed", "analyzed",
                   "published"]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def acquire_internet_archive(archive_id: str, media_dir: Path,
                             ia_file: str | None = None) -> Path:
    """Download an IA item file.

    Default is the single-file derivative `{id}_512kb.mp4`. For
    multi-file items (NASA audio, nested hearing collections) pass
    --ia-file with the exact file name within the item.
    """
    media_dir.mkdir(parents=True, exist_ok=True)
    fname = ia_file or f"{archive_id}_512kb.mp4"
    local = (f"{archive_id}__" +
             fname.replace("/", "_")) if ia_file else f"{archive_id}.mp4"
    out = media_dir / local
    if out.is_file() and out.stat().st_size > 0:
        logger.info("source already present: %s", out)
        return out
    from urllib.parse import quote
    url = (f"https://archive.org/download/{archive_id}/"
           f"{quote(fname)}")
    logger.info("downloading %s", url)
    subprocess.run(["curl", "-sL", "-A", "pvcons/0.1",
                    "-o", str(out), url], check=True)
    if not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError(f"IA download failed: {url}")
    return out


def acquire_youtube(yt_url: str, media_dir: Path, slug: str) -> Path:
    media_dir.mkdir(parents=True, exist_ok=True)
    out = media_dir / f"{slug}.mp4"
    if out.is_file() and out.stat().st_size > 0:
        return out
    logger.info("yt-dlp %s", yt_url)
    subprocess.run([
        os.path.expanduser("~/venvs/tools/bin/yt-dlp"),
        "--no-part", "--no-mtime", "--restrict-filenames",
        "-f", "bv*+ba/b", "--merge-output-format", "mp4",
        "-o", str(media_dir / f"{slug}.%(ext)s"), yt_url,
    ], check=True, capture_output=True)
    if not out.is_file():
        raise RuntimeError("yt-dlp produced no mp4")
    return out


def normalize_segment(src: Path, work: Path, start: float,
                       dur: float) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    wav = work / "audio_16k.wav"
    if wav.is_file() and wav.stat().st_size > 0:
        logger.info("normalized wav present: %s", wav)
        return wav
    logger.info("ffmpeg normalize [%.0f,+%.0f] -> 16k mono wav",
                start, dur)
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-ss", str(start),
        "-t", str(dur), "-i", str(src), "-ac", "1", "-ar", "16000",
        "-vn", "-c:a", "pcm_s16le", str(wav), "-y",
    ], check=True)
    return wav


def build_purpose_grants(profile_lb: dict, obtained_at: str) -> list:
    grants = profile_lb.get("purpose_grants",
                            ["public_transparency", "research",
                             "journalism"])
    return [{"purpose": p, "granted": True, "granted_at": obtained_at}
            for p in grants]


def build_initial_vcon(vid: str, subject: str, rec_date: str,
                        src_url: str, src_media_url: str,
                        src_sha: str, ia_id: str, wav: Path,
                        seg_start: float, seg_dur: float,
                        profile: dict, obtained_at: str):
    from vcon import Vcon
    from vcon.dialog import Dialog
    from vcon.extensions.lawful_basis.attachment import (
        RegistryInfo, ProofMechanism, ProofType)

    created = f"{rec_date}T00:00:00+00:00"
    v = Vcon.build_new(created_at=created)
    v.vcon_dict["uuid"] = vid
    v.vcon_dict["subject"] = subject

    v.add_dialog(Dialog(
        type="recording",
        start=created,
        parties=[],
        duration=seg_dur,
        mediatype=("audio/mpeg" if src_media_url.lower()
                   .endswith((".mp3", ".m4a", ".wav"))
                   else "video/mp4"),
        filename=src_media_url.rsplit("/", 1)[-1],
        url=src_media_url,
        content_hash=f"sha256-{src_sha}",
        meta={
            "note": (f"Transcript times are offsets into the original "
                     f"source media. Segment {int(seg_dur)}s from "
                     f"{int(seg_start)}s."),
            "source_segment_start_s": seg_start,
            "local_wav": str(wav),
        },
    ))

    plb = profile.get("lawful_basis", {})
    v.add_lawful_basis_attachment(
        lawful_basis=plb.get("basis", "public_task"),
        expiration=plb.get("expiration"),
        purpose_grants=build_purpose_grants(plb, obtained_at),
        terms_of_service=plb.get(
            "terms_of_service", "https://policy.publicvcons.org/terms"),
        registry=RegistryInfo(
            registry_type="scitt",
            url=plb.get("registry", "https://scitt.publicvcons.org")),
        proof_mechanisms=[ProofMechanism(
            proof_type=ProofType.CRYPTOGRAPHIC_SIGNATURE,
            timestamp=obtained_at,
            proof_data={
                "mechanism": "scitt_statement_chain",
                "registry": plb.get(
                    "registry", "https://scitt.publicvcons.org"),
                "stages": BACKFILL_STAGES,
            })],
        metadata={
            "justification": plb.get("justification", "").strip(),
            "citations": plb.get("citations", []),
            "source": {
                "archive": (profile.get("sourced_from", {})
                            .get("archive", "Internet_Archive")),
                "archive_identifier": ia_id,
                "source_url": src_url,
                "source_media_url": src_media_url,
                "source_media_sha256": src_sha,
                "obtained_at": obtained_at,
                "segment_start_s": seg_start,
                "segment_duration_s": seg_dur,
            },
        },
    )
    return v


def run_chain(vid: str, work: Path):
    """Run the config.yml `publicvcons` chain link modules in order."""
    os.environ["PVCONS_VCON_STORE"] = str(work)
    os.environ["PVCONS_FORCE_FILE_STORE"] = "1"
    import importlib
    for name in CHAIN:
        mod = importlib.import_module(f"links.{name}")
        logger.info("== link: %s ==", name)
        result = mod.run(vid, name, getattr(mod, "default_options", {}))
        if result is None:
            raise SystemExit(f"chain halted at link '{name}' "
                             f"(lawful-basis hard rule or filter)")


SCITT_CLI = (HERE.parent / "scitt" / "cli" / "pvcons_scitt.py")


def sign_scitt(vcon_path: Path, lb_path: Path, scitt_dir: Path,
               scitt_url: str | None = None):
    scitt_dir.mkdir(parents=True, exist_ok=True)
    for old in scitt_dir.glob("*.json"):
        old.unlink()
    subprocess.run([TOOLS_PY, str(SCITT), "keygen"],
                   check=True, capture_output=True)
    for i, stage in enumerate(BACKFILL_STAGES, 1):
        subprocess.run([
            TOOLS_PY, str(SCITT), "sign",
            "--vcon", str(vcon_path), "--lawful-basis", str(lb_path),
            "--stage", stage, "--receipts", str(scitt_dir),
            "--seq", str(i),
        ], check=True, capture_output=True)
    r = subprocess.run([TOOLS_PY, str(SCITT), "verify",
                        "--receipts", str(scitt_dir)],
                       check=True, capture_output=True, text=True)
    logger.info("SCITT: %d stages signed (statement sigs verified)",
                r.stdout.count("OK "))

    # Anchor each statement in the transparency service and store its
    # inclusion-proof receipt next to the statement.
    if scitt_url:
        try:
            import httpx
            httpx.get(f"{scitt_url}/", timeout=5).raise_for_status()
        except Exception as e:
            raise SystemExit(
                f"SCITT service unreachable at {scitt_url}: {e}. "
                f"Start it (see scitt/runbooks) or omit --scitt-url.")
        n = 0
        for st in sorted(scitt_dir.glob("*.scitt.json")):
            rc = st.with_name(
                st.name.replace(".scitt.json", ".scitt-receipt.json"))
            subprocess.run([
                TOOLS_PY, str(SCITT_CLI), "register",
                "--statement", str(st), "--out", str(rc),
                "--url", scitt_url,
            ], check=True, capture_output=True)
            n += 1
        v = subprocess.run([TOOLS_PY, str(SCITT_CLI), "verify",
                            "--receipts", str(scitt_dir)],
                           check=True, capture_output=True, text=True)
        logger.info("SCITT: %d statements anchored, %d receipts "
                    "verified", n, v.stdout.count("OK "))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True,
                    help="source profile id (sources/<id>.yaml)")
    ap.add_argument("--archive-id", help="Internet Archive item id")
    ap.add_argument("--ia-file", help="exact file within a multi-file "
                    "IA item (e.g. 11-03301.mp3)")
    ap.add_argument("--youtube-url", help="YouTube watch URL")
    ap.add_argument("--recording-date", required=True,
                    help="YYYY-MM-DD")
    ap.add_argument("--segment-start", type=float, default=0.0)
    ap.add_argument("--segment-dur", type=float, required=True)
    ap.add_argument("--subject", default=None)
    ap.add_argument("--reuse-work",
                    help="existing work dir with cached intermediates")
    ap.add_argument("--scitt", action="store_true",
                    help="sign the SCITT lifecycle chain")
    ap.add_argument("--scitt-url", default=os.environ.get(
        "PVCONS_SCITT_URL"),
        help="transparency service to anchor statements in "
             "(e.g. http://127.0.0.1:8000); also stores receipts")
    args = ap.parse_args()

    profile = load_source_profile(args.source)
    if profile.get("status") not in (None, "active"):
        raise SystemExit(f"source '{args.source}' status="
                         f"{profile.get('status')} (not active)")

    vid = str(uuidlib.uuid4())
    rec = args.recording_date.replace("-", "/")
    media_dir = MEDIA_ROOT / args.source / rec
    data_dir = DATA_ROOT / rec / args.source / vid
    work = (Path(args.reuse_work) if args.reuse_work
            else WORK_ROOT / vid)
    work.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "scitt").mkdir(exist_ok=True)
    obtained_at = now_iso()

    # ---- ingress: acquire ----
    if args.archive_id:
        src_mp4 = acquire_internet_archive(args.archive_id, media_dir,
                                           args.ia_file)
        src_url = f"https://archive.org/details/{args.archive_id}"
        from urllib.parse import quote as _q
        src_media_url = (
            f"https://archive.org/download/{args.archive_id}/"
            f"{_q(args.ia_file) if args.ia_file else args.archive_id + '_512kb.mp4'}")
        ia_id = args.archive_id
    elif args.youtube_url:
        ia_id = args.youtube_url.rsplit("=", 1)[-1]
        src_mp4 = acquire_youtube(args.youtube_url, media_dir, ia_id)
        src_url = src_media_url = args.youtube_url
    else:
        raise SystemExit("need --archive-id or --youtube-url")

    src_sha = sha256_file(src_mp4)
    (data_dir / "source_media.sha256").write_text(
        f"{src_sha}  {src_mp4.name}\n")

    # ---- ingress: normalize + initial vCon ----
    wav = normalize_segment(src_mp4, work, args.segment_start,
                            args.segment_dur)
    subject = args.subject or profile.get("name", args.source)
    v = build_initial_vcon(
        vid, subject, args.recording_date, src_url, src_media_url,
        src_sha, ia_id, wav, args.segment_start, args.segment_dur,
        profile, obtained_at)
    (work / f"{vid}.vcon.json").write_text(v.to_json())
    logger.info("ingress vCon %s built (lawful_basis at ingress)", vid)

    # ---- chain ----
    run_chain(vid, work)

    # ---- egress: finalize to corpus ----
    from vcon import Vcon
    final = Vcon.load_from_file(str(work / f"{vid}.vcon.json"))
    ok, errs = final.is_valid()
    if not ok:
        raise SystemExit(f"final vcon invalid: {errs}")
    lb = next(a for a in final.vcon_dict["attachments"]
              if a.get("purpose") == "lawful_basis")["body"]
    vcon_path = data_dir / "vcon.json"
    lb_path = data_dir / "lawful_basis.json"
    vcon_path.write_text(final.to_json())
    lb_path.write_text(json.dumps(lb, indent=2))

    if args.scitt:
        sign_scitt(vcon_path, lb_path, data_dir / "scitt",
                   args.scitt_url)

    print(json.dumps({
        "uuid": vid,
        "vcon": vcon_path.parts and str(vcon_path),
        "data_dir": str(data_dir),
        "parties": len(final.vcon_dict.get("parties", [])),
        "analysis": [a["type"] for a in
                     final.vcon_dict.get("analysis", [])],
        "lawful_basis": lb.get("lawful_basis"),
        "scitt_signed": bool(args.scitt),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
