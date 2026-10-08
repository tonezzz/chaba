#!/usr/bin/env python3
"""batch-transcribe — offline CPU ASR via moondream/parakeet-redux (Photon).

Batch-only tool: NOT for the live voice path (that stays on Gemini Live).
Model covers 25 European languages — no Thai. Thai input yields garbage
European-looking text; filter upstream if the lane is mixed-language.

Usage:
    batch-transcribe a.wav b.m4a > out.json        # one JSON object per file
    batch-transcribe file.wav                      # single object
    cat file.wav | batch-transcribe                # stdin -> single object
    batch-transcribe --timestamps segment x.wav    # no word_ts

Output: JSON {"text", "word_ts": [{"word","start","end"}], "segments": [...],
"duration_seconds", "infer_seconds", "rt_factor", "model", "file"}.
Multiple inputs -> a JSON array; per-file failures become {"file","error"}.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

MODEL = "moondream/parakeet-redux"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "inputs",
        nargs="*",
        help="audio files (wav/flac/mp3/m4a/ogg); '-' or empty reads stdin",
    )
    ap.add_argument(
        "--timestamps",
        default="word",
        choices=["none", "segment", "word", "character"],
    )
    ap.add_argument("--cpu-threads", type=int, default=None)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--task", default="transcribe", choices=["transcribe", "translate"])
    args = ap.parse_args()

    inputs = args.inputs or ["-"]
    jobs: list[tuple[str, object]] = []
    for item in inputs:
        if item == "-":
            data = sys.stdin.buffer.read()
            if not data:
                print("batch-transcribe: empty stdin", file=sys.stderr)
                return 2
            jobs.append(("stdin", data))
        else:
            jobs.append((item, item))

    import moondream as md

    cfg: dict = {"device": "cpu"}
    if args.cpu_threads:
        cfg["cpu_threads"] = args.cpu_threads

    out = []
    with md.photon(args.model, **cfg) as speech:
        for name, audio in jobs:
            try:
                t0 = time.time()
                r = speech.transcribe(
                    audio=audio, timestamps=args.timestamps, task=args.task
                )
                infer = time.time() - t0
                words = [
                    w
                    for seg in r.get("segments", [])
                    for w in seg.get("words", [])
                ]
                dur = r["duration_seconds"]
                out.append(
                    {
                        "file": name,
                        "text": r["text"],
                        "language": r.get("language"),
                        "duration_seconds": dur,
                        "infer_seconds": round(infer, 3),
                        "rt_factor": round(dur / infer, 2) if infer else None,
                        "segments": r.get("segments", []),
                        "word_ts": words,
                        "model": args.model,
                    }
                )
            except Exception as e:  # keep batch going on bad input
                out.append({"file": name, "error": f"{type(e).__name__}: {e}"})

    json.dump(out[0] if len(out) == 1 else out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
