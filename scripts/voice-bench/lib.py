"""Shared helpers for the voice-fallback benchmark harness."""
import json
import re
import unicodedata
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
COMBOS = HERE / "combos.yml"
MANIFEST = HERE / "fixtures" / "manifest.yml"
RESULTS = HERE / "results"
RESULT_SCHEMA_VERSION = 1


class HarnessError(Exception):
    pass


def load_combos():
    data = yaml.safe_load(COMBOS.read_text()) or {}
    combos = {}
    for i, c in enumerate(data.get("combos") or []):
        ctx = f"combos.yml entry #{i}"
        if not isinstance(c, dict):
            raise HarnessError(f"{ctx}: must be a mapping")
        cid = c.get("id")
        if not cid or not isinstance(cid, str):
            raise HarnessError(f"{ctx}: missing string 'id'")
        if cid in combos:
            raise HarnessError(f"{ctx}: duplicate id {cid!r}")
        for field in ("stt", "llm", "tts", "orchestrator"):
            if not isinstance(c.get(field), str):
                raise HarnessError(f"{ctx} ({cid}): missing string '{field}'")
        labels = c.get("host_labels") or []
        if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
            raise HarnessError(f"{ctx} ({cid}): host_labels must be a list of strings")
        rt = c.get("runtime") or {}
        if rt.get("kind") not in (None, "none", "local", "podman"):
            raise HarnessError(f"{ctx} ({cid}): runtime.kind must be none|local|podman")
        combos[cid] = {
            "id": cid,
            "stt": c["stt"],
            "llm": c["llm"],
            "tts": c["tts"],
            "orchestrator": c["orchestrator"],
            "host_labels": labels,
            "runtime": rt,
            "endpoint": c.get("endpoint", ""),
            "adapter": c.get("adapter"),
            "notes": c.get("notes", ""),
        }
    return combos


def get_combo(combo_id):
    combos = load_combos()
    if combo_id not in combos:
        raise HarnessError(
            f"unknown combo {combo_id!r}; known: {', '.join(sorted(combos)) or '(none)'}"
        )
    return combos[combo_id]


def load_fixtures():
    data = yaml.safe_load(MANIFEST.read_text()) or {}
    fixtures = data.get("fixtures") or []
    seen = set()
    for i, fx in enumerate(fixtures):
        fid = fx.get("id")
        if not fid or fid in seen:
            raise HarnessError(f"manifest.yml entry #{i}: bad/duplicate id {fid!r}")
        seen.add(fid)
        for field in ("lang", "phrase", "expected_transcript"):
            if not isinstance(fx.get(field), str):
                raise HarnessError(f"manifest.yml ({fid}): missing '{field}'")
        wav = HERE / "fixtures" / f"{fid}.wav"
        fx["wav"] = str(wav)
        fx["wav_exists"] = wav.exists()
    return fixtures


# --- scoring ----------------------------------------------------------------

def normalize(text):
    text = unicodedata.normalize("NFKC", (text or "").lower())
    text = re.sub(r"[^\w\s\u0e00-\u0e7f]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _levenshtein(a, b):
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def wer(expected, actual, lang="en"):
    """Word error rate for English; character error rate for Thai (no spaces)."""
    e, a = normalize(expected), normalize(actual)
    if lang == "th":
        ref, hyp = list(e.replace(" ", "")), list(a.replace(" ", ""))
    else:
        ref, hyp = e.split(), a.split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return round(_levenshtein(ref, hyp) / len(ref), 4)


def tool_call_match(expected, actual):
    """exact = name + all expected args match; partial = name matches;
    none = anything else. expected None -> 'n/a' (no call expected)."""
    if expected is None:
        return "n/a"
    if not isinstance(actual, dict):
        return "none"
    if actual.get("name") != expected.get("name"):
        return "none"
    e_args = expected.get("args") or {}
    a_args = actual.get("args") or {}
    if all(a_args.get(k) == v for k, v in e_args.items()):
        return "exact"
    return "partial"


def fixture_result(fx, *, transcript=None, tool_call=None,
                   ttfa_ms=None, total_ms=None, status="ok", error=None):
    return {
        "id": fx["id"],
        "lang": fx["lang"],
        "category": fx["category"],
        "status": status,
        "error": error,
        "ttfa_ms": ttfa_ms,
        "total_ms": total_ms,
        "transcript": transcript,
        "expected_transcript": fx["expected_transcript"],
        "wer": wer(fx["expected_transcript"], transcript, fx["lang"])
        if transcript else None,
        "tool_call": tool_call,
        "expected_tool_call": fx.get("expected_tool_call"),
        "tool_call_match": tool_call_match(fx.get("expected_tool_call"), tool_call),
    }


def result_doc(combo, fixture_results, *, dry_run=False, meta=None):
    summary = {
        "n": len(fixture_results),
        "ok": sum(1 for r in fixture_results if r["status"] == "ok"),
        "mean_ttfa_ms": _mean(r["ttfa_ms"] for r in fixture_results),
        "mean_total_ms": _mean(r["total_ms"] for r in fixture_results),
        "mean_wer": _mean(r["wer"] for r in fixture_results),
        "tool_call": _tally(r["tool_call_match"] for r in fixture_results),
    }
    return {
        "schema": "voice-bench-result",
        "schema_version": RESULT_SCHEMA_VERSION,
        "combo": {k: combo[k] for k in
                  ("id", "stt", "llm", "tts", "orchestrator", "host_labels", "notes")},
        "dry_run": dry_run,
        "meta": meta or {},
        "summary": summary,
        "fixtures": fixture_results,
    }


def _mean(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 2) if vals else None


def _tally(vals):
    out = {"exact": 0, "partial": 0, "none": 0, "n/a": 0}
    for v in vals:
        out[v] = out.get(v, 0) + 1
    return out


def results_path(combo_id, ts):
    RESULTS.mkdir(exist_ok=True)
    return RESULTS / f"{combo_id}-{ts}.json"


def iter_results():
    for p in sorted(RESULTS.glob("*.json")):
        try:
            yield p, json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
