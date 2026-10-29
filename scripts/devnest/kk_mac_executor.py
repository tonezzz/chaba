#!/usr/bin/env python3
"""Explicit executor contract for the kk_mac_local lane (card
kk-mac-jev-adapter-integration).

This is the bounded, read-only executor for opportunistic work on KK-Mac
(KKs-Mac-Studio, tailnet). The contract:

  admission   fresh Ada Nest heartbeat (kk_mac_admission.snapshot —
              heartbeat age <= max_age_s, ollama_ok=true, disk over the
              threshold, node not busy/overloaded) AND a bounded task
              class: summary, operator_brief, structured_extract,
              safe_route. Anything else is a contract violation.
  execute     through scripts/devnest/kk_mac_llm.py — the fixed
              ssh+ollama /api/generate call. There is no shell, no code
              mutation, no credential path, no destructive action and no
              publish anywhere in this lane; the task-class bound is the
              safety surface.
  persist     a usage/admission/response artifact into the dispatch
              worktree (under ARTIFACT_ROOTS only) plus
              <taskdir>/kk_mac_result.json — durable even when the run
              itself is not mergeable.
  verify      independently: the response is checked against the card's
              declared expect block (JSON parses for the JSON classes,
              required keys, enum members, required fact substrings).
              The verifier never asks the model and never trusts its
              self-report.
  verdict     pass    — artifact landed AND verifier passed; only then
                        may the card's verified gate run.
              fallback— lane conditions (stale/absent heartbeat, ollama
                        down, node busy, ssh failure, invalid output):
                        fail closed and hand the card to the next lane.
              fail    — contract violation (unadmitted class, artifact
                        path outside the roots): held for a human, never
                        silently routed.

CLI:
    run     --card C --task-id T --task-class X --worktree W
            --taskdir D [--prompt TXT|--prompt-file F] [--expect-file E]
            [--artifact RELPATH] [--model M]
    admit   --task-class X [--prompt TXT|--prompt-file F]
    verify  --task-class X --response-file F [--expect-file E]
    probe   (heartbeat liveness only — used by hosts that cannot serve
             the lane to decide whether a card needs its fallback)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import kk_mac_admission
    from . import kk_mac_llm
except ImportError:  # direct script / spec-file loading
    _d = str(Path(__file__).resolve().parent)
    if _d not in sys.path:
        sys.path.insert(0, _d)
    import kk_mac_admission
    import kk_mac_llm

LANE = "kk_mac_local"
TASK_CLASSES = frozenset(kk_mac_llm.ALLOWED_TASKS)
# task classes whose response is a JSON object (fences tolerated)
JSON_CLASSES = frozenset(
    {"operator_brief", "structured_extract", "safe_route"})
# repo-relative roots the persisted artifact may land under — never
# scripts/, secrets, or anything executable/deployable
ARTIFACT_ROOTS = ("evals/kk-mac-lane/out/", "reports/", "docs/reports/")
DEFAULT_ARTIFACT_ROOT = "evals/kk-mac-lane/out/"
DEFAULT_MODEL = "qwen3:8b"
MAX_RESPONSE_CHARS = 20000
FALLBACK = "__kk_mac_fallback__"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def artifact_allowed(path: str) -> bool:
    """The artifact may only land under the declared roots — this is the
    no-mutation boundary for the lane's only durable write."""
    p = (path or "").strip().lstrip("/")
    if not p or ".." in p.split("/") or p.startswith("/"):
        return False
    return any(p == r.rstrip("/") or p.startswith(r)
               for r in ARTIFACT_ROOTS)


def probe(**kwargs) -> dict:
    """Heartbeat liveness only — {eligible, reasons, ...}. A probe that
    cannot run fails closed (ineligible), which routes callers to the
    fallback lane rather than blocking them."""
    try:
        return kk_mac_admission.snapshot(**kwargs)
    except Exception as exc:
        return {"host": kwargs.get("host", "KKs-Mac-Studio"),
                "eligible": False, "lane": LANE,
                "reasons": [f"probe_failed:{type(exc).__name__}"]}


def admission_gate(task_class: str, prompt: str,
                   *, snap: dict | None = None) -> dict:
    """Contract admission = bounded task declaration AND live heartbeat.
    reasons prefixed 'task:' are declaration problems; the rest come
    from the heartbeat gate."""
    reasons = []
    if task_class not in TASK_CLASSES:
        reasons.append(f"task:class_not_admitted:{task_class}")
    if not (prompt or "").strip():
        reasons.append("task:prompt_empty")
    elif len(prompt) > kk_mac_llm.MAX_PROMPT_CHARS:
        reasons.append("task:prompt_too_long")
    gate = probe() if snap is None else snap
    reasons += [str(r) for r in gate.get("reasons") or []]
    return {"eligible": not reasons, "reasons": reasons, "gate": gate}


def extract_json(text: str) -> dict | None:
    """Parse a JSON object out of the response — tolerate ``` fences and
    leading/trailing prose the small models add."""
    t = (text or "").strip()
    if not t:
        return None
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"```\s*$", "", t).strip()
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except (TypeError, json.JSONDecodeError):
        pass
    i, j = t.find("{"), t.rfind("}")
    if 0 <= i < j:
        try:
            v = json.loads(t[i:j + 1])
            return v if isinstance(v, dict) else None
        except (TypeError, json.JSONDecodeError):
            return None
    return None


def verify(task_class: str, response: str, expect: dict | None) -> dict:
    """Independent schema + fact check. The verifier is deterministic —
    it never calls the model and only judges the response text against
    the task envelope's declared expectations:

      expect.required_keys  keys that must exist in the JSON object
      expect.enums          {key: [allowed values]} membership
      expect.facts          literal substrings that must appear in the
                            response (the facts the evidence requires)

    -> {verdict: pass|fail, checks: {name: bool}}"""
    expect = expect or {}
    checks = {}
    resp = response or ""
    checks["response_nonempty"] = bool(resp.strip())
    checks["response_bounded"] = len(resp) <= MAX_RESPONSE_CHARS
    obj = extract_json(resp) if task_class in JSON_CLASSES else None
    if task_class in JSON_CLASSES:
        checks["json_parses"] = obj is not None
    for k in expect.get("required_keys") or []:
        checks[f"required_key:{k}"] = \
            isinstance(obj, dict) and k in obj
    for k, allowed in (expect.get("enums") or {}).items():
        checks[f"enum:{k}"] = \
            isinstance(obj, dict) and obj.get(k) in (allowed or [])
    hay = resp
    if isinstance(obj, dict):
        hay += "\n" + json.dumps(obj, ensure_ascii=False)
    for f in expect.get("facts") or []:
        checks[f"fact:{str(f)[:40]}"] = \
            str(f).lower() in hay.lower()
    ok = bool(checks) and all(checks.values())
    return {"verdict": "pass" if ok else "fail",
            "checks": checks,
            "verified_at": now_iso()}


def run_contract(task: dict, *, run_task=None,
                 snap: dict | None = None,
                 worktree: Path | None = None,
                 taskdir: Path | None = None) -> dict:
    """Run the full contract for one task. task keys: id, card,
    task_class, prompt, expect (dict), artifact (repo-relative path),
    model, host. Returns the durable result record — also written to
    <taskdir>/kk_mac_result.json, verdict to <taskdir>/verdict.json."""
    run_task = run_task or kk_mac_llm.run_task
    tc = str(task.get("task_class") or "")
    prompt = str(task.get("prompt") or "")
    expect = task.get("expect") or {}
    art = str(task.get("artifact") or "").strip()
    model = str(task.get("model") or DEFAULT_MODEL)
    result = {"executor": LANE, "card": task.get("card"),
              "task_id": task.get("id"), "task_class": tc,
              "model": model, "at": now_iso(),
              "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
              "prompt_chars": len(prompt),
              "artifact": art or None, "artifact_written": False,
              "verdict": "fail", "reasons": [], "checks": {},
              "admission": None, "usage": None, "response": None}
    # contract violations fail closed — never silently re-route a task
    # the bounded lane was meant to refuse
    if tc not in TASK_CLASSES:
        result["reasons"].append(f"class_not_admitted:{tc}")
    if art and not artifact_allowed(art):
        result["reasons"].append(f"artifact_outside_roots:{art}")
    if not prompt.strip():
        result["reasons"].append("prompt_empty")
    if result["reasons"]:
        _persist(result, worktree, taskdir)
        return result
    if len(prompt) > kk_mac_llm.MAX_PROMPT_CHARS:
        result["verdict"] = "fallback"
        result["reasons"].append("prompt_too_long")
        _persist(result, worktree, taskdir)
        return result
    gate = admission_gate(tc, prompt, snap=snap)
    result["admission"] = gate["gate"]
    if not gate["eligible"]:
        result["verdict"] = "fallback"
        result["reasons"] = gate["reasons"]
        _persist(result, worktree, taskdir)
        return result
    try:
        res = run_task(tc, prompt, model=model,
                       host=str(task.get("host") or "kk-mac"))
    except Exception as exc:
        result["verdict"] = "fallback"
        result["reasons"].append(
            f"executor_error:{type(exc).__name__}:{exc}"[:300])
        _persist(result, worktree, taskdir)
        return result
    if not res.get("ok"):
        result["verdict"] = "fallback"
        result["reasons"] = [
            "run_declined:" + ",".join(
                (res.get("admission") or {}).get("reasons") or ["?"])]
        _persist(result, worktree, taskdir)
        return result
    result["usage"] = res.get("usage")
    result["response"] = res.get("response") or ""
    v = verify(tc, result["response"], expect)
    result["checks"] = v["checks"]
    if v["verdict"] != "pass":
        # invalid output -> fail closed, hand off to the next lane
        failed = [k for k, ok_ in v["checks"].items() if not ok_]
        result["verdict"] = "fallback"
        result["reasons"] = ["invalid_output:" + ",".join(failed[:6])]
        _persist(result, worktree, taskdir)
        return result
    result["verdict"] = "pass"
    _persist(result, worktree, taskdir)
    return result


def _persist(result: dict, worktree: Path | None,
             taskdir: Path | None) -> None:
    """Durable evidence: the repo artifact (usage+admission+response+
    verdict) under the worktree's allowed roots, plus the taskdir
    copies the close-out reads."""
    art = result.get("artifact")
    if worktree and art and artifact_allowed(art):
        try:
            result["artifact_written"] = True
            dest = Path(worktree) / art
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(result, indent=1,
                                       ensure_ascii=False) + "\n")
        except OSError:
            result["artifact_written"] = False
    if taskdir:
        try:
            td = Path(taskdir)
            td.mkdir(parents=True, exist_ok=True)
            (td / "kk_mac_result.json").write_text(
                json.dumps(result, indent=1, ensure_ascii=False))
            (td / "verdict.json").write_text(json.dumps({
                "verdict": result.get("verdict"),
                "checks": result.get("checks") or {},
                "reasons": result.get("reasons") or [],
                "artifact": art,
                "verified_at": now_iso()}, indent=1))
        except OSError:
            pass


def _load_json_file(path: str) -> dict:
    try:
        v = json.loads(Path(path).read_text())
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _read_prompt(args) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text()
    return args.prompt or ""


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("run", "admit"):
        p = sub.add_parser(name)
        p.add_argument("--task-class", required=True)
        p.add_argument("--prompt", default="")
        p.add_argument("--prompt-file", default="")
    sub.choices["run"].add_argument("--card", default="")
    sub.choices["run"].add_argument("--task-id", default="")
    sub.choices["run"].add_argument("--worktree", default="")
    sub.choices["run"].add_argument("--taskdir", default="")
    sub.choices["run"].add_argument("--expect-file", default="")
    sub.choices["run"].add_argument("--artifact", default="")
    sub.choices["run"].add_argument("--model", default=DEFAULT_MODEL)
    sub.choices["run"].add_argument("--host", default="kk-mac")
    vp = sub.add_parser("verify")
    vp.add_argument("--task-class", required=True)
    vp.add_argument("--response-file", required=True)
    vp.add_argument("--expect-file", default="")
    sub.add_parser("probe")
    args = parser.parse_args()

    if args.cmd == "probe":
        print(json.dumps(probe(), sort_keys=True))
        return 0
    if args.cmd == "admit":
        out = admission_gate(args.task_class, _read_prompt(args))
        print(json.dumps(out, sort_keys=True, default=str))
        return 0 if out["eligible"] else 2
    if args.cmd == "verify":
        resp = Path(args.response_file).read_text()
        out = verify(args.task_class, resp,
                     _load_json_file(args.expect_file))
        print(json.dumps(out, sort_keys=True))
        return 0 if out["verdict"] == "pass" else 2
    # run
    task = {"id": args.task_id, "card": args.card,
            "task_class": args.task_class,
            "prompt": _read_prompt(args),
            "expect": _load_json_file(args.expect_file),
            "artifact": args.artifact, "model": args.model,
            "host": args.host}
    result = run_contract(
        task,
        worktree=Path(args.worktree) if args.worktree else None,
        taskdir=Path(args.taskdir) if args.taskdir else None)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
