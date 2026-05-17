"""Link: local-LLM analysis via Ollama (no paid API).

vcon-server's `analyze` link uses OpenAI; PublicVCons must run analysis
locally (PROTOTYPE_PLAN.md hard rule), so this link drives
pipeline/analyze.py against a local Ollama model and attaches the
result as a `summary` analysis.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _base import init_logger, get_store  # noqa: E402

logger = init_logger("pvcons.analyze_local")
PIPELINE = Path(__file__).resolve().parents[2] / "pipeline"

default_options = {
    "tools_python": os.path.expanduser("~/venvs/tools/bin/python"),
    "model": "llama3.1:8b-instruct-q4_K_M",
    "ollama_models": "/Volumes/publicvcons/models/ollama",
    "dialog_index": 0,
}


def run(vcon_uuid, link_name, opts=default_options):
    o = {**default_options, **(opts or {})}
    store = get_store()
    v = store.get_vcon(vcon_uuid)
    di = o["dialog_index"]

    tr = next((a for a in v.vcon_dict.get("analysis", [])
               if a.get("type") == "transcript"), None)
    if not tr:
        raise RuntimeError("analyze_local: no transcript analysis "
                           "(run diarize first)")

    with tempfile.TemporaryDirectory() as td:
        tin = Path(td) / "transcript_merged.json"
        tout = Path(td) / "analysis.json"
        tin.write_text(json.dumps(tr["body"]))
        env = {**os.environ,
               "OLLAMA_MODELS": o["ollama_models"]}
        logger.info("local analysis via Ollama %s", o["model"])
        subprocess.run([
            o["tools_python"], str(PIPELINE / "analyze.py"),
            "--transcript-json", str(tin),
            "--model", o["model"],
            "--out", str(tout),
        ], check=True, capture_output=True, env=env)
        aj = json.loads(tout.read_text())

    v.add_analysis(
        type="summary",
        dialog=di,
        vendor="publicvcons",
        product=aj.get("_model", o["model"]),
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
    store.store_vcon(v)
    logger.info("summary analysis attached")
    return vcon_uuid
