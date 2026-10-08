#!/usr/bin/env python3
"""Render voice-bench results into reports/voice-fallback/LATEST.md."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent.parent / "reports/voice-fallback"


def agg(fixtures, lang=None):
    sel = [f for f in fixtures if lang is None or f["lang"] == lang]
    if not sel:
        return None
    def avg(k):
        vals = [f[k] for f in sel if f.get(k) is not None]
        return sum(vals) / len(vals) if vals else None
    wers = [f["wer"] for f in sel if f.get("wer") is not None]
    tm = {"exact": 0, "partial": 0, "none": 0}
    for f in sel:
        tm[f.get("tool_match", "none")] += 1
    return {
        "n": len(sel),
        "stt_ms": avg("stt_ms"), "llm_ft_ms": avg("llm_first_token_ms"),
        "llm_ms": avg("llm_total_ms"), "tts_ms": avg("tts_ms"),
        "ttfa_ms": avg("ttfa_ms"), "total_ms": avg("total_ms"),
        "wer": sum(wers) / len(wers) if wers else None,
        "tool": tm,
    }


def main(result_file=None):
    results = sorted((HERE / "results").glob("*.json"))
    if result_file:
        results = [Path(result_file)]
    lines = ["# Voice-fallback bench — LATEST", ""]
    lines.append("| combo | stt | device | lang | n | stt ms | llm ft ms | llm ms | tts ms | ttfa ms | total ms | WER/CER | tool exact/partial/none |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for rf in results:
        d = json.loads(rf.read_text())
        for run in d["runs"]:
            for lang in ("en", "th"):
                a = agg(run["fixtures"], lang)
                if not a:
                    continue
                lines.append(
                    f"| {d['combo']} | {run['stt_model']} | {run['stt_device']} | {lang} | {a['n']} "
                    f"| {a['stt_ms']:.0f} | {a['llm_ft_ms']:.0f} | {a['llm_ms']:.0f} "
                    f"| {a['tts_ms'] and round(a['tts_ms']) or '—'} | {a['ttfa_ms']:.0f} | {a['total_ms']:.0f} "
                    f"| {a['wer']:.3f} | {a['tool']['exact']}/{a['tool']['partial']}/{a['tool']['none']} |"
                )
        lines.append("")
        lines.append(f"source: `{rf.name}` (llm={d['llm_model']}, {d['ts']})")
        lines.append("")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "LATEST.md").write_text("\n".join(lines))
    print(f"wrote {OUT/'LATEST.md'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
