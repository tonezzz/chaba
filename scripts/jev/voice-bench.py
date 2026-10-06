#!/usr/bin/env python3
"""Voice bench (TTS-only): synthesize the eval cases as audio, transcribe
through whisper size tiers, and score each gate model on the ASR text.

Pipeline per case:
  text --edge-tts--> mp3 --ffmpeg--> wav(16k) --faster-whisper {tiny,base,small}--> transcript
  transcript --/v1/systemone--> gate p   (also scored on clean text)

Outputs: audio/*.wav, voice-bench.json with per-clip WER proxy,
gate accuracy (ASR vs clean), and per-tier latency.

  voice-bench.py eval-all.jsonl --gate http://100.102.134.91:8778 \
      --sizes tiny,base,small --out voice-bench.json
"""
import argparse, asyncio, json, re, subprocess, time
from pathlib import Path

THAI_RE = re.compile(r"[ก-๙]")
EN_VOICE = "en-US-AriaNeural"
TH_VOICE = "th-TH-PremwadeeNeural"


def thai(t): return bool(THAI_RE.search(t))


async def synth(text, voice, mp3):
    import edge_tts
    for attempt in range(5):
        try:
            c = edge_tts.Communicate(text, voice)
            await c.save(str(mp3))
            return
        except Exception:
            if attempt == 4:
                raise
            await asyncio.sleep(2 * (attempt + 1))


def to_wav(mp3, wav):
    subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-i", str(mp3),
                    "-ar", "16000", "-ac", "1", str(wav)], check=True)


def gate(url, turn):
    import urllib.request
    body = json.dumps({
        "state": f'Ada, a voice assistant, asked the user to confirm a '
                 f'memory write. The user turn was: "{turn}"',
        "questions": {"q1": {"type": "noul"}},
    }).encode()
    req = urllib.request.Request(url + "/v1/systemone", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["answers"]["q1"]["noul"]


def cer(a, b):
    """char error rate, whitespace-normalized — better than WER for Thai
    (no spaces between words)."""
    import difflib
    a = " ".join(a.split()); b = " ".join(b.split())
    sm = difflib.SequenceMatcher(None, a, b)
    return round(1 - sm.ratio(), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("--gate", default="http://100.102.134.91:8778")
    ap.add_argument("--thr", type=float, default=0.75)
    ap.add_argument("--sizes", default="tiny,base,small")
    ap.add_argument("--out", default="voice-bench.json")
    ap.add_argument("--audio-dir", default="audio")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.corpus) if l.strip()]
    adir = Path(args.audio_dir); adir.mkdir(exist_ok=True)

    # --- TTS ---
    t0 = time.time()
    for i, r in enumerate(rows):
        wav = adir / f"{i:03d}.wav"
        if wav.exists(): continue
        mp3 = adir / f"{i:03d}.mp3"
        asyncio.run(synth(r["text"], TH_VOICE if thai(r["text"]) else EN_VOICE, mp3))
        to_wav(mp3, wav); mp3.unlink()
    print(f"tts: {len(rows)} clips ({time.time()-t0:.0f}s)")

    # --- Whisper tiers ---
    from faster_whisper import WhisperModel
    results = {i: {"text": r["text"], "label": bool(r["label"]),
                   "clean_p": gate(args.gate, r["text"])}
               for i, r in enumerate(rows)}
    for size in args.sizes.split(","):
        wm = WhisperModel(size, device="cpu", compute_type="int8")
        for i in results:
            wav = str(adir / f"{i:03d}.wav")
            t = time.time()
            segs, _ = wm.transcribe(wav, beam_size=1)
            tx = "".join(s.text for s in segs).strip()
            dt = time.time() - t
            p = gate(args.gate, tx) if tx else 0.0
            r = results[i][size] = {
                "asr": tx, "asr_s": round(dt, 2),
                "cer": cer(results[i]["text"], tx), "p": p,
                "ok": (p >= args.thr) == results[i]["label"],
                "flip": (p >= args.thr) != (results[i]["clean_p"] >= args.thr),
            }
        del wm
        print(f"  tier {size} done", flush=True)

    # --- report ---
    rep = {"gate": args.gate, "thr": args.thr, "n": len(rows), "tiers": {}}
    for size in args.sizes.split(","):
        sub = [results[i][size] for i in results]
        sel_th = [results[i] for i in results if thai(results[i]["text"])]
        rep["tiers"][size] = {
            "acc": round(sum(s["ok"] for s in sub) / len(sub), 3),
            "flips": sum(s["flip"] for s in sub),
            "cer_med": sorted(s["cer"] for s in sub)[len(sub) // 2],
            "cer_thai_med": sorted(results[i][size]["cer"] for i in
                                   range(len(rows)) if thai(results[i]["text"]))[len(sel_th) // 2],
            "asr_s_med": round(sorted(s["asr_s"] for s in sub)[len(sub) // 2], 2),
            "misses": [{"text": results[i]["text"][:50], "asr": s["asr"][:50],
                        "p": round(s["p"], 2)} for i, s in
                       ((i, results[i][size]) for i in results) if not s["ok"]],
        }
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    Path(args.out).write_text(json.dumps({"rep": rep, "rows": results},
                                        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
