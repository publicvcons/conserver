#!/usr/bin/env python3
"""Speaker diarization with pyannote.audio 3.x.

Input:  a 16 kHz mono WAV.
Output: JSON list of speaker turns [{start, end, speaker}], anonymous
        speaker labels (SPEAKER_00, SPEAKER_01, ...).

Run inside the pvcons venv with HUGGING_FACE_HUB_TOKEN set.
"""
import argparse
import json
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-speakers", type=int, default=None)
    ap.add_argument("--max-speakers", type=int, default=None)
    args = ap.parse_args()

    token = os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        print("HUGGING_FACE_HUB_TOKEN not set", file=sys.stderr)
        return 2

    import torch

    # pyannote 3.x checkpoints predate PyTorch 2.6's weights_only=True
    # default and store non-tensor globals (TorchVersion, omegaconf, etc.).
    # The model is the official pyannote/speaker-diarization-3.1 checkpoint
    # fetched over an authenticated, gated HF repo, so it is trusted here.
    _orig_load = torch.load

    def _trusting_load(*a, **kw):
        kw["weights_only"] = False
        return _orig_load(*a, **kw)

    torch.load = _trusting_load

    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", use_auth_token=token
    )
    if torch.backends.mps.is_available():
        pipeline.to(torch.device("mps"))

    kw = {}
    if args.min_speakers is not None:
        kw["min_speakers"] = args.min_speakers
    if args.max_speakers is not None:
        kw["max_speakers"] = args.max_speakers

    diarization = pipeline(args.wav, **kw)

    turns = [
        {"start": round(seg.start, 3), "end": round(seg.end, 3), "speaker": label}
        for seg, _, label in diarization.itertracks(yield_label=True)
    ]
    with open(args.out, "w") as f:
        json.dump({"turns": turns}, f, indent=2)
    print(f"wrote {len(turns)} turns -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
