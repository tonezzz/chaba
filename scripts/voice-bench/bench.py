#!/usr/bin/env python3
"""voice-bench harness — stream fixtures through a declared combo and record metrics.

Usage:
  bench.py --combo cascade-whisper-piper [--dry-run] [--models small,medium]

Per fixture measures: stt_ms, llm_first_token_ms, llm_total_ms, tts_ms,
ttfa_ms (stt + llm first-token + tts of the spoken reply), total_ms,
WER/CER vs expected transcript, tool-call match (exact|partial|none).
Output: results/<combo>-<ts>.json
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jiwer
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def norm_en(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", s.lower())).strip()


def norm_th(s: str) -> str:
    return re.sub(r"\s+", "", s)


def error_rate(lang, ref, hyp):
    if lang == "th":
        ref, hyp = norm_th(ref), norm_th(hyp)
        if not ref:
            return None
        # CER via Levenshtein on chars
        return jiwer.cer(ref, hyp)
    return jiwer.wer(norm_en(ref), norm_en(hyp))


def tool_match(expected, got):
    if not expected:
        return "exact" if not got or got.get("tool") in (None, "chitchat") else "none"
    if not got or got.get("tool") != expected.get("tool"):
        return "none"
    eargs, gargs = expected.get("args") or {}, got.get("args") or {}
    matched = sum(
        1 for k, v in eargs.items()
        if k in gargs and gargs[k] is not None
        and (norm_en(str(v)) in norm_en(str(gargs[k])) or norm_en(str(gargs[k])) in norm_en(str(v)))
    )
    return "exact" if matched == len(eargs) else "partial"


def parse_llm_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


class WhisperSTT:
    def __init__(self, model, device, compute_type):
        from faster_whisper import WhisperModel
        self.name = f"faster-whisper:{model}"
        try:
            self.model = WhisperModel(model, device=device, compute_type=compute_type)
            self.device = device
        except Exception as e:  # CUDA OOM / unsupported — fall back to CPU
            print(f"  [stt] {device}/{compute_type} failed ({type(e).__name__}); falling back to cpu/int8", file=sys.stderr)
            self.model = WhisperModel(model, device="cpu", compute_type="int8")
            self.device = "cpu"

    def transcribe(self, wav: Path, lang: str):
        import numpy as np
        raw = subprocess.run(
            ["ffmpeg", "-v", "quiet", "-i", str(wav), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
            capture_output=True, check=True,
        ).stdout
        audio = np.frombuffer(raw, dtype=np.float32)
        t0 = time.perf_counter()
        segs, _ = self.model.transcribe(audio, language=lang, beam_size=1, vad_filter=True)
        text = " ".join(s.text for s in segs).strip()
        return text, (time.perf_counter() - t0) * 1000


class OllamaLLM:
    def __init__(self, base_url, model, template):
        self.base_url, self.model, self.template = base_url, model, template
        self.client = httpx.Client(timeout=120)

    def generate(self, text: str):
        prompt = self.template.format(text=text)
        t0 = time.perf_counter()
        first_ms = None
        out = []
        with self.client.stream("POST", f"{self.base_url}/api/generate",
                                json={"model": self.model, "prompt": prompt, "stream": True,
                                      "options": {"num_predict": 96, "temperature": 0}}) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if first_ms is None and chunk.get("response"):
                    first_ms = (time.perf_counter() - t0) * 1000
                out.append(chunk.get("response", ""))
                if chunk.get("done"):
                    break
        total_ms = (time.perf_counter() - t0) * 1000
        return "".join(out), first_ms or total_ms, total_ms


class PiperTTS:
    def __init__(self, binary, voice):
        self.binary, self.voice = str(ROOT / binary), str(ROOT / voice)

    def synth(self, text: str, out: Path):
        t0 = time.perf_counter()
        p = subprocess.run([self.binary, "-m", self.voice, "-f", str(out), "--length-scale", "1.0"],
                           input=text.encode(), capture_output=True)
        ms = (time.perf_counter() - t0) * 1000
        return ms if p.returncode == 0 else None


def run(combo_id: str, models_filter=None, dry_run=False):
    combos = yaml.safe_load((HERE / "combos.yml").read_text())["combos"]
    if combo_id not in combos:
        sys.exit(f"unknown combo {combo_id!r}; have: {list(combos)}")
    combo = combos[combo_id]
    manifest = yaml.safe_load((HERE / "fixtures/manifest.yml").read_text())["fixtures"]

    if dry_run:
        print(json.dumps({"combo": combo_id, "fixtures": len(manifest),
                          "schema": ["fixture_id", "stt_ms", "llm_first_token_ms", "llm_total_ms",
                                     "tts_ms", "ttfa_ms", "total_ms", "wer", "tool_match"]}, indent=2))
        return

    llm = OllamaLLM(combo["llm"]["base_url"], combo["llm"]["model"], combo["llm"]["prompt_template"])
    tts = PiperTTS(combo["tts"]["binary"], combo["tts"]["voice"])
    models = models_filter or combo["stt"]["models"]
    results = {"combo": combo_id, "ts": datetime.now(timezone.utc).isoformat(),
               "llm_model": combo["llm"]["model"], "runs": []}

    for mname in models:
        stt = WhisperSTT(mname, combo["stt"]["device"], combo["stt"]["compute_type"])
        run_rec = {"stt_model": mname, "stt_device": stt.device, "fixtures": []}
        for fx in manifest:
            wav = HERE / "fixtures" / fx["wav"]
            rec = {"fixture_id": fx["id"], "lang": fx["lang"]}
            t_start = time.perf_counter()
            transcript, rec["stt_ms"] = stt.transcribe(wav, fx["lang"])
            rec["transcript"] = transcript
            rec["wer"] = round(error_rate(fx["lang"], fx["expected_transcript"], transcript), 4)
            llm_out, rec["llm_first_token_ms"], rec["llm_total_ms"] = llm.generate(transcript)
            got = parse_llm_json(llm_out)
            rec["llm_raw"] = llm_out.strip()[:300]
            rec["tool_match"] = tool_match(fx.get("expected_tool"), got)
            say = (got or {}).get("say") or transcript
            if fx["lang"] == "th" and combo["tts"].get("thai_gap"):
                rec["tts_ms"] = None
                rec["tts_note"] = "skipped: no Thai piper voice"
            else:
                rec["tts_ms"] = tts.synth(say, HERE / "results" / f"_last_{fx['id']}.wav")
            rec["ttfa_ms"] = rec["stt_ms"] + rec["llm_first_token_ms"] + (rec["tts_ms"] or 0)
            rec["total_ms"] = (time.perf_counter() - t_start) * 1000
            for k in ("stt_ms", "llm_first_token_ms", "llm_total_ms", "ttfa_ms", "total_ms"):
                rec[k] = round(rec[k], 1)
            if rec["tts_ms"]:
                rec["tts_ms"] = round(rec["tts_ms"], 1)
            run_rec["fixtures"].append(rec)
            print(f"  {mname} {fx['id']}: stt={rec['stt_ms']:.0f}ms llm={rec['llm_total_ms']:.0f}ms "
                  f"tts={rec['tts_ms'] and round(rec['tts_ms']) or 'skip'} wer={rec['wer']} tool={rec['tool_match']}")
        results["runs"].append(run_rec)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = HERE / "results" / f"{combo_id}-{ts}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--combo", required=True)
    ap.add_argument("--models", help="comma-separated whisper models override")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(a.combo, a.models.split(",") if a.models else None, a.dry_run)
