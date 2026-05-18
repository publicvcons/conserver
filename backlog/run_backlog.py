#!/usr/bin/env python3
"""Run the historical priority backlog (PROTOTYPE_PLAN.md §3.5, Phase 4).

Iterates priority10.yaml and runs orchestrate.py on every `status:
ready` item that is not already in the corpus. Idempotent and
resumable: an item is "done" when a vcon whose
lawful_basis.metadata.source.archive_identifier (+ ia_file) matches is
already committed, so re-runs and a daily cron only pick up what's
missing — exactly the Phase 4 "one new historical vcon per day" cadence.

  run_backlog.py --list
  run_backlog.py --corpus seed/vcons [--limit 1] [--scitt-url URL]
  run_backlog.py --only iran_contra_19870708 --corpus seed/vcons
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CONSERVER = HERE.parent
ORCH = CONSERVER / "orchestrate.py"
MANIFEST = HERE / "priority10.yaml"
PY = sys.executable


def corpus_sources(corpus: Path) -> set:
    """archive_identifier[:ia_file] already present in the corpus."""
    seen = set()
    for vp in corpus.rglob("vcon.json"):
        try:
            v = json.loads(vp.read_text())
            for a in v.get("attachments", []):
                if a.get("purpose") == "lawful_basis":
                    s = (a.get("body", {}).get("metadata", {})
                         .get("source", {}))
                    aid = s.get("archive_identifier")
                    if aid:
                        seen.add(aid)
        except Exception:
            continue
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(CONSERVER.parent / "vcons"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", help="run just this backlog item id")
    ap.add_argument("--limit", type=int, default=0,
                    help="max items to process this run (0 = all ready)")
    ap.add_argument("--scitt-url",
                    help="anchor in the SCITT service (passed through)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    items = yaml.safe_load(MANIFEST.read_text())["items"]
    corpus = Path(a.corpus).resolve()
    done = corpus_sources(corpus)

    if a.list:
        for it in items:
            mark = ("DONE" if it.get("archive_id") in done
                    else it["status"].upper())
            print(f"  [{mark:>12}] p{it['plan_priority']:<2} "
                  f"{it['id']}  — {it['title']}")
        ready = [i for i in items if i["status"] == "ready"]
        print(f"\n{len(items)} items · "
              f"{sum(1 for i in items if i['status']=='ready')} ready · "
              f"{sum(1 for i in items if i.get('archive_id') in done)} "
              f"in corpus · "
              f"{sum(1 for i in items if i['status']=='needs_source')} "
              f"need a verified source")
        return 0

    todo = [it for it in items if it["status"] == "ready"
            and it.get("archive_id") not in done
            and (not a.only or it["id"] == a.only)]
    if a.limit:
        todo = todo[:a.limit]
    if not todo:
        print("nothing to do (all ready items already in corpus)")
        return 0

    rc = 0
    for it in todo:
        cmd = [PY, str(ORCH),
               "--source", it["source"],
               "--archive-id", it["archive_id"],
               "--recording-date", it["recording_date"],
               "--segment-start", str(it.get("segment_start", 0)),
               "--segment-dur", str(it["segment_dur"]),
               "--subject", it["subject"], "--scitt"]
        if it.get("ia_file"):
            cmd += ["--ia-file", it["ia_file"]]
        if a.scitt_url:
            cmd += ["--scitt-url", a.scitt_url]
        print(f"\n=== backlog: {it['id']} (p{it['plan_priority']}) ===")
        print("  " + " ".join(cmd))
        if a.dry_run:
            continue
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print(f"  FAILED {it['id']} rc={r.returncode} "
                  f"(left for next run)")
            rc = 1
        else:
            print(f"  OK {it['id']}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
