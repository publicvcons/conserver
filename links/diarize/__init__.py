"""Link: pyannote diarization + merge into a speaker transcript.

Runs pipeline/diarize.py (pyannote.audio 3.1, pvcons venv) on the WAV,
merges speaker turns onto the whisper transcript with pipeline/merge.py
(applying the source-segment offset), and writes the result as a
`transcript` analysis on the vCon via the upstream vcon library.

No upstream equivalent — pyannote diarization is project-specific.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _base import init_logger, get_store, pvcons_env  # noqa: E402

logger = init_logger("pvcons.diarize")
PIPELINE = Path(__file__).resolve().parents[2] / "pipeline"

default_options = {
    "pvcons_python": os.path.expanduser("~/venvs/pvcons/bin/python"),
    "tools_python": os.path.expanduser("~/venvs/tools/bin/python"),
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
    whisper_json = meta.get("whisper_json")
    if not (wav and whisper_json and Path(whisper_json).is_file()):
        raise RuntimeError("diarize: needs meta.local_wav and "
                           "meta.whisper_json (run whisper_cpp first)")

    work = Path(wav).parent
    dz = work / "diarization.json"
    merged = work / "transcript_merged.json"
    offset = float(meta.get("source_segment_start_s", 0.0))

    if dz.is_file() and dz.stat().st_size > 0:
        logger.info("diarization.json present, skipping pyannote (resume)")
    else:
        logger.info("pyannote diarization")
        subprocess.run([
            o["pvcons_python"], str(PIPELINE / "diarize.py"),
            "--wav", wav, "--out", str(dz),
        ], check=True, capture_output=True,
           env={**os.environ, **pvcons_env()})

    logger.info("merge transcript+diarization (offset %.1fs)", offset)
    subprocess.run([
        o["tools_python"], str(PIPELINE / "merge.py"),
        "--whisper-json", whisper_json, "--diarization-json", str(dz),
        "--offset", str(offset), "--out", str(merged),
    ], check=True, capture_output=True)

    body = json.loads(merged.read_text())

    # Speakers are discovered here, so this link is the single place
    # parties are created. Anonymous until a later identification step.
    if not v.vcon_dict.get("parties"):
        from vcon.party import Party
        for i, sp in enumerate(body["speakers"]):
            v.add_party(Party(
                name=f"Speaker {i + 1}",
                role="speaker",
                meta={"diarization_label": sp, "identified": False},
            ))

    v.add_analysis(
        type="transcript",
        dialog=di,
        vendor="publicvcons",
        product="whisper.cpp large-v3 + pyannote.audio 3.1",
        encoding="json",
        body={"speakers": body["speakers"],
              "segments": body["segments"]},
    )
    store.store_vcon(v)
    logger.info("transcript analysis: %d speakers, %d segments",
                len(body["speakers"]), len(body["segments"]))
    return vcon_uuid
