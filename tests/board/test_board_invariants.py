"""tests/board/test_board_invariants.py — Q1 queue-truth findings.

Q1 flags action.status=queued cards no runner can ever claim: manual
executor/lane/type (Tony's hands), unknown executors (fail-closed), and
types outside dispatch_repos.SERVED_TYPES — plus the legacy
type!=dispatch starvation signal. The write door (board-api) refuses to
create these; Q1 is the YAML-bypass/legacy-card catch.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "board_invariants", REPO / "scripts/board/board-invariants.py")
bi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bi)

OLD = "2026-01-01 00:00"
FRESH = "2999-01-01 00:00"


def _card(cid, action=None, updated=OLD, column="backlog", **kw):
    c = {"id": cid, "title": cid, "column": column, "updated": updated}
    if action is not None:
        c["action"] = action
    c.update(kw)
    return c


def _write(tmp_path, cards):
    for c in cards:
        (tmp_path / f"{c['id']}.yml").write_text(yaml.safe_dump(c))


def _q1(tmp_path, cards):
    _write(tmp_path, cards)
    orig = bi.CARD_DIR
    bi.CARD_DIR = tmp_path
    try:
        return bi.check_cards()["Q1"]
    finally:
        bi.CARD_DIR = orig


def test_q1_flags_queued_manual_type(tmp_path):
    finds = _q1(tmp_path, [_card("m1", {"type": "manual",
                                     "status": "queued"})])
    assert len(finds) == 1 and "m1" in finds[0] and "manual" in finds[0]


def test_q1_flags_queued_manual_executor_and_lane(tmp_path):
    finds = _q1(tmp_path, [
        _card("m2", {"type": "dispatch", "executor": "manual",
                     "status": "queued"}),
        _card("m3", {"type": "dispatch", "lane": "manual",
                     "status": "queued"}),
    ])
    assert len(finds) == 2
    assert any("executor=manual" in f for f in finds)
    assert any("lane=manual" in f for f in finds)


def test_q1_flags_queued_unserved_type_and_unknown_executor(tmp_path):
    finds = _q1(tmp_path, [
        _card("u1", {"type": "teleport", "status": "queued"}),
        _card("u2", {"type": "dispatch", "executor": "bogus",
                     "status": "queued"}),
    ])
    assert len(finds) == 2
    assert any("no unattended executor" in f for f in finds)
    assert any("unknown" in f and "fail-closed" in f for f in finds)


def test_q1_keeps_legacy_non_dispatch_flag(tmp_path):
    # container/script are runner-claimable but kanban-dispatch is
    # dispatch-only — the pre-existing starvation signal still fires
    finds = _q1(tmp_path, [_card("c1", {"type": "container",
                                      "status": "queued"})])
    assert len(finds) == 1 and "kanban-dispatch" in finds[0]


def test_q1_ignores_claimable_and_young_cards(tmp_path):
    finds = _q1(tmp_path, [
        _card("ok1", {"type": "dispatch", "status": "queued"}),
        _card("ok2", {"type": "dispatch", "lane": "paid_frontier",
                      "status": "queued"}),
        _card("ok3", {"type": "manual", "status": "queued"},
              updated=FRESH),   # inside the 24h grace window
        _card("ok4", {"type": "manual", "status": "idle"}),
        _card("ok5", {"type": "manual", "status": "failed"}),
    ])
    assert finds == []


def test_queue_block_reason_parity_with_served_types(tmp_path):
    # the helper itself: served types pass, everything else names why
    assert bi._queue_block_reason({"type": "dispatch"}) == ""
    assert bi._queue_block_reason({"type": "container"}) == ""
    assert bi._queue_block_reason({"type": "script"}) == ""
    assert "manual" in bi._queue_block_reason({"type": "manual"})
    assert "executor" in bi._queue_block_reason({"executor": "manual"})
    assert "lane" in bi._queue_block_reason({"lane": "manual"})
    assert "no unattended" in bi._queue_block_reason({"type": "weird"})
