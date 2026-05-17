#!/usr/bin/env python3
"""Merge a whisper.cpp JSON transcript with pyannote diarization turns.

Produces a speaker-attributed transcript: a list of segments with
{start, end, speaker, text}, where speaker is the anonymous diarizer
label whose turn most overlaps each transcript segment.

whisper.cpp `-oj` schema: top-level `transcription` is a list of
{ offsets: {from, to} (milliseconds), text }.
"""
import argparse
import json


def seg_bounds(seg):
    off = seg.get("offsets") or {}
    return off.get("from", 0) / 1000.0, off.get("to", 0) / 1000.0


def best_speaker(s, e, turns):
    mid = (s + e) / 2.0
    best, best_ov = None, 0.0
    for t in turns:
        ov = max(0.0, min(e, t["end"]) - max(s, t["start"]))
        if ov > best_ov:
            best, best_ov = t["speaker"], ov
    if best is not None:
        return best
    # no overlap: nearest turn by midpoint distance
    nearest = min(
        turns,
        key=lambda t: abs(mid - (t["start"] + t["end"]) / 2.0),
        default=None,
    )
    return nearest["speaker"] if nearest else "SPEAKER_00"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--whisper-json", required=True)
    ap.add_argument("--diarization-json", required=True)
    ap.add_argument("--offset", type=float, default=0.0,
                    help="seconds to add to transcript times (segment offset "
                         "into the original source media)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.whisper_json) as f:
        wj = json.load(f)
    with open(args.diarization_json) as f:
        turns = json.load(f)["turns"]

    segments = []
    for seg in wj.get("transcription", []):
        s, e = seg_bounds(seg)
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        spk = best_speaker(s, e, turns)
        segments.append({
            "start": round(s + args.offset, 3),
            "end": round(e + args.offset, 3),
            "speaker": spk,
            "text": text,
        })

    speakers = sorted({s["speaker"] for s in segments})
    out = {"speakers": speakers, "segments": segments}
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"merged {len(segments)} segments, {len(speakers)} speakers "
          f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
