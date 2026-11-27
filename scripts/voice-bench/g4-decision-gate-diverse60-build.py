#!/usr/bin/env python3
"""Build a diversity-focused third gate set (60 briefs, 20 READY / 40 NOT_READY).

Unlike the 130-brief validation set (65/70 negatives were 'read/check the note'
templates), this set deliberately excludes those templates and hand-audits
negatives from distinct families: explicit approval/human gates, deferred and
keep-or-close cards, smoke/fixture cards, no-op/informational alerts, umbrella/
tracker cards, and descriptive-only observations with no imperative in the
brief. Labels follow the same rubric the model is given: the brief alone must
state a concrete action/deliverable and target with no external gate.

Ambiguous cards found during the audit were dropped rather than relabeled to
fit a quota. Disjoint by card ID and normalized brief from all four prior sets.

No API calls; emits the dataset, a Decisions noul payload and a review file.
"""
import collections
import json
import re
from pathlib import Path
import yaml

RESULTS = Path(__file__).resolve().parent / "results"
CARDS_DIR = Path("/tmp/opencode/cards-baseline/docs/ssot/kanban/cards")
PRIORS = [
    RESULTS / "g4-decision-gate-expanded-dataset.json",
    Path("/tmp/opencode/decision-gate-heldout-dataset.json"),
    RESULTS / "g4-decision-gate-heldout110-dataset.json",
    RESULTS / "g4-decision-gate-validation130-dataset.json",
]

# (card id, READY?, negative family or "ready", reason for the hand label)
CURATED = [
    # READY — brief alone gives an action/deliverable and a target, no gate.
    ("ada-ocb-skills-edu-postmerge-recheck", True, "ready", "clear the two source-gone flags on a named lesson"),
    ("adobe-stock-render-preview-wiring", True, "ready", "needs assets.json entries with preview/thumbnail URLs; fixture mention is context, not a gate"),
    ("audit-auto-idc02", True, "ready", "fix the drift or the SSOT declaration on this host"),
    ("board-diagram-lanes-view", True, "ready", "build a lane/sub-lane diagram starting with Adobe Stock"),
    ("board-tests-control-pane-lane-failures", True, "ready", "find the real cause in named failing tests; do not weaken asserts"),
    ("gemini-38-live-extended-thinking-bench-2026-11-26", True, "ready", "run the bench and compare to baseline; '20-fixture' is test fixtures, not a scratch card"),
    ("jack-shared-workspace-repo-promotion", True, "ready", "use the shared instance with organized workspaces and a gated commit flow"),
    ("jevnest-kk-mac-capacity-loop", True, "ready", "feed the KK-Mac with bounded work under named runtime capacity gates"),
    ("job-health-sweep-consecutive-failure-alerts", True, "ready", "dead jobs must surface themselves; named hosts and jobs"),
    ("mcp-dell-alphavantage-llama-decision", True, "ready", "resolve the named allowlist/retire verdict"),
    ("opencode-ada-ha-tab-standard", True, "ready", "define and add the protected tab after Board"),
    ("ops-mn01-restore-sshd-shell-script-20261126", True, "ready", "restore standard host behavior locally on a named host"),
    ("ops-tony-dell-ssh-restore-diag", True, "ready", "re-run verbosely to a named output file; exit 0 by design"),
    ("ops-tony-dell-ssh-restore-fix", True, "ready", "re-run verbosely to a named output file; exit 0 by design"),
    ("oswe-eval-ada-test-tab", True, "ready", "evaluate, self-deploy, and add the named sidebar tab"),
    ("runner-auto-queue", True, "ready", "fix the card requirements or teach a host the label"),
    ("ssh-access-ansible-standard", True, "ready", "layered fix: declare -> generate -> verify the SSH contract"),
    ("unified-media-pack-layout", True, "ready", "generalize the Nest artifact structure with a named pack contract"),
    ("video-history-data-management", True, "ready", "create one lineage/retention procedure for named artifact classes"),
    ("video-history-opencode-doc", True, "ready", "independently review and verify the video history procedure"),
    # NOT_READY — explicit approval/human gates.
    ("capture-harvester-apply-gate-1426cfed", False, "approval_gated", "stay read-only until Tony explicitly approves sink writes"),
    ("chaba-exec-checkout-idc02-dirty-files", False, "approval_gated", "needs a per-group human commit/move/discard decision; spec says NOT for dispatch"),
    ("lab-cf-kv-claw-channel", False, "approval_gated", "pre-req: Tony must add token scopes before the card is dispatchable"),
    ("ada-voice-host-status-drop-19-pr", False, "approval_gated", "human-owned step: no gh CLI or token on the host"),
    ("kk-mac-disk-headroom", False, "approval_gated", "review and reclaim only with Tony approval"),
    # NOT_READY — deferred / keep-or-close / backlog.
    ("ada-alias-telemetry", False, "deferred_or_parked", "waiting in backlog"),
    ("ada-deploy-gate-tests", False, "deferred_or_parked", "waiting in backlog"),
    ("ada-pi-ci", False, "deferred_or_parked", "waiting in backlog"),
    ("ada-toolsd-runner-facade", False, "deferred_or_parked", "waiting in backlog"),
    ("ada-trace-full-result", False, "deferred_or_parked", "waiting in backlog"),
    ("lab-meshtastic-th", False, "deferred_or_parked", "keep-or-close decision due; experiment still gathering"),
    ("lab-gold-thb-causality", False, "deferred_or_parked", "data still gathering; keep-or-close decision due"),
    ("request-lifecycle", False, "deferred_or_parked", "waiting in backlog — no action needed"),
    ("ada-chat-ux-verify", False, "human_eyeball", "needs a human eyeball before it is done"),
    # NOT_READY — smoke/fixture and no-op/informational.
    ("kk-mac-script-smoke", False, "fixture_or_test", "smoke card proving the runner claims+executes a card"),
    ("budget-watch-ada-dev-2", False, "noop_or_informational", "budget-cap alert with no action in the brief"),
    ("keywatch-or-idc03", False, "noop_or_informational", "credential-monitor alert with no action in the brief"),
    ("keywatch-or-tony-dell", False, "noop_or_informational", "credential-monitor alert with no action in the brief"),
    ("keywatch-or-tony-omen", False, "noop_or_informational", "credential-monitor alert with no action in the brief"),
    ("mddb-ops-30g-analyze-compact-via-mddbd-r-eed976", False, "noop_or_informational", "conditional analysis only; no imperative"),
    ("prune-old-docs-sweep-exits-in-223ms-veri-6e0db7", False, "noop_or_informational", "either/or diagnostic question, no chosen action"),
    # NOT_READY — umbrella/tracker cards.
    ("release-lifecycle-standard", False, "umbrella_or_parent", "explicit umbrella card spanning multiple lanes"),
    ("report-loop-ada-opinion", False, "umbrella_or_parent", "part 5 of an umbrella loop; queued when Tony presses Start"),
    ("report-loop-bench", False, "umbrella_or_parent", "part 6 of an umbrella loop; queued when Tony presses Start"),
    ("report-loop-comment-delivery", False, "umbrella_or_parent", "part 4 of an umbrella loop; queued when Tony presses Start"),
    ("report-loop-session-rails", False, "umbrella_or_parent", "part 3 of an umbrella loop; queued when Tony presses Start"),
    ("report-loop-spawn-api", False, "umbrella_or_parent", "part 1 of an umbrella loop; queued when Tony presses Start"),
    ("report-loop-spawn-ui", False, "umbrella_or_parent", "part 2 of an umbrella loop; queued when Tony presses Start"),
    # NOT_READY — descriptive-only observations with no imperative in the brief.
    ("cast-loop-breaker-test-failure", False, "descriptive_only", "failing-test report; fix lives only in spec"),
    ("colab-runtime-identity-and-duplicate-ses-11a426", False, "descriptive_only", "risk description, no action in brief"),
    ("devin-lane-cheap-ops-reroute", False, "descriptive_only", "audit findings only, no imperative"),
    ("devin-session-audit-2026-10-29", False, "descriptive_only", "scan summary; 'verification remains' is not a concrete action"),
    ("devin-taskdir-gc-dispatch-hosts", False, "descriptive_only", "verified findings only, no imperative"),
    ("devnest-ada-mcp-bridge-sync", False, "descriptive_only", "state description; comparison action lives only in spec"),
    ("idc02-mddb-cors-wildcard-sec-008-set-mdd-1b41a4", False, "descriptive_only", "conditional 'should be allowlisted before', no present action"),
    ("m1-behavioral-fixture-activation-and-skips", False, "descriptive_only", "status report on a closed verdict"),
    ("mddb-2-15-4-v2-18-10-upgrade-custom-lsn-aa896c", False, "descriptive_only", "status report; upgrade implications only"),
    ("mddb-embed-stale-freebytes-metric-20g-vs-1b600f", False, "descriptive_only", "bug observation, no action in brief"),
    ("mddb-storage-reduction-retention-relocation", False, "descriptive_only", "in-flight pipeline, no imperative in brief"),
    ("omen-maintenance-preflight-back-up-ha-st-b3738f", False, "descriptive_only", "read-only scan report"),
]

assert len(CURATED) == 60, len(CURATED)
assert len({r[0] for r in CURATED}) == len(CURATED)
assert sum(r[1] for r in CURATED) == 20

blocked_ids, blocked_briefs = set(), set()
for p in PRIORS:
    for it in json.load(open(p))["items"]:
        blocked_ids.add(it["id"])
        blocked_briefs.add(re.sub(r"\W+", " ", it["brief"].lower()).strip())

cards = {}
for folder in (CARDS_DIR, CARDS_DIR / "archive"):
    for f in sorted(folder.glob("*.yml")):
        cards.setdefault(f.stem, (f, "active" if folder == CARDS_DIR else "archive"))

sel = []
for cid, label, kind, reason in sorted(CURATED):
    assert cid not in blocked_ids, cid
    f, source = cards[cid]
    d = yaml.safe_load(open(f)) or {}
    brief = str(d.get("brief") or "").replace("\n", " ").strip()
    norm = re.sub(r"\W+", " ", brief.lower()).strip()
    assert norm not in blocked_briefs, cid
    sel.append({"id": cid, "brief": brief, "label": label, "kind": kind,
                "label_reason": reason, "source": source})

assert len({re.sub(r"\W+", " ", r["brief"].lower()).strip() for r in sel}) == len(sel)
sel = [{"n": i + 1, **r} for i, r in enumerate(sel)]

ds = {
    "schema": "decision-gate-diverse60",
    "date": "2026-11-27",
    "source": "origin/master card snapshot, disjoint by ID and normalized brief from 60/41/110/130-brief prior sets",
    "label_rule": "Hand audited against the brief alone (the model never sees spec): READY = concrete action/deliverable and target with no external gate; NOT_READY = explicit approval/human gate, deferral, smoke/fixture, umbrella/tracker, informational, or descriptive only. Ambiguous cards were dropped, not relabeled to fit a quota.",
    "counts": {"ready": 20, "not_ready": 40},
    "negative_families": dict(collections.Counter(r["kind"] for r in sel if not r["label"])),
    "items": sel,
}
json.dump(ds, open(RESULTS / "g4-decision-gate-diverse60-dataset.json", "w"), indent=2)

lines = [f"{i+1}. [{r['id']}] {r['brief']}" for i, r in enumerate(sel)]
questions = {}
for i in range(len(sel)):
    questions[f"ready_{i+1}"] = {
        "type": "noul",
        "instructions": (
            f"Is brief {i+1} ready for dispatch now? Ready means it states a concrete action "
            "and target with enough detail to act without another source; not ready means it "
            "is gated on approval, deferred, a fixture, an umbrella/tracker, informational, or "
            "descriptive only."
        ),
    }
json.dump({"model": "gemini-decision-1", "input": "Kanban card briefs to triage:\n" + "\n".join(lines),
           "questions": questions},
          open(RESULTS / "g4-decision-gate-diverse60-payload.json", "w"), indent=2)
open(RESULTS / "g4-decision-gate-diverse60-review.txt", "w").write("\n".join(
    ("R" if r["label"] else "N") + " " + l for r, l in zip(sel, lines)) + "\n")
print("selected", ds["counts"], ds["negative_families"], "questions", len(questions))
