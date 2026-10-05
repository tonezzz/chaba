#!/usr/bin/env python3
"""yt-whisper-vtt.py — Whisper transcription lane for caption-less videos.

Transcribes audio with faster-whisper word timestamps and writes a VTT in
YouTube karaoke form (<c>word</c> tags) so the file feeds yt-vtt-dub.py
parse_words / --sentences / --cast-detect unchanged. Use for videos that
ship no captions at all (e.g. sNh4pVMFhvQ, Sweden 1994).

One-time setup:
  python3 -m venv ~/.venvs/whisper
  ~/.venvs/whisper/bin/pip install faster-whisper
First run downloads the model to ~/.cache/huggingface (small ~460 MB,
base ~145 MB, tiny ~75 MB). CPU works; set WHISPER_DEVICE=cuda if a GPU
build of ctranslate2 is installed.

Usage: yt-whisper-vtt.py <media> <out.vtt> [--model small] [--lang sv]
Then:  yt-vtt-translate.py out.vtt merged.vtt --langs en,th   (if src!=en)
       yt-vtt-dub.py media merged.vtt dub.mp4 --sentences \\
           --en-vtt out.vtt --cast-detect
"""
import argparse
import os
import sys
from pathlib import Path

WHISPER_PY = os.environ.get("WHISPER_PY",
                            str(Path.home() / ".venvs/whisper/bin/python"))


def _ensure_fw():
    try:
        import faster_whisper  # noqa: F401
        return
    except ImportError:
        pass
    if Path(sys.executable).resolve() == Path(WHISPER_PY).resolve():
        sys.exit("faster-whisper not installed in " + WHISPER_PY +
                 " — see docstring setup")
    if not Path(WHISPER_PY).exists():
        sys.exit("whisper venv missing: " + WHISPER_PY +
                 " — see docstring setup")
    os.execv(WHISPER_PY, [WHISPER_PY, str(Path(__file__).resolve())]
             + sys.argv[1:])


_ensure_fw()
from faster_whisper import WhisperModel  # noqa: E402


def _ts(x):
    h = int(x // 3600)
    m = int((x % 3600) // 60)
    return f"{h:02d}:{m:02d}:{x % 60:06.3f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("out")
    ap.add_argument("--model", default="small",
                    help="faster-whisper model size (tiny/base/small/...)")
    ap.add_argument("--lang", default=None,
                    help="source language code (default: auto-detect)")
    ap.add_argument("--cue-secs", type=float, default=5.0,
                    help="max cue duration — YT karaoke runs ~4-6s cues")
    a = ap.parse_args()

    model = WhisperModel(
        a.model,
        device=os.environ.get("WHISPER_DEVICE", "cpu"),
        compute_type=os.environ.get("WHISPER_COMPUTE", "int8"))
    segments, info = model.transcribe(
        a.media, language=a.lang, word_timestamps=True,
        vad_filter=True)
    print(f"lang={info.language} p={info.language_probability:.2f} "
          f"dur={info.duration:.0f}s model={a.model}", file=sys.stderr)

    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append((w.start, w.end, w.word))
    if not words:
        sys.exit("whisper produced no words")
    print(f"{len(words)} words", file=sys.stderr)

    # chunk into <=cue-secs VTT cues, every word karaoke-tagged — same
    # shape parse_words consumes (no rolling-context repeats needed)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("WEBVTT\nKind: captions\n\n")
        i = 0
        while i < len(words):
            j = i
            while (j + 1 < len(words)
                   and words[j + 1][0] - words[i][0] <= a.cue_secs):
                j += 1
            cs, ce = words[i][0], words[j][1]
            f.write(f"{_ts(cs)} --> {_ts(ce)}\n")
            f.write("".join(f"<{_ts(s)}><c>{w}</c>"
                            for s, _, w in words[i:j + 1]) + "\n\n")
            i = j + 1
    print(f"wrote {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
