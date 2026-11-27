#!/usr/bin/env python3
"""Hand-label the fresh 60-card spec-aware set and emit a Decisions payload.

Labels are from brief+spec alone, using the same readiness rubric as earlier
arms: READY needs a concrete action/deliverable and target with no external
gate; NOT_READY covers approval/decision gates, blocked dependencies,
credentials/maintenance windows, umbrella/audit-only scopes, and descriptive
or already-done cards. No threshold tuning, no API calls, no secrets.
"""
import collections
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
pool = json.load(open(RESULTS / "g4-decision-gate-spec60-candidates.json"))["pool"]
by_n = {c["n"]: c for c in pool}

# n: (READY?, family, reason)
LABELS = {
    1: (True, "ready", "four concrete pieces plus a named pilot card and first target"),
    2: (True, "ready", "named reconnect fix in a named file with a repro and voice non-regression test"),
    3: (True, "ready", "find the plug filter, fix it, add a named unit test"),
    4: (True, "ready", "numbered standard + invite/redeem/approve build steps with named surfaces"),
    5: (True, "ready", "named routing rule and pending-store shape with an existing approver surface"),
    6: (False, "approval_gated", "spec makes work conditional on Tony choosing target, soundtrack and subtitle treatment"),
    7: (False, "descriptive_only", "already done in a named commit; only optional follow-ups remain"),
    8: (True, "ready", "fix named session-create path failure with approved secret path for credentials"),
    9: (True, "ready", "hybrid delivery contract chosen per Tony with named relay changes and done condition"),
    10: (True, "ready", "named files, flags and test/deploy steps for the text provider path"),
    11: (False, "approval_gated", "explicit HUMAN-GATED tail; production restart needs approval and key decision"),
    12: (True, "ready", "duplicate action key on a named line; decide, remove, validate"),
    13: (True, "ready", "Phase 1 only, named script/tests, detection and one request with a re-raise guard"),
    14: (True, "ready", "three named missing doc paths; write the doc or fix the registry"),
    15: (True, "ready", "three named artifacts to locate/land on named hosts"),
    16: (False, "approval_gated", "restore cards only after current evidence; dirty mirror must not be touched"),
    17: (True, "ready", "fix injected test overwrite with named options and post-run cleanup"),
    18: (True, "ready", "harden named render function and audit siblings against malformed cards"),
    19: (False, "approval_gated", "part 2 needs obtaining/registering Plesk or SSH credentials for h3"),
    20: (False, "approval_gated", "stateful HA move explicitly needs a maintenance window"),
    21: (True, "ready", "failing named test with a stated done-condition: repair the rotted drop or retire it"),
    22: (False, "approval_gated", "claude interactive OAuth login needs Tony unless a setup-token is supplied"),
    23: (True, "ready", "sweep named units/args to :11027 with an explicit migration-completion step"),
    24: (True, "ready", "two named deliverables and a machine-checkable done-condition"),
    26: (False, "descriptive_only", "assessment with suggested levers; no lever selected or scoped for dispatch"),
    27: (True, "ready", "define L0-L3 layers and verifier, apply first to host assessment"),
    28: (True, "ready", "named lane catalog and a monthly savings report contract"),
    30: (True, "ready", "fix the named keyword set and validate against the two named false positives"),
    31: (True, "ready", "priority-aware claim order with starvation guard and named test coverage"),
    32: (True, "ready", "Tony answered proceed; approved strategy and concrete deliverables"),
    33: (True, "ready", "enable named flag and hybrid recall path with a verified done-condition"),
    34: (True, "ready", "named script cap under a wall-clock budget and a oneshot verification"),
    35: (True, "ready", "inventory named producers, repoint to /inbox, verify an alert lands on the writer"),
    37: (False, "approval_gated", "account/billing state and Tony-side key or billing decision; no local fix"),
    38: (True, "ready", "provision per-consumer users/tokens with a named helper and kill the old token"),
    39: (True, "ready", "queued request with named new report and cross-link deliverables"),
    40: (True, "ready", "one-line canary file in a named path with an exact commit message; do not push"),
    41: (True, "ready", "living doc with four named experiments to run and record"),
    42: (True, "ready", "sandbox with explicit isolation, allowed paths and verification steps"),
    43: (False, "approval_gated", "design doc is written for review; architecture is proposed, not authorized"),
    45: (True, "ready", "Tony decision recorded as adopt; implement envelope staging with regression tests"),
    46: (False, "approval_gated", "explicit product decision: ask KK to accept a pilot before profile changes"),
    48: (True, "ready", "planning package is batched work before the later Tony ask"),
    49: (True, "ready", "named executor and pack inputs/outputs with an explicit no-publish, no-spend gate"),
    50: (True, "ready", "spike questions first with named measurement and a bounded ada-dev prototype"),
    51: (True, "ready", "Phase 1 only with named digest change, WP identities and verification"),
    52: (True, "ready", "three named scoring bugs with named files and regression cases"),
    54: (True, "ready", "named snapshot script and page family with a verified done-condition"),
    55: (True, "ready", "five numbered rename steps with verification"),
    56: (True, "ready", "named narration layer on an existing digest with format and lane gates"),
    57: (False, "descriptive_only", "feasibility note on a research question; no stack utility and no chosen build"),
    58: (False, "umbrella_or_audit", "multi-surface Nest fabric spanning every input/output lane; no bounded first deliverable"),
    60: (False, "approval_gated", "spec says a Tony decision is needed and a prod host/npm change needs explicit approval"),
    61: (False, "approval_gated", "irreversible partition change with delete only after Tony confirms"),
    62: (True, "ready", "stale project path with a named settings fix and acceptance check"),
    68: (False, "umbrella_or_audit", "fleet-wide command/MCP audit with no selected candidate or bounded deliverable"),
    71: (False, "blocked_by", "explicit blocked_by gate on primer-efficacy-measurement; report must exist first"),
    72: (False, "approval_gated", "spec forbids auto-install without confirming after diagnosis"),
    84: (False, "approval_gated", "pairing needs a one-time Google auth code generated by Tony"),
    88: (False, "umbrella_or_audit", "end-to-end UX redesign across all lifecycle stages, not a bounded task"),
}
assert len(LABELS) == 60, len(LABELS)
assert set(LABELS) <= set(by_n), set(LABELS) - set(by_n)
assert sum(1 for v in LABELS.values() if v[0]) == 40

items = []
for n in sorted(LABELS):
    c = by_n[n]
    label, kind, reason = LABELS[n]
    items.append({"n": n, "id": c["id"], "brief": c["brief"], "spec": c["spec"],
                  "source": c["source"], "label": label, "kind": kind,
                  "label_reason": reason})

assert len({c["id"] for c in items}) == 60
ds = {
    "schema": "decision-gate-spec60",
    "date": "2026-11-27",
    "source": "origin/master snapshot; 60 card IDs disjoint by ID and normalized brief from five prior sets",
    "label_rule": "Hand audited from brief+spec alone. READY = concrete action/deliverable and target with no external gate; NOT_READY = approval/decision gate, blocked dependency, credentials/maintenance window, umbrella/audit-only scope, or descriptive/done-only text.",
    "counts": {"ready": 40, "not_ready": 20},
    "families": dict(collections.Counter(r["kind"] for r in items)),
    "items": items,
}
json.dump(ds, open(RESULTS / "g4-decision-gate-spec60-dataset.json", "w"), indent=2)

lines = []
for r in items:
    lines.append(f"Card {r['n']} [{r['id']}]\nBRIEF: {r['brief']}\nSPEC: {r['spec']}")
questions = {}
for r in items:
    n = r["n"]
    questions[f"ready_{n}"] = {
        "type": "noul",
        "instructions": (
            f"Is card {n} ready for dispatch now? Use both its brief and its spec. Ready means a "
            "concrete action/deliverable and target are stated with enough detail to act without "
            "another source or an external decision; not ready means it is gated on approval or a "
            "human decision, a blocked dependency, credentials or a maintenance window, an umbrella/"
            "audit-only scope, or is descriptive/already done."
        ),
    }
payload = {"model": "gemini-decision-1",
           "input": "Kanban cards with their briefs and specs:\n" + "\n\n".join(lines),
           "questions": questions}
json.dump(payload, open(RESULTS / "g4-decision-gate-spec60-payload.json", "w"), indent=2)
review = "\n".join(("R" if r["label"] else "N") + f" {r['n']}. [{r['id']}] {r['kind']}: {r['label_reason']}"
                   for r in items)
(RESULTS / "g4-decision-gate-spec60-labels.txt").write_text(review + "\n")
print("selected", ds["counts"], ds["families"], "questions", len(questions),
      "input chars", len(payload["input"]))
