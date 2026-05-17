#!/usr/bin/env python3
"""Local-LLM analysis of a speaker-attributed transcript via Ollama.

No paid APIs. Talks to a local Ollama server (default llama3.1:8b q4).

Output JSON:
  { summary, topics[], entities{people[],orgs[],laws[],places[]},
    bill_references[], vote_references[], neutral_editorial_summary }

Long transcripts are map-reduced: chunk -> per-chunk notes -> final
synthesis, so this stays within an 8B model's context window.
"""
import argparse
import json
import re
import sys
import urllib.request

OLLAMA = "http://127.0.0.1:11434/api/generate"


def gen(model, prompt, temperature=0.2, num_ctx=8192):
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }).encode()
    req = urllib.request.Request(
        OLLAMA, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())["response"].strip()


def chunk_words(text, size=2200):
    words = text.split()
    for i in range(0, len(words), size):
        yield " ".join(words[i:i + size])


def extract_json(s):
    # tolerate models that wrap JSON in prose or code fences
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        raise ValueError(f"no JSON object in model output: {s[:200]}")
    return json.loads(m.group(0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript-json", required=True)
    ap.add_argument("--model", default="llama3.1:8b-instruct-q4_K_M")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.transcript_json) as f:
        tj = json.load(f)
    plain = "\n".join(
        f'{s["speaker"]}: {s["text"]}' for s in tj["segments"]
    )

    chunks = list(chunk_words(plain))
    notes = []
    for i, c in enumerate(chunks):
        print(f"summarizing chunk {i+1}/{len(chunks)}", file=sys.stderr)
        notes.append(gen(args.model,
            "You are a neutral analyst of US government proceedings. "
            "Summarize the key points, decisions, named people, "
            "organizations, laws/bills, and any votes in this transcript "
            f"excerpt. Be factual and concise.\n\n---\n{c}\n---"))

    combined = "\n\n".join(notes)
    schema = (
        '{"summary": str, "topics": [str], '
        '"entities": {"people": [str], "orgs": [str], "laws": [str], '
        '"places": [str]}, "bill_references": [str], '
        '"vote_references": [str], "neutral_editorial_summary": str}'
    )
    final = gen(args.model,
        "Synthesize the notes below into a single JSON object with EXACTLY "
        f"this schema:\n{schema}\n\n"
        "Rules: output ONLY the JSON object, no prose. 'summary' is 3-6 "
        "sentences. 'neutral_editorial_summary' is 2-3 sentences, strictly "
        "neutral, no opinion. Use [] or \"\" when a field is unknown.\n\n"
        f"NOTES:\n{combined}", temperature=0.1)

    data = extract_json(final)
    data.setdefault("entities", {})
    for k in ("people", "orgs", "laws", "places"):
        data["entities"].setdefault(k, [])
    for k in ("topics", "bill_references", "vote_references"):
        data.setdefault(k, [])
    data["_model"] = args.model
    data["_chunks"] = len(chunks)

    with open(args.out, "w") as f:
        json.dump(data, f, indent=2)
    print(f"wrote analysis -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
