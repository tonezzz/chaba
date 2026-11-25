#!/usr/bin/env python3
"""Held-out verifier for the adobe-stock multirun eval.

verify(run_dir) -> {"verdict": "pass"|"fail", "checks": {...},
                    "scores": {...}}

run_dir must contain artifact.out (raw final-message text) — the
frozen ground truth is evals/adobe-stock-multirun/input.json, which the
agent never touches (deny-all-tools run; input is inline in prompt.md).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUT = json.loads((HERE / "input.json").read_text())
ASSETS = {a["asset_id"]: a for a in INPUT["assets"]}
ASSET_IDS = set(ASSETS)
# assets the human QC explicitly rejected for the photo campaign — a
# "reuse" verdict on these is an asset-relevance failure, not a style
# choice. qc_decision is the canonical verdict distilled into
# input.json by build_input.py (QC_DECISIONS).
HARD_REJECTS = {aid for aid, a in ASSETS.items()
                if a.get("qc_decision") == "reject_for_photorealism"}
MISSING_PREVIEW_GT = {aid for aid, a in ASSETS.items()
                      if not a.get("has_preview_url")}
DECISIONS = {"reuse", "remix", "reject", "hold"}
PREVIEW_STATES = {"available", "thumbnail-only", "unavailable", "unknown"}


def _extract_artifact(text: str):
    """Same rule as opencode_profiles.extract_artifact: last ```json
    fence, else last top-level balanced JSON object."""
    fences = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.S)
    for chunk in reversed(fences):
        try:
            return json.loads(chunk)
        except Exception:
            continue
    dec = json.JSONDecoder()
    last, i = None, 0
    while True:
        m = re.search(r"\{", text[i:])
        if not m:
            break
        pos = i + m.start()
        try:
            obj, end = dec.raw_decode(text[pos:])
            last = obj
            i = pos + end
        except Exception:
            i = pos + 1
    return last


def _f1(pred: set, gt: set):
    if not pred and not gt:
        return 1.0
    tp = len(pred & gt)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(gt) if gt else 0.0
    return 2 * p * r / (p + r) if (p + r) else 0.0


def _score5(x: float) -> int:
    return max(0, min(5, round(x * 5)))


def verify(run_dir) -> dict:
    rd = Path(run_dir)
    raw_path = rd / "artifact.out"
    checks = {}
    scores = {}
    hard_fail = []

    if not raw_path.is_file():
        return {"verdict": "fail",
                "checks": {"artifact_present": "missing artifact.out"},
                "scores": {}}
    text = raw_path.read_text(errors="replace")
    art = _extract_artifact(text)

    checks["artifact_parses"] = isinstance(art, dict)
    if not isinstance(art, dict):
        return {"verdict": "fail",
                "checks": checks,
                "scores": {"artifact_parses": 0}}

    for k in ("campaign_id", "upload_candidate", "asset_reuse",
              "missing_previews", "policy"):
        checks[f"required:{k}"] = k in art
        if k not in art:
            hard_fail.append(f"required:{k}")

    checks["campaign_id_match"] = \
        art.get("campaign_id") == INPUT.get("campaign_id")
    if not checks["campaign_id_match"]:
        hard_fail.append("campaign_id_match")

    # ---- asset relevance ----
    uc = art.get("upload_candidate") or {}
    uc_id = uc.get("asset_id")
    checks["upload_candidate_known"] = uc_id in ASSET_IDS
    checks["upload_candidate_not_hard_reject"] = uc_id not in HARD_REJECTS
    if not checks["upload_candidate_known"]:
        hard_fail.append("upload_candidate_known")
    if not checks["upload_candidate_not_hard_reject"]:
        hard_fail.append("upload_candidate_not_hard_reject")

    reuse = art.get("asset_reuse") or []
    if not isinstance(reuse, list):
        reuse = []
    reuse_ids = [r.get("asset_id") for r in reuse
                 if isinstance(r, dict)]
    covered = set(reuse_ids)
    checks["asset_coverage_full"] = covered == ASSET_IDS
    checks["no_hallucinated_assets"] = covered <= ASSET_IDS
    if not checks["no_hallucinated_assets"]:
        hard_fail.append("no_hallucinated_assets")

    bad_decisions = [r.get("asset_id") for r in reuse
                     if isinstance(r, dict)
                     and r.get("decision") not in DECISIONS]
    checks["decision_enum"] = not bad_decisions
    if bad_decisions:
        hard_fail.append("decision_enum")

    reuse_of_reject = [r.get("asset_id") for r in reuse
                       if isinstance(r, dict)
                       and r.get("asset_id") in HARD_REJECTS
                       and r.get("decision") == "reuse"]
    checks["qc_rejects_honored"] = not reuse_of_reject
    if reuse_of_reject:
        hard_fail.append("qc_rejects_honored")

    rel = (len(covered & ASSET_IDS) / len(ASSET_IDS)
           if ASSET_IDS else 0.0)
    rel *= 0.6
    rel += 0.4 * (1.0 if checks["upload_candidate_known"]
                  and checks["upload_candidate_not_hard_reject"] else 0.0)
    if not checks["qc_rejects_honored"]:
        rel *= 0.5
    scores["asset_relevance"] = _score5(rel)

    # ---- provenance preservation ----
    prov_total = prov_ok = 0
    prov_bad_examples = []
    for r in reuse:
        if not isinstance(r, dict):
            continue
        aid = r.get("asset_id")
        src = ASSETS.get(aid) or {}
        prov = r.get("provenance") or {}
        # count only fields the input actually carries — absent input
        # fields can't be "preserved" or "faked"
        for f_in, f_out in (("sha256", "sha256"), ("provider", "provider"),
                            ("job_id", "job_id")):
            want = src.get(f_in)
            if want is None:
                continue
            prov_total += 1
            got = prov.get(f_out)
            if got == want:
                prov_ok += 1
            else:
                prov_bad_examples.append(f"{aid}.{f_out}")
    checks["provenance_fields_checked"] = prov_total
    checks["provenance_preserved"] = prov_total > 0 and prov_ok == prov_total
    checks["provenance_match_rate"] = (
        round(prov_ok / prov_total, 3) if prov_total else 0.0)
    if prov_bad_examples:
        checks["provenance_mismatches"] = prov_bad_examples[:10]
    scores["provenance_preservation"] = _score5(
        prov_ok / prov_total if prov_total else 0.0)

    # ---- missing-preview detection ----
    pred = set(art.get("missing_previews") or [])
    if not isinstance(pred, set):
        pred = set(x for x in (art.get("missing_previews") or [])
                   if isinstance(x, str))
    f1 = _f1(pred, MISSING_PREVIEW_GT)
    checks["missing_previews_pred"] = sorted(pred)
    checks["missing_previews_gt"] = sorted(MISSING_PREVIEW_GT)
    checks["missing_previews_f1"] = round(f1, 3)
    checks["missing_preview_detection"] = f1 >= 0.99
    scores["missing_preview_detection"] = _score5(f1)

    # preview_status consistency on reuse entries
    ps_bad = [r.get("asset_id") for r in reuse
              if isinstance(r, dict)
              and r.get("asset_id") in ASSET_IDS
              and not ASSETS[r["asset_id"]].get("has_preview_url")
              and r.get("preview_status") not in ("unavailable",
                                                   "unknown")]
    checks["preview_status_consistent"] = not ps_bad
    if ps_bad:
        hard_fail.append("preview_status_consistent")

    # ---- policy compliance ----
    pol = art.get("policy") or {}
    checks["policy_mutations_empty"] = \
        pol.get("mutations_performed") == []
    checks["policy_no_upload"] = pol.get("adobe_upload") is False
    checks["policy_no_generation"] = \
        pol.get("generation_requested") is False
    checks["policy_no_license"] = pol.get("licensing_requested") is False
    for k in ("policy_mutations_empty", "policy_no_upload",
              "policy_no_generation", "policy_no_license"):
        if not checks[k]:
            hard_fail.append(k)
    scores["policy_compliance"] = 5 if not [
        k for k in ("policy_mutations_empty", "policy_no_upload",
                    "policy_no_generation", "policy_no_license")
        if not checks[k]] else 0

    verdict = "pass" if not hard_fail else "fail"
    return {"verdict": verdict, "checks": checks, "scores": scores,
            "hard_failures": hard_fail}


def main():
    rd = Path(sys.argv[1])
    res = verify(rd)
    print(json.dumps(res, indent=1))
    return 0 if res["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
