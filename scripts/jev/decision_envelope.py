#!/usr/bin/env python3
"""decision-envelope — normalize + lint the JevTeam decision envelope.

Card jevteam-omen-or-lane-admission (2026-11-24). One request shape every
JevTeam lane accepts for a bounded decision or bounded work item:

    executor / provider / model / lane / task_class /
    artifact / expect / max_tokens / cost_budget / fallback

Canonical schema: schemas/jevteam-decision-envelope.schema.json.
This module validates WITHOUT jsonschema (stdlib + optional yaml) so it
runs on every fleet host — the schema file is the contract, this is the
enforcement copy. When the two drift, the schema wins and this file
gets updated.

Field semantics:
  executor   catalog executor id (devin, opencode, kk_mac_local, script,
             nlm_batch, claude) or a decision-plane lane ref (omen,
             jevos). 'omen' is decision-plane ONLY — it may carry
             artifact/expect for scoring/audit tasks but must never
             carry mutation intent (the lane has no mutation path).
  provider   model namespace — litellm, openrouter, ollama, omen-local,
             jev-student, devin, none.
  model      concrete model id; '' = executor default.
  lane       ssot.devnest-lanes.yml catalog lane id.
  task_class bounded class declared by the lane's task_classes.
  artifact   {path, kind} the verifier checks, or null for inline
             decision answers (noul/choice/score) with no persisted file.
  expect     {required_keys, enums, facts} — same shape as the
             kk_mac_local action.expect verifier contract.
  max_tokens hard output-token cap; required, unbounded calls refused.
  cost_budget {usd, window: call|day|30d} — usd=0 marks a free/local leg;
             paid legs must fit inside the claim-time key headroom.
  fallback   {lane, on[]} — ordered escape; on lists trigger classes
             (401/402/429/timeout/health_fail/verifier_fail/quota/any).

Usage:
  decision_envelope.py lint envelope.json|envelope.yaml
  decision_envelope.py normalize card.yml          # action -> envelope
  decision_envelope.py selftest                    # built-in cases

Exit codes: 0 valid | 1 invalid envelope | 2 usage/io error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED = [
    "executor", "provider", "model", "lane", "task_class",
    "artifact", "expect", "max_tokens", "cost_budget", "fallback",
]

EXECUTORS = {"devin", "opencode", "kk_mac_local", "script", "nlm_batch",
             "claude", "manual", "omen", "jevos", "none"}
PROVIDERS = {"litellm", "openrouter", "ollama", "omen-local",
             "jev-student", "devin", "none"}
FALLBACK_ON = {"401", "402", "429", "timeout", "health_fail",
               "verifier_fail", "quota", "any"}
COST_WINDOWS = {"call", "day", "30d"}
MAX_TOKENS_CAP = 200000

# decision-plane lanes — answers only, never mutations. An envelope that
# routes mutation-shaped work here is invalid by construction.
DECISION_ONLY = {"omen", "jevos"}
MUTATION_HINTS = ("write", "mutat", "deploy", "delete", "push",
                  "install", "restart", "edit", "commit", "rm ",
                  "create file", "modify")


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate(env: dict) -> list[str]:
    """Envelope lint — empty list = structurally valid."""
    errs = []
    if not isinstance(env, dict):
        return ["envelope must be an object"]
    for k in REQUIRED:
        if k not in env:
            errs.append(f"missing_envelope_field:{k}")
    if errs:
        return errs

    ex = env.get("executor")
    if not isinstance(ex, str) or not ex.strip():
        errs.append("bad_value:executor must be a non-empty string")
    elif ex.strip() not in EXECUTORS:
        errs.append(f"bad_value:executor={ex!r} not in {sorted(EXECUTORS)}")

    prov = env.get("provider")
    if not isinstance(prov, str) or not prov.strip():
        errs.append("bad_value:provider must be a non-empty string")
    elif prov.strip() not in PROVIDERS:
        errs.append(f"bad_value:provider={prov!r} not in {sorted(PROVIDERS)}")

    model = env.get("model")
    if not isinstance(model, str) or len(model) > 120:
        errs.append("bad_value:model must be a string <=120 chars")

    lane = env.get("lane")
    if not isinstance(lane, str) or not lane.strip():
        errs.append("bad_value:lane must be a non-empty string")

    tc = env.get("task_class")
    if not isinstance(tc, str) or not tc.strip():
        errs.append("bad_value:task_class must be a non-empty string")
    elif ex in DECISION_ONLY:
        # decision planes score/route/gate — they never mutate. A task
        # class that names a mutation verb is refused outright.
        t = tc.lower()
        if any(h in t for h in MUTATION_HINTS):
            errs.append(
                f"decision_plane_mutation:{tc!r} cannot run on {ex} "
                "(decision-only lane)")

    art = env.get("artifact")
    if art is not None:
        if not isinstance(art, dict):
            errs.append("bad_value:artifact must be an object or null")
        else:
            for k in ("path", "kind"):
                if k in art and not isinstance(art[k], str):
                    errs.append(f"bad_value:artifact.{k} must be a string")
            p = art.get("path")
            if p is not None and (p.startswith("/") or ".." in
                                  Path(p).parts):
                errs.append("bad_value:artifact.path must be "
                            "repo-relative, no '..'")

    exp = env.get("expect")
    if exp is not None:
        if not isinstance(exp, dict):
            errs.append("bad_value:expect must be an object or null")
        else:
            for sect in ("required_keys", "facts"):
                if sect in exp and not (
                        isinstance(exp[sect], list)
                        and all(isinstance(x, str) for x in exp[sect])):
                    errs.append(f"bad_value:expect.{sect} must be "
                                "a list of strings")
            if "enums" in exp:
                en = exp["enums"]
                if not isinstance(en, dict) or not all(
                        isinstance(v, list)
                        and all(isinstance(x, str) for x in v)
                        for v in en.values()):
                    errs.append("bad_value:expect.enums must be "
                                "{key: [allowed strings]}")

    mt = env.get("max_tokens")
    if not isinstance(mt, int) or isinstance(mt, bool) \
            or not 1 <= mt <= MAX_TOKENS_CAP:
        errs.append(f"bad_value:max_tokens must be int 1..{MAX_TOKENS_CAP}")

    cb = env.get("cost_budget")
    if not isinstance(cb, dict):
        errs.append("bad_value:cost_budget must be an object")
    else:
        usd = cb.get("usd")
        if not _is_num(usd) or usd < 0:
            errs.append("bad_value:cost_budget.usd must be >=0")
        if cb.get("window") not in COST_WINDOWS:
            errs.append("bad_value:cost_budget.window must be one of "
                        f"{sorted(COST_WINDOWS)}")

    fb = env.get("fallback")
    if not isinstance(fb, dict):
        errs.append("bad_value:fallback must be an object")
    else:
        if not isinstance(fb.get("lane"), str) or not fb["lane"].strip():
            errs.append("bad_value:fallback.lane must be a non-empty "
                        "string")
        on = fb.get("on")
        if not isinstance(on, list) or not on or not all(
                x in FALLBACK_ON for x in on):
            errs.append("bad_value:fallback.on must be a non-empty list "
                        f"of {sorted(FALLBACK_ON)}")

    # paid leg sanity: provider openrouter/litellm with a nonzero model
    # pick and usd=0 budget is a contradiction — free aliases are named
    # or-free-*; anything else on a $0 budget is a mislabeled paid call.
    if isinstance(model, str) and model and _is_num(
            (cb or {}).get("usd")):
        paidish = ("or-" in model and "free" not in model) or \
            model.startswith("openrouter/")
        if paidish and cb.get("usd") == 0:
            errs.append("cost_budget_mismatch: paid-looking model "
                        f"{model!r} declared usd=0")

    return errs


def normalize(card: dict, defaults: dict | None = None) -> dict:
    """Build an envelope from a kanban card's action block.

    Maps the existing card contract onto the normalized shape:
      action.executor/model/lane/task_class/artifact/expect -> same names
      action.lane_envelope.* (opencode job envelope) wins where present
      defaults fill anything still missing (caller supplies lane-appropriate
      max_tokens/cost_budget/fallback for its task).
    """
    a = card.get("action") if isinstance(card.get("action"), dict) else {}
    env_in = a.get("lane_envelope") if isinstance(
        a.get("lane_envelope"), dict) else {}
    d = dict(defaults or {})

    def pick(*names):
        for n in names:
            for src in (env_in, a, d):
                v = src.get(n)
                if v not in (None, ""):
                    return v
        return None

    model = pick("model") or ""
    prov = pick("provider")
    if not prov:
        prov = model.split("/", 1)[0] if "/" in model else (
            "devin" if model else "none")
    art = pick("artifact")
    if isinstance(art, str):
        art = {"path": art, "kind": "file"}
    exp = pick("expect")
    if exp is None:
        # lane_envelope-style verifier refs don't map to expect; keep
        # the card's own verifier name as a fact when nothing else exists.
        ver = a.get("verifier") or env_in.get("verifier")
        if isinstance(ver, dict) and ver.get("ref"):
            exp = {"facts": [f"verifier:{ver['ref']}"]}
        elif isinstance(ver, str) and ver:
            exp = {"facts": [f"verifier:{ver}"]}
    fb = pick("fallback")
    if fb is None:
        fb = {"lane": "devin", "on": ["any"]}
    elif isinstance(fb, str):
        fb = {"lane": fb, "on": ["any"]}

    env = {
        "executor": pick("executor") or "devin",
        "provider": prov,
        "model": model,
        "lane": pick("lane") or "devin",
        "task_class": pick("task_class") or "unclassified",
        "artifact": art,
        "expect": exp,
        "max_tokens": pick("max_tokens") or d.get("max_tokens") or 4096,
        "cost_budget": pick("cost_budget") or d.get("cost_budget")
        or {"usd": 0, "window": "call"},
        "fallback": fb,
    }
    return env


def _load(path: Path) -> dict:
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
            return yaml.safe_load(text)
        except ImportError:
            raise SystemExit(f"{path}: yaml module required for .yml input")
    return json.loads(text)


def selftest() -> int:
    good = {
        "executor": "opencode", "provider": "litellm",
        "model": "litellm/or-deepseek-v4-flash", "lane": "openrouter",
        "task_class": "bursty_experiment",
        "artifact": {"path": "reports/x.json", "kind": "json"},
        "expect": {"required_keys": ["verdict"],
                   "enums": {"verdict": ["pass", "fail"]},
                   "facts": ["host"]},
        "max_tokens": 2048,
        "cost_budget": {"usd": 0.05, "window": "call"},
        "fallback": {"lane": "devin", "on": ["429", "timeout"]},
    }
    cases = [
        ("good paid", good, 0),
        ("good free omen decision", {
            "executor": "omen", "provider": "omen-local",
            "model": "gemma-3-1b-it", "lane": "omen",
            "task_class": "noul_gate", "artifact": None, "expect": None,
            "max_tokens": 64, "cost_budget": {"usd": 0, "window": "call"},
            "fallback": {"lane": "jevos", "on": ["health_fail", "timeout"]},
        }, 0),
        ("missing max_tokens", {k: v for k, v in good.items()
                                if k != "max_tokens"}, 1),
        ("decision plane mutation", {
            "executor": "omen", "provider": "omen-local",
            "model": "gemma-3-4b-it", "lane": "omen",
            "task_class": "write the deploy script",
            "artifact": None, "expect": None, "max_tokens": 512,
            "cost_budget": {"usd": 0, "window": "call"},
            "fallback": {"lane": "devin", "on": ["any"]},
        }, 1),
        ("paid model zero budget", dict(good, cost_budget={
            "usd": 0, "window": "call"}), 1),
        ("bad fallback trigger", dict(good, fallback={
            "lane": "devin", "on": ["explode"]}), 1),
        ("artifact traversal", dict(good, artifact={
            "path": "../etc/passwd"}), 1),
    ]
    bad = 0
    for name, env, want_errs in cases:
        errs = validate(env)
        ok = bool(errs) == bool(want_errs)
        bad += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} {name}: "
              f"{errs if errs else 'valid'}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lint", help="validate an envelope file")
    p.add_argument("file")
    p = sub.add_parser("normalize", help="card yml -> envelope JSON")
    p.add_argument("file")
    p.add_argument("--defaults", default="",
                   help="JSON defaults merged under card fields")
    sub.add_parser("selftest")
    args = ap.parse_args()

    if args.cmd == "selftest":
        return selftest()
    path = Path(args.file)
    if not path.is_file():
        print(f"error: {path} not found", file=sys.stderr)
        return 2
    try:
        doc = _load(path)
    except Exception as e:
        print(f"error: {path}: {e}", file=sys.stderr)
        return 2

    if args.cmd == "lint":
        errs = validate(doc)
        if errs:
            for e in errs:
                print(f"INVALID {e}")
            return 1
        print("VALID")
        return 0

    # normalize
    defaults = {}
    if args.defaults:
        defaults = json.loads(Path(args.defaults).read_text())
    env = normalize(doc if isinstance(doc, dict) else {}, defaults)
    errs = validate(env)
    out = {"envelope": env, "errors": errs}
    print(json.dumps(out, indent=1))
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
