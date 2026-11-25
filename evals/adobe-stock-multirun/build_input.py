#!/usr/bin/env python3
"""Build the identical read-only input for the Adobe Stock multirun eval.

Reads the frozen campaign snapshot under input/ and emits
input.json — the single JSON document embedded verbatim in brief.md.
Deterministic: same inputs -> same bytes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
INP = HERE / "input"


def load(name):
    return json.loads((INP / name).read_text())


def qc_sections():
    """Map asset-id -> list of QC decision/relevant lines from
    40-qc-review.md. Sections are '## <heading>'; a section belongs to
    every asset id mentioned in its heading, plus ids named in the
    first prose line."""
    text = (INP / "40-qc-review.md").read_text()
    sections = []
    cur_head, cur = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur_head is not None:
                sections.append((cur_head, "\n".join(cur)))
            cur_head, cur = line[3:].strip(), []
        else:
            cur.append(line)
    if cur_head is not None:
        sections.append((cur_head, "\n".join(cur)))

    out = {}
    for head, body in sections:
        ids = set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)+", head))
        # keep only ids that look like asset ids (contain a digit or
        # known prefixes) to avoid matching lane names
        ids = {i for i in ids if re.search(r"\d", i) or
               i.startswith(("comparison-", "remote-work-"))}
        # decision-ish lines only — keeps the distilled input compact
        keep = []
        for ln in body.splitlines():
            if re.search(r"decision|qc_|sha|reject|revise|keep|pending|"
                         r"photoreal|sharpness|landed|provider|lane",
                         ln, re.I):
                keep.append(ln.strip()[:220])
        for aid in ids:
            out.setdefault(aid, [])
            for ln in keep[:14]:
                if ln not in out[aid]:
                    out[aid].append(ln)
    return out


# Canonical human-QC verdicts, distilled from SESSION.json comparison
# fields + 40-qc-review.md decision lines + per-asset manifests.
# This is eval ground truth: the brief instructs arms to honor these.
QC_DECISIONS = {
    "remote-work-home-office-001": "keep_for_comparison",
    "comparison-b-sharp-leaves": "revise",
    "comparison-c-omen-sdxl": "reject_for_photorealism",
    "comparison-e-cf-flux-schnell": "revise",
    "comparison-d-omen-sdxl-q8": "revise",
    "comparison-d-x4": "pending_visual_qc",
    "comparison-d-x4-sharp40": "pending_visual_qc",
    "comparison-d-x4-sharp60": "pending_visual_qc",
    "comparison-g-omen-sdxl-q8-wallfix": "pending_visual_qc",
    "comparison-e-gemini-wallfix": "revise",
    "comparison-e-gemini-fix2": "revise",
    "comparison-e-gemini-fix3-region": "revise",
    "comparison-e-gemini-fix4-wheels": "pending_visual_qc",
    "comparison-e-omen-sdxl-inpaint-wheels": "pending_visual_qc",
    "comparison-e-cf-inpaint-wheels": "pending_visual_qc",
    "comparison-h-omen-sdxl-q8-cprompt": "pending_visual_qc",
}


def manifest_for(asset_id):
    for f in sorted((INP / "manifests").glob(f"*/{asset_id}.manifest.json")):
        return json.loads(f.read_text())
    for f in sorted((INP / "manifests").glob(f"*/asset-manifest.json")):
        d = json.loads(f.read_text())
        if d.get("asset_id") == asset_id or d.get("id") == asset_id:
            return d
    # single asset-manifest dir fallback
    for d in sorted((INP / "manifests").iterdir()):
        if d.is_dir() and d.name == asset_id:
            for f in d.glob("*.json"):
                return json.loads(f.read_text())
    return {}


def main():
    session = load("SESSION.json")
    run = load("RUN.json")
    index = load("assets.json")
    status = load("campaign-status.json")
    qc = qc_sections()

    run_assets = {a.get("id"): a for a in run.get("assets", [])}
    idx_assets = {a.get("id"): a for a in index.get("items", [])}

    assets = []
    for aid in session.get("asset_ids", []):
        ra, ia = run_assets.get(aid, {}), idx_assets.get(aid, {})
        man = manifest_for(aid)
        meta = man.get("meta") or {}
        rec = {
            "asset_id": aid,
            "in_run_index": aid in run_assets or aid in idx_assets,
            "provider": ra.get("provider") or ia.get("provider")
                        or man.get("provider"),
            "job_id": ra.get("job_id") or man.get("job_id"),
            "sha256": ra.get("sha256") or man.get("sha256"),
            "dimensions": ra.get("dimensions")
                          or (f"{ra.get('width')}x{ra.get('height')}"
                              if ra.get("width") else None)
                          or man.get("dimensions") or man.get("size"),
            "bytes": ra.get("bytes") or man.get("bytes"),
            "has_preview_url": bool(ra.get("preview_url")
                                    or ia.get("preview_url")
                                    or man.get("preview_url")),
            "has_thumbnail_url": bool(ra.get("thumbnail_url")
                                      or ia.get("thumbnail_url")
                                      or man.get("thumbnail_url")),
            "preview_url": ra.get("preview_url") or ia.get("preview_url"),
            "status": ra.get("status") or ia.get("status"),
            "landed_at": ra.get("landed_at") or man.get("landed_at")
                         or man.get("completed_at"),
        }
        if man.get("prompt"):
            rec["render_prompt"] = man["prompt"]
        if man.get("negative_prompt"):
            rec["negative_prompt"] = man["negative_prompt"]
        if man.get("model"):
            rec["model"] = man["model"]
        for k in ("model_id", "runtime", "pack", "endpoint", "request_id",
                  "campaign"):
            if man.get(k) and k not in rec:
                rec[k] = man[k]
        if meta.get("postprocess_of"):
            rec["derived_from"] = meta["postprocess_of"]
        if man.get("status"):
            rec["manifest_status"] = man["status"]
        man_qc = man.get("qc") or {}
        if man_qc.get("decision"):
            rec["manifest_qc_decision"] = man_qc["decision"]
        qc_lines = qc.get(aid) or qc.get(aid.replace("comparison-", "")) or []
        if qc_lines:
            rec["qc_notes"] = qc_lines
        if aid in QC_DECISIONS:
            rec["qc_decision"] = QC_DECISIONS[aid]
        assets.append({k: v for k, v in rec.items() if v is not None})

    baseline = assets[0] if assets else {}
    doc = {
        "campaign_id": session.get("session_id"),
        "title": session.get("title"),
        "status": session.get("status"),
        "current_stage": session.get("current_stage"),
        "snapshot_at": "2026-11-25T07:18Z (campaign-status receipt)",
        "pending_decisions": session.get("pending_decisions"),
        "baseline_asset_id": (session.get("comparison") or {})
                             .get("baseline_asset_id"),
        "qc_outcomes": {
            "candidate_qc": (session.get("comparison") or {})
                            .get("candidate_qc_decision"),
            "revision_qc": (session.get("comparison") or {})
                           .get("revision_qc_decision"),
        },
        "baseline_prompt": baseline.get("render_prompt"),
        "baseline_negative_prompt": baseline.get("negative_prompt"),
        "assets": assets,
        "policy": {
            "adobe_upload": False,
            "note": "read-only analysis; no upload, generation, "
                    "licensing, or card mutation is permitted",
        },
    }
    (HERE / "input.json").write_text(json.dumps(doc, indent=1) + "\n")
    print(f"assets={len(assets)} bytes="
          f"{(HERE / 'input.json').stat().st_size}")


if __name__ == "__main__":
    main()
