"""Publish the standard packet: report.md, verdict.json, education.html.

Reads results.json + replay-check.json produced by run/replay.
"""
import html
import json
from datetime import datetime, timezone

from .contract import canonical_json
from .harness import PACKET


def _verdict(results, check):
    gate_ok = check["ok"] and not results["schema_errors"]
    blocked = any("unrecorded" == a for a in
                  [r["model_revision"] for r in results["rows"]])
    sim_note = any(r.get("meta", {}).get("simulated")
                   for r in results["rows"])
    # watch: contract proven, replay deterministic, but NCM arm is a
    # stand-in and no quality adoption decision can be made at P0.
    verdict = "watch"
    confidence = "high" if gate_ok else "low"
    rationale = [
        "P0 gate: deterministic schema validity + reproducible replay "
        "from manifest.json without provider calls — "
        + ("PASS" if gate_ok else "FAIL"),
        f"{check['rows_replayed']} rows replayed, "
        f"{check['identity_mismatches']} identity mismatches, "
        f"{check['schema_errors']} schema errors, "
        f"{check['guard_violations']} authority-guard violations",
        "ncm_2level arm is a deterministic contract stand-in; the "
        "trained NCM checkpoint stays blocked until P1 authorized GPU",
        "LLM arms used pinned local Ollama models recorded at freeze; "
        "replay needs no provider",
    ]
    if blocked:
        rationale.append("some LLM cells recorded status=blocked — those "
                         "rows are schema-valid escalations, not passes")
    next_steps = [
        "P1: run the Thai NCM toy on authorized GPU (Colab) — frozen SP "
        "tokenizer, VQ codes, generator training, AR baseline",
        "P2: give JEV metadata-only features and measure route "
        "accuracy/gate precision on a held-out labelled set",
        "Adopt nothing: P0 proves the contract, not quality",
    ]
    return {
        "verdict": verdict,
        "confidence": confidence,
        "gate": {
            "schema_valid": not results["schema_errors"],
            "replay_deterministic": check["ok"],
            "providers_called_at_replay": check["providers_called"],
            "guard_violations": check["guard_violations"],
        },
        "simulated_arms_present": bool(sim_note),
        "rationale": rationale,
        "next": next_steps,
    }


def _report(manifest, results, check, verdict):
    s = results["summary"]
    n_tasks = len({r["task_id"] for r in results["rows"]})
    lines = [
        "# NCM + JEV + Nest — P0 replay contract benchmark",
        "",
        f"- procedure: `{manifest['procedure']}`",
        f"- corpus: `{manifest['corpus_id']}` sha256 "
        f"`{manifest['corpus_sha256'][:16]}…`",
        f"- code revision: `{manifest['code_revision']}`",
        f"- seeds: {manifest['seed_set']}",
        f"- rows: {len(results['rows'])} contract rows over "
        f"{n_tasks} tasks",
        "",
        "## P0 gate",
        "",
        f"- schema validity: **{'PASS' if not results['schema_errors'] else 'FAIL'}** "
        f"({len(results['schema_errors'])} errors)",
        f"- reproducible replay from manifest.json without provider "
        f"calls: **{'PASS' if check['ok'] else 'FAIL'}** "
        f"({check['rows_replayed']} rows, "
        f"{check['identity_mismatches']} mismatches)",
        f"- authority-guard violations: {check['guard_violations']}",
        "",
        "## Arms",
        "",
        "| arm | class | model_id | revision | quant | hw | sim |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for a in manifest["arms"]:
        lines.append(
            f"| {a['id']} | {a['class']} | {a['model_id']} | "
            f"`{str(a['model_revision'])[:14]}` | {a['quantization']} | "
            f"{a['hardware']} | {a['simulated']} |")
    lines += [
        "",
        "## Results per arm",
        "",
        "| candidate | n | pass | fail | escalate | mean score | "
        "tokens_out | mean latency_ms |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cid in sorted(s):
        a = s[cid]
        lines.append(
            f"| {cid} | {a['n']} | {a['pass']} | {a['fail']} | "
            f"{a['escalate']} | {a['mean_score']} | {a['tokens_out']} | "
            f"{a['mean_latency_ms']} |")
    lines += [
        "",
        "## Method",
        "",
        "1. Corpus frozen before running (`corpus/frozen.json`): 4 seeded "
        "Sudoku puzzles (ncmthai token format), 3 Thai continuation "
        "fixtures, 3 fixed short prompts, and one recorded local-Ollama "
        "output per LLM arm × task × seed.",
        "2. Every arm emits the worker-contract row "
        "(task_id,input,candidate,model_id,model_revision,prompt_hash,"
        "seed,output,latency_ms,tokens_in,tokens_out,verdict,"
        "artifact_ref).",
        "3. Deterministic verifier scores each output — the claimed "
        "answer (last non-empty line / last grid), so reasoning prose "
        "doesn't count as the answer; the authority guard escalates any "
        "output containing permission-minting keys.",
        "4. Replay regenerates all rows from manifest.json and compares "
        "identity fields (everything except wall-clock latency).",
        "",
        "## Honest caveats",
        "",
        "- `ncm_2level` is a contract stand-in, NOT the trained NCM — "
        "its scores measure the harness, not the paper architecture. "
        "Real NCM numbers require the P1 GPU stage, which stays blocked "
        "until authorized compute exists.",
        "- LLM arms are small local GGUF models; their outputs are real "
        "inference but represent the smallest authorized tier.",
        "- `ar_char_ngram` is a real (if weak) AR baseline trained on "
        "the 24-line frozen Thai corpus + task references.",
        "- P0 answers 'does the contract/replay machinery work', not "
        "'which generator is best'. Quality claims wait for P3.",
        "",
        f"## Verdict: **{verdict['verdict']}** "
        f"(confidence: {verdict['confidence']})",
        "",
    ] + [f"- {r}" for r in verdict["rationale"]]
    return "\n".join(lines) + "\n"


def _education(manifest, results, verdict):
    rows = "".join(
        f"<tr><td>{html.escape(c)}</td><td>{a['n']}</td>"
        f"<td>{a['pass']}</td><td>{a['fail']}</td>"
        f"<td>{a['escalate']}</td><td>{a['mean_score']}</td></tr>"
        for c, a in sorted(results["summary"].items()))
    arms = "".join(
        f"<li><b>{html.escape(a['id'])}</b> ({a['class']}) — "
        f"{html.escape(a['model_id'])} @ "
        f"{html.escape(str(a['model_revision']))[:20]}, "
        f"{a['quantization']}, {html.escape(a['hardware'])}"
        + (" <i>[simulated]</i>" if a["simulated"] else "") + "</li>"
        for a in manifest["arms"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>NCM+JEV+Nest P0 — replay contract</title>
<style>body{{font-family:system-ui,sans-serif;max-width:52em;margin:2em auto;line-height:1.5}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:.3em .6em}}
code{{background:#f4f4f4;padding:.1em .3em}}</style></head><body>
<h1>P0 replay contract — NCM + JEV + Nest</h1>
<p><b>What this is.</b> The contract-and-replay stage of the exploration
procedure: a frozen corpus (seeded Sudoku puzzles, Thai continuation
fixtures, fixed short prompts) replayed through a common worker
contract. It proves the machinery — schema-valid rows, deterministic
verifier, authority guard, provider-free replay — before any GPU spend.</p>
<p><b>What it is not.</b> A quality benchmark. The NCM arm is a
two-level stand-in pending the blocked P1 GPU stage; LLM arms are the
smallest local pinned models. No routing or production change follows.</p>
<h2>Arms</h2><ul>{arms}</ul>
<h2>Per-arm outcomes</h2>
<table><tr><th>candidate</th><th>n</th><th>pass</th><th>fail</th>
<th>escalate</th><th>mean&nbsp;score</th></tr>{rows}</table>
<h2>Gate &amp; verdict</h2>
<p>Verdict: <b>{verdict['verdict']}</b> ({verdict['confidence']}).</p>
<ul>{"".join(f"<li>{html.escape(r)}</li>" for r in verdict["rationale"])}</ul>
<h2>Reproduce</h2>
<pre>cd experiments/ncm-jev-p0
python3 -m p0harness replay   # provider-free; exit 0 = gate pass</pre>
<p>Packet: <code>manifest.json</code> <code>results.json</code>
<code>report.md</code> <code>verdict.json</code>
<code>education.html</code></p>
<p>Generated {datetime.now(timezone.utc).isoformat(timespec="seconds")}
· procedure: docs/kb/ncm-jev-nest-exploration-procedure.md</p>
</body></html>"""


def publish(manifest, results, check):
    verdict = _verdict(results, check)
    (PACKET / "verdict.json").write_text(
        canonical_json(verdict) + "\n", encoding="utf-8")
    (PACKET / "report.md").write_text(
        _report(manifest, results, check, verdict), encoding="utf-8")
    (PACKET / "education.html").write_text(
        _education(manifest, results, verdict), encoding="utf-8")
    print(f"packet: verdict={verdict['verdict']} -> {PACKET}")
    return verdict
