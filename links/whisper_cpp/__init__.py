"""Link: transcribe with whisper.cpp large-v3 (local, no paid API).

vcon-server ships a `transcribe` (whisper) link, but PublicVCons must
use whisper.cpp large-v3 locally with no cloud API (PROTOTYPE_PLAN.md
hard rule), so this is a project link.

Reads the normalized 16 kHz WAV path from dialog[di].meta.local_wav,
runs the tested pipeline/transcribe via whisper-cli, and stashes the
raw whisper JSON path in dialog meta for the diarize link to consume.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _base import init_logger, get_store  # noqa: E402

logger = init_logger("pvcons.whisper_cpp")

default_options = {
    "whisper_cli": os.path.expanduser(
        "~/Code/whisper.cpp/build/bin/whisper-cli"),
    "model": "/Volumes/publicvcons/models/whisper-cpp/ggml-large-v3.bin",
    "language": "en",
    "threads": 8,
    "dialog_index": 0,
}


def run(vcon_uuid, link_name, opts=default_options):
    o = {**default_options, **(opts or {})}
    store = get_store()
    v = store.get_vcon(vcon_uuid)
    di = o["dialog_index"]
    dialog = v.vcon_dict["dialog"][di]
    meta = dialog.get("meta", {})
    wav = meta.get("local_wav")
    if not wav or not Path(wav).is_file():
        raise RuntimeError(
            f"whisper_cpp: dialog[{di}].meta.local_wav missing/not found: "
            f"{wav}")

    work = Path(wav).parent
    out_base = work / "transcript"
    tj = out_base.with_suffix(".json")
    if tj.is_file() and tj.stat().st_size > 0:
        logger.info("transcript.json present, skipping whisper (resume)")
    else:
        logger.info("whisper.cpp large-v3 -> %s", out_base)
        subprocess.run([
            o["whisper_cli"], "-m", o["model"], "-f", wav,
            "-l", o["language"], "-t", str(o["threads"]), "-p", "1",
            "-oj", "-of", str(out_base),
        ], check=True, capture_output=True)
    if not tj.is_file():
        raise RuntimeError("whisper_cpp: no transcript.json produced")
    nseg = len(json.loads(tj.read_text()).get("transcription", []))
    meta["whisper_json"] = str(tj)
    meta["whisper_segments"] = nseg
    dialog["meta"] = meta
    store.store_vcon(v)
    logger.info("transcribed %d raw segments", nseg)
    return vcon_uuid
