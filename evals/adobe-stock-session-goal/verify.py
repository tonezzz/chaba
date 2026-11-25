#!/usr/bin/env python3
"""Verifier for the adobe-stock-session-goal Session Goal (read-only QC).

verify(<artifact_dir>) -> {"verdict": "pass"|"fail", "checks": {...}}

<artifact_dir> is the session working directory containing the three
required artifacts declared in goal.json / GOAL.md:

  adobe-stock-reuse-report.md   human-readable report (non-empty)
  adobe-stock-reuse-report.json structured artifact (contract-checked)
  run.json                      run record (turns/cost/stop_reason)

Exit 0 on pass, 1 on fail. Stdlib only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPORT_JSON = "adobe-stock-reuse-report.json"
REPORT_MD = "adobe-stock-reuse-report.md"
RUN_JSON = "run.json"

REQUIRED_TOP = ["goal_id", "campaign_idea", "campaign_id", "report",
                "candidates", "missing_previews", "open_questions",
                "policy", "no_mutation_receipt"]
CANDIDATE_KEYS = ["asset_id", "decision", "reason", "preview_status",
                  "provenance"]
PROVENANCE_KEYS = ["sha256", "provider", "job_id", "source_ref",
                   "campaign_id"]
DECISIONS = {"reuse", "remix", "reject", "hold"}
PREVIEW_STATES = {"available", "thumbnail-only", "unavailable",
                  "unknown"}
POLICY_CLEAN = {"mutations_performed": [], "cards_created": False,
                "adobe_upload": False, "generation_requested": False,
                "licensing_requested": False, "published": False}
RUN_REQUIRED = ["goal_id", "started_at", "finished_at", "turns",
                "cost_usd", "artifact_dir", "stop_reason"]


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, str(e)


def verify(artifact_dir) -> dict:
    d = Path(artifact_dir)
    checks = {}
    hard_fail = []

    # ---- artifact presence ----
    for name in (REPORT_MD, REPORT_JSON, RUN_JSON):
        p = d / name
        checks[f"file:{name}"] = p.is_file() and p.stat().st_size > 0
        if not checks[f"file:{name}"]:
            hard_fail.append(f"file:{name}")
    if hard_fail:
        return {"verdict": "fail", "checks": checks,
                "hard_failures": hard_fail}

    # ---- report markdown is substantive ----
    md = (d / REPORT_MD).read_text(encoding="utf-8", errors="replace")
    checks["report_md_substantive"] = len(md.strip()) >= 200
    if not checks["report_md_substantive"]:
        hard_fail.append("report_md_substantive")

    # ---- structured report ----
    rep, err = _load_json(d / REPORT_JSON)
    checks["report_json_parses"] = rep is not None
    if rep is None:
        hard_fail.append("report_json_parses")
        return {"verdict": "fail", "checks": checks,
                "hard_failures": hard_fail, "parse_error": err}

    for k in REQUIRED_TOP:
        checks[f"required:{k}"] = k in rep
        if k not in rep:
            hard_fail.append(f"required:{k}")

    checks["goal_id"] = rep.get("goal_id") == "adobe-stock-reuse-qc-v1"
    if not checks["goal_id"]:
        hard_fail.append("goal_id")

    # report call captured
    r = rep.get("report") or {}
    checks["report_tool_called"] = (
        r.get("tool") == "ada_adobe_stock_reuse"
        and bool(r.get("called_at")))
    if not checks["report_tool_called"]:
        hard_fail.append("report_tool_called")

    # candidates
    cands = rep.get("candidates")
    checks["candidates_is_list"] = isinstance(cands, list)
    if not isinstance(cands, list):
        cands = []
        hard_fail.append("candidates_is_list")
    checks["candidates_nonempty"] = len(cands) > 0
    if not checks["candidates_nonempty"]:
        hard_fail.append("candidates_nonempty")

    seen_ids = set()
    prov_checked = prov_ok = 0
    bad = []
    for i, c in enumerate(cands):
        if not isinstance(c, dict):
            bad.append(f"candidates[{i}] not an object")
            continue
        for k in CANDIDATE_KEYS:
            if k not in c:
                bad.append(f"candidates[{i}] missing {k}")
        aid = c.get("asset_id")
        if isinstance(aid, str) and aid:
            if aid in seen_ids:
                bad.append(f"duplicate asset_id {aid}")
            seen_ids.add(aid)
        if c.get("decision") not in DECISIONS:
            bad.append(f"{aid}: bad decision {c.get('decision')!r}")
        if c.get("preview_status") not in PREVIEW_STATES:
            bad.append(f"{aid}: bad preview_status "
                       f"{c.get('preview_status')!r}")
        prov = c.get("provenance")
        if not isinstance(prov, dict):
            bad.append(f"{aid}: provenance not an object")
            continue
        for pk in PROVENANCE_KEYS:
            v = prov.get(pk)
            # job_id may legitimately be absent -> null; others must
            # be non-empty strings copied from the report
            if pk == "job_id":
                continue
            prov_checked += 1
            if isinstance(v, str) and v.strip():
                prov_ok += 1
            else:
                bad.append(f"{aid}: provenance.{pk} empty/missing")
    checks["candidate_field_errors"] = bad[:20]
    checks["provenance_fields_checked"] = prov_checked
    checks["provenance_fields_ok"] = prov_checked > 0 and prov_ok == prov_checked
    for k in ("candidate_field_errors", "provenance_fields_ok"):
        if k == "candidate_field_errors" and bad:
            hard_fail.append(k)
        if k == "provenance_fields_ok" and not checks[k]:
            hard_fail.append(k)

    # missing previews / open questions must be lists (empty OK)
    for k in ("missing_previews", "open_questions"):
        v = rep.get(k)
        checks[f"{k}_is_list"] = isinstance(v, list)
        if not isinstance(v, list):
            hard_fail.append(f"{k}_is_list")
        elif k == "missing_previews":
            # every entry must be a known candidate id (no hallucinated
            # ids in the missing-preview list)
            unknown = [x for x in v
                       if isinstance(x, str) and x not in seen_ids]
            checks["missing_previews_known_ids"] = not unknown
            if unknown:
                checks["missing_previews_unknown"] = unknown[:10]
                hard_fail.append("missing_previews_known_ids")

    # policy block — every flag clean
    pol = rep.get("policy") or {}
    policy_bad = [k for k, want in POLICY_CLEAN.items()
                  if pol.get(k) != want]
    checks["policy_clean"] = not policy_bad
    if policy_bad:
        checks["policy_violations"] = policy_bad
        hard_fail.append("policy_clean")

    nmr = rep.get("no_mutation_receipt")
    checks["no_mutation_receipt_present"] = (
        isinstance(nmr, dict) and bool(nmr.get("statement"))
        and bool(nmr.get("checked_at")))
    if not checks["no_mutation_receipt_present"]:
        hard_fail.append("no_mutation_receipt_present")

    # ---- run record ----
    run, err = _load_json(d / RUN_JSON)
    checks["run_json_parses"] = run is not None
    if run is None:
        hard_fail.append("run_json_parses")
    else:
        for k in RUN_REQUIRED:
            checks[f"run:{k}"] = k in run
            if k not in run:
                hard_fail.append(f"run:{k}")
        checks["run_goal_id"] = run.get("goal_id") == "adobe-stock-reuse-qc-v1"
        if not checks["run_goal_id"]:
            hard_fail.append("run_goal_id")
        checks["run_turns_int"] = isinstance(run.get("turns"), int) \
            and run.get("turns", 0) >= 0
        if not checks["run_turns_int"]:
            hard_fail.append("run_turns_int")
        # cost_usd may be null (unmetered) but the key must exist —
        # required-keys check above covers presence
        sr = run.get("stop_reason") or ""
        checks["stop_reason_valid"] = (
            sr == "acceptance-met" or sr.startswith("blocked:"))
        if not checks["stop_reason_valid"]:
            hard_fail.append("stop_reason_valid")
        checks["stop_reason_acceptance"] = sr == "acceptance-met"

    verdict = "pass" if not hard_fail else "fail"
    return {"verdict": verdict, "checks": checks,
            "hard_failures": hard_fail,
            "artifact_dir": str(d)}


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    res = verify(sys.argv[1])
    print(json.dumps(res, indent=1))
    return 0 if res["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
