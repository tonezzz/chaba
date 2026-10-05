#!/usr/bin/env python3
"""yt-cast-detect.py — heuristic speaker-turn detection on a karaoke VTT.

Thin CLI over the detection code in the sibling yt-vtt-dub.py: cue-gap
clustering (Otsu split of inter-group gaps) + question-cue heuristics,
N-speaker round-robin (default 2 -> alternation for interview/talk videos).
YouTube auto-captions carry no speaker labels; this is the cheap first pass
before paying for real diarization (resemblyzer/pyannote).

Usage:
  yt-cast-detect.py <karaoke.en.vtt> [--secs 300] [--offset 20]
                    [--speakers 2] [--detect-gap 0.6] [--voices V1,V2]
                    [--format turns|cast-times|json] [--dump-turns file]

Pipe the cast-times output straight into the dub:
  yt-vtt-dub.py src.mp4 merged.vtt out.mp4 --sentences \
      --en-vtt karaoke.en.vtt --offset 20 --secs 180 \
      --cast-times "$(yt-cast-detect.py karaoke.en.vtt --secs 180 \
                    --offset 20 --format cast-times)"
or just use yt-vtt-dub.py's own --cast-detect flag (same code, in-process).
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path


def _load_dub():
    here = Path(__file__).resolve().parent
    for p in (here / "yt-vtt-dub.py",
              Path.home() / ".local/bin/yt-vtt-dub.py"):
        if p.exists():
            spec = importlib.util.spec_from_file_location("yt_vtt_dub", p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    sys.exit("yt-vtt-dub.py not found next to this script or in ~/.local/bin")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vtt", help="karaoke VTT with <c> word timestamps")
    ap.add_argument("--secs", type=float, default=1e9)
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--speakers", type=int, default=2)
    ap.add_argument("--detect-gap", type=float, default=0.6)
    ap.add_argument("--voices",
                    default="th-TH-NiwatNeural,th-TH-PremwadeeNeural",
                    help="comma voices in speaker order (only 2 TH voices "
                         "exist in edge-tts — extras cycle)")
    ap.add_argument("--format", choices=["turns", "cast-times", "json"],
                    default="turns")
    ap.add_argument("--dump-turns", default="")
    a = ap.parse_args()

    dub = _load_dub()
    words = dub.parse_words(a.vtt, a.secs, offset=a.offset)
    if not words:
        sys.exit("no words parsed — is this a karaoke VTT with <c> tags?")
    turns, dbg = dub.detect_turns(words, speakers=a.speakers,
                                  detect_gap=a.detect_gap)
    voices = [v.strip() for v in a.voices.split(",")]
    stats = dub.turn_summary(turns)
    host = max(stats, key=lambda s: stats[s]["q"], default=None)

    n_bounds = sum(1 for b in dbg["boundaries"] if b["boundary"])
    print(f"{len(words)} words, {len(turns)} turns over {a.speakers} "
          f"speakers ({n_bounds} boundaries, t_long={dbg['t_long']})",
          file=sys.stderr)
    for spk in sorted(stats):
        st = stats[spk]
        tag = " <- host?" if spk == host and st["q"] else ""
        print(f"  S{spk} {voices[spk % len(voices)]}: {st['turns']} turns, "
              f"{st['air']:.0f}s air, {st['q']} questions{tag}",
              file=sys.stderr)

    if a.dump_turns:
        json.dump({"t_long": dbg["t_long"], "voices": voices,
                   "turns": [
                       {"spk": spk, "s": round(s, 2), "e": round(e, 2),
                        "text": " ".join(dub._grp_text(g) for g in gs)[:160]}
                       for s, e, spk, gs in turns],
                   "boundaries": dbg["boundaries"]},
                  open(a.dump_turns, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"dumped turns -> {a.dump_turns}", file=sys.stderr)

    if a.format == "cast-times":
        print(dub.turns_to_cast_times(turns, voices))
    elif a.format == "json":
        json.dump({"t_long": dbg["t_long"], "voices": voices,
                   "turns": [{"spk": spk, "s": s, "e": e,
                              "text": " ".join(dub._grp_text(g) for g in gs)}
                             for s, e, spk, gs in turns]},
                  sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:  # turns table
        for s, e, spk, gs in turns:
            text = " ".join(dub._grp_text(g) for g in gs)
            print(f"{s:8.2f}-{e:8.2f}  S{spk}  {text[:90]}")


if __name__ == "__main__":
    main()
