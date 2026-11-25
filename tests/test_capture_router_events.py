"""Unit tests for capture-router.py Phase C.2 events mode (OPS-1354).

Covers the acceptance criteria: idempotent reruns, audit JSONL, no
unapproved sink writes, and the board-api mutation door staying the only
write path (the router itself performs zero sink writes).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
ROUTER_PATH = REPO / "scripts/chaba/capture-router.py"


def _load_router():
    spec = importlib.util.spec_from_file_location("capture_router", ROUTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("capture_router", mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def router():
    return _load_router()


def _event(**kw):
    ev = {
        "event_id": "evt-x", "event_type": "discovery",
        "as_of": "2026-11-25", "source": "devin", "actor": "devin",
        "subject": "s", "summary": "Please wire the capture hooks next action",
        "refs": [], "dedupe_key": "discovery:devin:s:wire",
        "volatility": "pointer", "payload": {},
    }
    ev.update(kw)
    return ev


def _write_events(path: Path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n",
                    encoding="utf-8")


def test_consume_routes_and_audits(router, tmp_path):
    spool = tmp_path / "spool"
    ev = spool / "events.jsonl"
    _write_events(ev, [_event()])
    ledger = tmp_path / "capture-ledger.yml"
    ledger.write_text("matrix_version: t\nentries: []\n", encoding="utf-8")

    stats = router.consume_events([ev], spool, ledger_path=ledger,
                                  run_id="t1")
    assert stats["events"] == 1 and stats["new"] == 1
    assert stats["proposals_new"] == 1 and stats["ledger_added"] == 1

    audit = [json.loads(l) for l in
             (spool / "router-audit.jsonl").read_text().splitlines()
             if l.strip()]
    routed = [a for a in audit if a.get("mode") == "route"
              and a.get("dedupe_status") == "new"]
    assert routed and all(a["dry_run"] is True for a in audit)
    assert routed[0]["sink_write"] == "none"
    assert routed[0]["target_sink"]

    doc = yaml.safe_load(ledger.read_text())
    assert len(doc["entries"]) == 1
    assert doc["entries"][0]["dedupe_key"].startswith(
        doc["entries"][0]["proposed_sink"] + ":")


def test_consume_is_idempotent(router, tmp_path):
    spool = tmp_path / "spool"
    ev = spool / "events.jsonl"
    _write_events(ev, [_event(), _event(dedupe_key="discovery:devin:s2:x",
                                      event_id="evt-y",
                                      summary="Explain how routing works")])
    ledger = tmp_path / "capture-ledger.yml"

    router.consume_events([ev], spool, ledger_path=ledger, run_id="t1")
    first_entries = yaml.safe_load(ledger.read_text())["entries"]
    audit_len = len((spool / "router-audit.jsonl")
                    .read_text().splitlines())

    stats = router.consume_events([ev], spool, ledger_path=ledger,
                                  run_id="t2")
    assert stats["new"] == 0 and stats["duplicate"] == 2
    assert stats["proposals_new"] == 0 and stats["ledger_added"] == 0
    assert yaml.safe_load(ledger.read_text())["entries"] == first_entries
    # noop+audit: audit still grows, nothing else does
    assert len((spool / "router-audit.jsonl")
               .read_text().splitlines()) > audit_len


def test_no_sink_writes_outside_runtime_dir(router, tmp_path):
    """The router must not create files outside its out-dir + ledger."""
    repo = tmp_path / "fake-repo"
    spool = tmp_path / "spool"
    ev = spool / "events.jsonl"
    _write_events(ev, [_event()])
    before = {p for p in tmp_path.rglob("*")}
    router.consume_events([ev], spool, ledger_path=None, run_id="t1")
    after = {p for p in tmp_path.rglob("*")}
    new_files = {str(p.relative_to(tmp_path)) for p in after - before}
    allowed = {"spool/router-state.json", "spool/router-audit.jsonl",
               "spool/router-proposals.jsonl"}
    assert new_files <= allowed, f"unexpected writes: {new_files - allowed}"
    assert not (repo / "docs").exists()


def test_secret_event_rejected_metadata_only(router, tmp_path):
    spool = tmp_path / "spool"
    ev = spool / "events.jsonl"
    secret = "api_key=sk-ABCDEFGHIJKLMNOPQRSTUVWX"
    _write_events(ev, [_event(summary=secret,
                            dedupe_key="discovery:devin:s:sec",
                            event_id="evt-sec")])
    stats = router.consume_events([ev], spool, ledger_path=None,
                                  run_id="t1")
    assert stats["rejected"] == 1 and stats["new"] == 0
    blob = (spool / "router-audit.jsonl").read_text() + \
        (spool / "router-proposals.jsonl").read_text() \
        if (spool / "router-proposals.jsonl").exists() else \
        (spool / "router-audit.jsonl").read_text()
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in blob


def test_bad_envelope_and_missing_dedupe_key(router, tmp_path):
    spool = tmp_path / "spool"
    ev = spool / "events.jsonl"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text('{"event_type":"discovery","summary":"no key"}\n'
                  'garbage-line\n', encoding="utf-8")
    stats = router.consume_events([ev], spool, ledger_path=None, run_id="t1")
    assert stats["rejected"] == 1 and stats["errors"] == 1
    audit = (spool / "router-audit.jsonl").read_text()
    assert "rejected:no-dedupe-key" in audit
    assert "rejected:bad-json" in audit
