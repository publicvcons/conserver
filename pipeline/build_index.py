#!/usr/bin/env python3
"""Build the corpus index.json the web viewer's home feed reads.

Walks a vcons corpus (default the publicvcons/vcons checkout) and emits
a flat manifest plus collections. Collections are expressed as queries
over the flat repo (PROTOTYPE_PLAN.md §12 option B): by source and by
year, derived — no curation coupled to storage layout.

  build_index.py --corpus seed/vcons --out seed/vcons/index.json
"""
import argparse
import json
from pathlib import Path


def entry(vp: Path, corpus: Path) -> dict:
    v = json.loads(vp.read_text())
    rel = vp.parent.relative_to(corpus).as_posix()
    # path: YYYY/MM/DD/source/uuid
    parts = rel.split("/")
    source = parts[3] if len(parts) >= 5 else "unknown"
    year = parts[0] if parts else ""
    analysis = v.get("analysis", [])
    summ = next((a for a in analysis if a.get("type") == "summary"), {})
    tr = next((a for a in analysis if a.get("type") == "transcript"), {})
    sb = summ.get("body", {}) if isinstance(summ, dict) else {}
    scitt = vp.parent / "scitt"
    return {
        "uuid": v.get("uuid"),
        "path": rel,
        "subject": v.get("subject", ""),
        "created_at": v.get("created_at", ""),
        "source": source,
        "year": year,
        "parties": len(v.get("parties", [])),
        "segments": len(tr.get("body", {}).get("segments", []))
        if isinstance(tr, dict) else 0,
        "topics": sb.get("topics", []),
        "neutral_editorial_summary":
            sb.get("neutral_editorial_summary", ""),
        "lawful_basis": next(
            (a["body"].get("lawful_basis")
             for a in v.get("attachments", [])
             if a.get("purpose") == "lawful_basis"), None),
        "has_receipts": scitt.is_dir() and any(
            scitt.glob("*.scitt-receipt.json")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    corpus = Path(a.corpus).resolve()

    vcons = []
    for vp in sorted(corpus.rglob("vcon.json")):
        try:
            vcons.append(entry(vp, corpus))
        except Exception as e:
            print(f"skip {vp}: {e}")
    vcons.sort(key=lambda e: e["created_at"], reverse=True)

    def collect(key):
        out = {}
        for e in vcons:
            out.setdefault(e[key], []).append(e["uuid"])
        return out

    index = {
        "generated_from": str(corpus.name),
        "count": len(vcons),
        "vcons": vcons,
        "collections": {
            "by_source": collect("source"),
            "by_year": collect("year"),
        },
    }
    Path(a.out).write_text(json.dumps(index, indent=2))
    print(f"indexed {len(vcons)} vcon(s) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
