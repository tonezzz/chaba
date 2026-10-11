"""Shared helpers for the micro-bench input-polish harness."""
import json
import re
import unicodedata
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
VARIANTS = HERE / "variants.yml"
MANIFEST = HERE / "fixtures" / "manifest.yml"
RESULTS = HERE / "results"
RESULT_SCHEMA_VERSION = 1

# The fixed "receiving AI" protocol: a small HA-style tool surface plus a
# strict JSON reply shape, so any chat model can stand in for the real
# downstream (Ada/Gemini) and results stay comparable across variants.
DOWNSTREAM_SYSTEM = """\
You are a home-assistant voice agent. The user gives you one utterance.
Reply with EXACTLY one JSON object, no other text:
  {"tool_call": {"name": "<tool>", "args": {...}}}   — to act
  {"answer": "<short reply>"}                        — to answer, chat back, \
or ask for clarification

Available tools (names and args are exact — do not invent others):
  hass_turn_on(domain, area)        domain: light|fan|climate|media_player|switch
  hass_turn_off(domain, area)
  hass_set_temperature(area, temperature)   temperature: number
  hass_lock(entity)                 entity: front_door
  hass_get_state(entity)            entity: sensor.outside_temperature,
    sensor.washer_power, sensor.solar_power, lock.front_door, light.kitchen
Rules: if the request is ambiguous or has no referent, answer asking for
clarification. Never fabricate entity names. Preserve every name, number,
and device id from the utterance exactly."""

POLISH_PROMPTS = {
    "normalize_v1": """\
You are an input normalizer for a voice assistant. Rewrite the user's
utterance into clean, canonical phrasing: fix ASR mishearings, typos,
code-switched Thai/English, and fragments. Rules:
- Preserve every name, number, entity id, and the user's intent EXACTLY.
- If the input is already clean, return it unchanged.
- If the input is ambiguous or gibberish, return it UNCHANGED — never
  invent a referent or guess a command.
- Reply in the same language as the input (Thai stays Thai).
- Output ONLY the rewritten utterance — no quotes, no explanation.""",
}

CATEGORIES = ("asr_noise_en", "asr_noise_th", "thai_eng_mix", "typo",
              "fragment", "clean", "entity_heavy", "chit_chat",
              "ambiguous", "gibberish")


class HarnessError(Exception):
    pass


def load_variants():
    data = yaml.safe_load(VARIANTS.read_text()) or {}
    out = {}
    for i, v in enumerate(data.get("variants") or []):
        ctx = f"variants.yml entry #{i}"
        if not isinstance(v, dict):
            raise HarnessError(f"{ctx}: must be a mapping")
        vid = v.get("id")
        if not vid or not isinstance(vid, str):
            raise HarnessError(f"{ctx}: missing string 'id'")
        if vid in out:
            raise HarnessError(f"{ctx}: duplicate id {vid!r}")
        ds = v.get("downstream")
        if not isinstance(ds, dict) or not ds.get("provider") \
                or not ds.get("model"):
            raise HarnessError(f"{ctx} ({vid}): downstream needs provider+model")
        pol = v.get("polish")
        if pol is not None:
            if not isinstance(pol, dict) or not pol.get("provider") \
                    or not pol.get("model"):
                raise HarnessError(f"{ctx} ({vid}): polish needs provider+model")
            if pol.get("prompt", "normalize_v1") not in POLISH_PROMPTS:
                raise HarnessError(
                    f"{ctx} ({vid}): unknown polish prompt {pol.get('prompt')!r}")
        out[vid] = {
            "id": vid,
            "polish": pol,
            "downstream": ds,
            "host_labels": v.get("host_labels") or [],
            "notes": v.get("notes", ""),
        }
    return out


def get_variant(variant_id):
    variants = load_variants()
    if variant_id not in variants:
        raise HarnessError(
            f"unknown variant {variant_id!r}; known: "
            f"{', '.join(sorted(variants)) or '(none)'}")
    return variants[variant_id]


def load_fixtures():
    data = yaml.safe_load(MANIFEST.read_text()) or {}
    fixtures = data.get("fixtures") or []
    seen = set()
    for i, fx in enumerate(fixtures):
        fid = fx.get("id")
        if not fid or fid in seen:
            raise HarnessError(f"manifest.yml entry #{i}: bad/duplicate id {fid!r}")
        seen.add(fid)
        for field in ("lang", "category", "raw", "gold"):
            if not isinstance(fx.get(field), str):
                raise HarnessError(f"manifest.yml ({fid}): missing '{field}'")
        if fx["category"] not in CATEGORIES:
            raise HarnessError(
                f"manifest.yml ({fid}): unknown category {fx['category']!r}")
        etc = fx.get("expected_tool_call")
        if etc is not None and not isinstance(etc, dict):
            raise HarnessError(f"manifest.yml ({fid}): bad expected_tool_call")
        fx.setdefault("preserve", [])
    return fixtures


# --- scoring ---------------------------------------------------------------

def normalize(text):
    text = unicodedata.normalize("NFKC", (text or "").lower())
    text = re.sub(r"[^\w\s฀-๿.]", " ", text)
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


def similarity(a, b):
    """Normalized similarity 0..1 (1 = identical after normalization)."""
    a, b = normalize(a), normalize(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return round(1 - _levenshtein(a, b) / max(len(a), len(b)), 4)


def entities_preserved(preserve, text):
    """Fraction of preserve[] strings present in text (normalized)."""
    if not preserve:
        return None
    norm = normalize(text)
    hit = sum(1 for p in preserve if normalize(str(p)) in norm)
    return round(hit / len(preserve), 4)


def tool_call_match(expected, actual):
    """exact = name + all expected args; partial = name only; none = miss.
    'fabricated' = nothing expected but a call was emitted (polish or
    downstream invented an action — the key regression signal).
    'n/a' = nothing expected, none emitted."""
    if expected is None:
        return "fabricated" if isinstance(actual, dict) and actual.get("name") \
            else "n/a"
    if not isinstance(actual, dict):
        return "none"
    if actual.get("name") != expected.get("name"):
        return "none"
    e_args = expected.get("args") or {}
    a_args = actual.get("args") or {}
    if all(a_args.get(k) == v for k, v in e_args.items()):
        return "exact"
    return "partial"


def fixture_result(fx, *, polished=None, polish_ms=None, polish_tokens=None,
                   reply=None, tool_call=None, answer=None, downstream_ms=None,
                   downstream_tokens=None, status="ok", error=None):
    sent = polished if polished is not None else fx["raw"]
    return {
        "id": fx["id"],
        "lang": fx["lang"],
        "category": fx["category"],
        "status": status,
        "error": error,
        "raw": fx["raw"],
        "gold": fx["gold"],
        "polished": polished,
        "sent_downstream": sent,
        "polish_ms": polish_ms,
        "polish_tokens": polish_tokens,
        "downstream_ms": downstream_ms,
        "downstream_tokens": downstream_tokens,
        "total_ms": (polish_ms or 0) + (downstream_ms or 0)
        if downstream_ms is not None else None,
        "net_tokens": (polish_tokens or 0) + (downstream_tokens or 0)
        if downstream_tokens is not None else None,
        "polish_sim": similarity(fx["gold"], polished)
        if polished is not None else None,
        "entities": entities_preserved(fx["preserve"], sent),
        "reply": reply,
        "tool_call": tool_call,
        "answer": answer,
        "expected_tool_call": fx.get("expected_tool_call"),
        "tool_call_match": tool_call_match(fx.get("expected_tool_call"),
                                           tool_call),
    }


def result_doc(variant, fixture_results, *, dry_run=False, meta=None):
    def _mean(key):
        vals = [r[key] for r in fixture_results
                if isinstance(r.get(key), (int, float))]
        return round(sum(vals) / len(vals), 2) if vals else None

    per_cat = {}
    for r in fixture_results:
        c = per_cat.setdefault(r["category"], {"n": 0, "exact": 0,
                                               "fabricated": 0})
        c["n"] += 1
        if r["tool_call_match"] == "exact":
            c["exact"] += 1
        if r["tool_call_match"] == "fabricated":
            c["fabricated"] += 1

    return {
        "schema": "micro-bench-result",
        "schema_version": RESULT_SCHEMA_VERSION,
        "variant": {k: variant[k] for k in ("id", "polish", "downstream",
                                            "host_labels", "notes")},
        "dry_run": dry_run,
        "meta": meta or {},
        "summary": {
            "n": len(fixture_results),
            "ok": sum(1 for r in fixture_results if r["status"] == "ok"),
            "mean_polish_sim": _mean("polish_sim"),
            "mean_entities": _mean("entities"),
            "mean_polish_ms": _mean("polish_ms"),
            "mean_downstream_ms": _mean("downstream_ms"),
            "mean_total_ms": _mean("total_ms"),
            "mean_polish_tokens": _mean("polish_tokens"),
            "mean_downstream_tokens": _mean("downstream_tokens"),
            "mean_net_tokens": _mean("net_tokens"),
            "tool_call": _tally(r["tool_call_match"]
                                for r in fixture_results),
            "per_category": per_cat,
        },
        "fixtures": fixture_results,
    }


def _tally(vals):
    out = {"exact": 0, "partial": 0, "none": 0, "fabricated": 0, "n/a": 0}
    for v in vals:
        out[v] = out.get(v, 0) + 1
    return out


def results_path(variant_id, ts):
    RESULTS.mkdir(exist_ok=True)
    return RESULTS / f"{variant_id}-{ts}.json"


def iter_results():
    for p in sorted(RESULTS.glob("*.json")):
        try:
            doc = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if doc.get("schema") == "micro-bench-result":
            yield p, doc
