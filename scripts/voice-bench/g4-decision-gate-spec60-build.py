#!/usr/bin/env python3
"""Build a fresh, disjoint 60-card set whose model input includes card specs.

Prior arms gave the judge only card briefs; several false approvals were
briefs whose real disposition lived in the spec. This arm gives the judge the
brief plus the spec verbatim, on 60 card IDs disjoint by ID and normalized
brief from all five prior sets. Labels are hand-audited from brief+spec alone.

No API calls; emits a review file, a dataset skeleton and a Decisions payload.
"""
import json
import re
from pathlib import Path

import yaml

RESULTS = Path(__file__).resolve().parent / "results"
BASE = Path("/tmp/opencode/cards-baseline/docs/ssot/kanban/cards")
PRIORS = [
    RESULTS / "g4-decision-gate-expanded-dataset.json",
    Path("/tmp/opencode/decision-gate-heldout-dataset.json"),
    RESULTS / "g4-decision-gate-heldout110-dataset.json",
    RESULTS / "g4-decision-gate-validation130-dataset.json",
    RESULTS / "g4-decision-gate-diverse60-dataset.json",
]

blocked_ids, blocked_briefs = set(), set()
for p in PRIORS:
    for it in json.load(open(p))["items"]:
        blocked_ids.add(it["id"])
        blocked_briefs.add(re.sub(r"\W+", " ", it["brief"].lower()).strip())

cards = {}
for folder in (BASE, BASE / "archive"):
    for f in sorted(folder.glob("*.yml")):
        cards.setdefault(f.stem, (f, "active" if folder == BASE else "archive"))

candidates = []
for cid, (f, source) in sorted(cards.items()):
    if cid in blocked_ids:
        continue
    try:
        d = yaml.safe_load(open(f)) or {}
    except yaml.YAMLError:
        continue
    brief = str(d.get("brief") or "").replace("\n", " ").strip()
    spec = str(d.get("spec") or "").replace("\n", " ").strip()
    norm = re.sub(r"\W+", " ", brief.lower()).strip()
    if not (100 <= len(brief) <= 600 and 300 <= len(spec) <= 2600):
        continue
    if norm in blocked_briefs:
        continue
    candidates.append({"id": cid, "brief": brief, "spec": spec, "source": source})

# Deterministic spread across the pool so the review file is not dominated by
# one alphabetical cluster; the final selection is made during hand labeling.
step = max(1, len(candidates) // 90)
pool = candidates[::step][:90]
for i, c in enumerate(pool, 1):
    c["n"] = i

review = "\n\n".join(
    f"[{c['n']}] {c['id']} ({c['source']})\nBRIEF: {c['brief']}\nSPEC: {c['spec'][:900]}"
    for c in pool
)
(RESULTS / "g4-decision-gate-spec60-review.txt").write_text(review + "\n")
json.dump({"schema": "decision-gate-spec60-candidates", "pool": pool},
          open(RESULTS / "g4-decision-gate-spec60-candidates.json", "w"), indent=2)
print("snapshot cards", len(cards), "blocked", len(blocked_ids),
      "eligible", len(candidates), "review pool", len(pool))
