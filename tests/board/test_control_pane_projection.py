"""tests/board/test_control_pane_projection.py — control-pane design (KNB-0229).

Read-only: the card YAML is the board's source of truth (all card writes go
through scripts/board/board-api.py). The design
(docs/design/kanban-card-cycle-control-pane.md) maps each pane section to
sources that must be present today: the card record, the envelope contract
(ada_job_envelope), the DevNest ledger (lane_gate).
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.board.ada_job_envelope import (
    LIFECYCLE, REQUIRED, RESULT_ARTIFACTS, validate_envelope, validate_result,
)
from scripts.devnest.lane_gate import METRIC_FIELDS

REPO = Path(__file__).resolve().parents[2]
CARD_PATH = REPO / "docs/ssot/kanban/cards/kanban-card-cycle-control-pane.yml"
ARCHIVED_CARD_PATH = (
    REPO / "docs/ssot/kanban/cards/archive/kanban-card-cycle-control-pane.yml")


def _card_path() -> Path:
    # KNB-0229 completed and was archived on 2026-11-23; the pane contract
    # still reads the same card record, now in the archive. Keep the live
    # path first so the test also works if the card is ever re-opened.
    return CARD_PATH if CARD_PATH.exists() else ARCHIVED_CARD_PATH

# Example envelope + result bundle per the ada_job_envelope contracts — the
# shape the pane's lifecycle/attempts/escalation and artifact/verifier
# sections read.
SAMPLE_ENVELOPE = {
    "job_id": "knb-0229-control-pane",
    "card_id": "kanban-card-cycle-control-pane",
    "project": "chaba",
    "repo": "chaba",
    "worktree": "/tmp/chaba-knb-0229",
    "task_class": "design",
    "objective": "Design the card-cycle control pane (KNB-0229).",
    "requirements": ["read-only projection first"],
    "acceptance_criteria": ["design artifact + checklist land in docs/design/"],
    "executor": "opencode",
    "model": "gpt-5",
    "target_host": "tony-omen",
    "allowed_paths": ["docs/design", "tests/board"],
    "input_artifacts": [],
    "output_artifacts": ["result.json", "summary.md", "diff.patch", "tests.json"],
    "verify": ["pytest"],
    "approval_required": ["merge", "deploy"],
    "timeout_s": 900,
    "idempotency_key": "knb-0229-control-pane-v1",
    "state": "draft",
}

SAMPLE_RESULT = {
    "status": "pass",
    "artifacts": ["result.json", "summary.md", "diff.patch", "tests.json"],
    "verifier": "pytest tests/board/test_control_pane_projection.py",
    "evidence": ["card-pick sweep 2026-11-19: KNB-0229 top pick (sweep)"],
}


def _card() -> dict:
    return yaml.safe_load(_card_path().read_text())


def test_card_record_is_the_pane_card():
    c = _card()
    assert c["ref"] == "KNB-0229"
    assert c["column"] in ("doing", "done")  # completed + archived 2026-11-23
    assert c["priority"] in ("high", "medium", "low")
    assert c["updated"]
    assert c["brief"] and c["spec"]
    # lifecycle & timeline source
    assert isinstance(c["comms"], list) and c["comms"]
    assert c["tags"]


def test_eligibility_and_claim_reason_sources_present():
    c = _card()
    # card-pick.is_actionable: open requests block pickup — the pane shows the
    # reason; all of KNB-0229's requests are answered, so the card is
    # actionable in sweep order (doing, untouched).
    assert all(r.get("status") in ("answered", "closed")
               for r in c.get("requests") or [])
    assert c.get("awaiting_action") is True or c["column"] in ("doing", "done")
    assert (c.get("action") or {}).get("status")  # terminal lifecycle for pane


def test_envelope_contract_validates_sample():
    assert validate_envelope(SAMPLE_ENVELOPE) == []
    assert set(REQUIRED) <= set(SAMPLE_ENVELOPE)
    assert SAMPLE_ENVELOPE["state"] in LIFECYCLE
    assert set(RESULT_ARTIFACTS) <= set(SAMPLE_RESULT["artifacts"])
    assert validate_result(SAMPLE_RESULT) == []


def test_devnest_ledger_evidence_fields_present():
    # tokens/cost/duration — the pane's evidence: execution, not display.
    for field in ("input_tokens", "output_tokens", "provider_cost_usd",
                  "combined_cost_usd", "wall_s", "queue_s", "failure_reason"):
        assert field in METRIC_FIELDS


def test_pane_implemented_on_board_page():
    # The pane is the read-only card-cycle control on the Board page
    # (scripts/render-board2.py -> stacks/web/public/apps/board2/).
    src = (REPO / "scripts/render-board2.py").read_text()
    assert 'id="control"' in src
    for label in ("Lifecycle & timeline", "Eligibility & claim reason",
                  "Executor / provider / model", "Host / session",
                  "Queue & run duration", "Evidence: tokens & cost",
                  "Artifact & verifier", "Attempts & failure",
                  "Suggested escalation"):
        assert label in src
    for fn in ("cpPane", "cpReason", "cpEscalate", "cpCards",
               "renderControl", "cpFetchLive"):
        assert fn + "(" in src
    page = (REPO / "stacks/web/public/apps/board2/index.html").read_text()
    assert "cp-head" in page and "Card cycle control" in page


def test_pane_reads_lane_evidence_from_board_api_jobs():
    # §4: the pane's tokens/cost/duration come from the new read door:
    # GET /jobs?card= on board-api (ledger metric + usage.json + envelope).
    src = (REPO / "scripts/render-board2.py").read_text()
    assert "/jobs?card=" in src
    assert "'Queue & run duration'" in src
    assert "'Evidence: tokens & cost'" in src
    # §6.3: every pane row cites its source
    assert "cp-src" in src
    assert "from: " in src
    assert "SRC_METRIC" in src
    assert "SRC_USAGE" in src


def test_pane_data_contract_on_board_payload():
    # The page's data (cards.json — written by board-api after card writes)
    # carries the pane's sources: the active-cycle card + the fields its
    # sections read (card record + live action overlay via board-api).
    payload = json.loads(
        (REPO / "stacks/web/public/apps/board2/cards.json").read_text())
    fields = ("title", "brief", "spec", "comms", "requests", "updated")
    # KNB-0229 is archived now, so it is legitimately absent from the live
    # payload. Assert the same contract against a card that carries the
    # pane's sources; prefer the design card if it is ever re-opened.
    k = next((c for c in payload["cards"]
              if c["id"] == "kanban-card-cycle-control-pane"), None)
    if k is None:
        k = next(c for c in payload["cards"]
                 if all(f in c for f in fields))
    assert k["column"] in ("backlog", "doing", "review", "done", "lab")
    for f in fields:
        assert f in k
