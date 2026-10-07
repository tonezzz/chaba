#!/usr/bin/env python3
"""yt-diarize.py — pyannote speaker-diarization -> turn file for
yt-vtt-dub.py --diarize-file.

Runs on tony-omen (GPU):  ~/.venvs/diarize/bin/python yt-diarize.py \
    media.mp4 out.diarize.txt [--rttm out.rttm] [--num-speakers N]

Output formats:
  default: 'start end SPEAKER_NN' lines (the v17 format)
  --rttm : standard RTTM alongside

Any media ffmpeg can decode works — audio is extracted to 16kHz mono wav
first. SPEAKER_NN labels are clustering ids, not identities; name them
with yt-vtt-dub.py --anchors (transcript-anchor method). Micro-turn
filtering is left to the renderer (--min-turn 0.3) so the raw table is
preserved.

Auth: pyannote models are gated — needs HF_TOKEN env or a cached
~/.cache/huggingface/token on the diarize host (tony-omen has both the
token and the model cache already).
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def hf_token():
    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if tok:
        return tok
    f = Path.home() / ".cache/huggingface/token"
    return f.read_text().strip() if f.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media", help="audio/video file ffmpeg can decode")
    ap.add_argument("out", help="'start end SPEAKER_NN' turn file")
    ap.add_argument("--rttm", default="", help="also write standard RTTM")
    ap.add_argument("--num-speakers", type=int, default=0,
                    help="speaker count hint (0 = let pyannote decide)")
    ap.add_argument("--model", default="pyannote/speaker-diarization-3.1")
    a = ap.parse_args()

    from pyannote.audio import Pipeline
    import torch

    pipe = Pipeline.from_pretrained(a.model, token=hf_token())
    if torch.cuda.is_available():
        pipe.to(torch.device("cuda"))

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "in.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", a.media,
             "-vn", "-ac", "1", "-ar", "16000", str(wav)],
            check=True)
        kw = {"num_speakers": a.num_speakers} if a.num_speakers else {}
        out = pipe(str(wav), **kw)

    # pyannote 4.x returns DiarizeOutput (.speaker_diarization); 3.x
    # returns the Annotation directly
    ann = getattr(out, "speaker_diarization", out)
    rows = sorted((seg.start, seg.end, lab)
                  for seg, _, lab in ann.itertracks(yield_label=True))
    stem = Path(a.media).stem
    with open(a.out, "w", encoding="utf-8") as f:
        for s, e, lab in rows:
            f.write(f"{s:.3f} {e:.3f} {lab}\n")
    if a.rttm:
        with open(a.rttm, "w", encoding="utf-8") as f:
            for s, e, lab in rows:
                f.write(f"SPEAKER {stem} 1 {s:.3f} {e - s:.3f} "
                        f"<NA> <NA> {lab} <NA> <NA>\n")
    n_spk = len({lab for _, _, lab in rows})
    print(f"{len(rows)} raw turns, {n_spk} speakers -> {a.out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
