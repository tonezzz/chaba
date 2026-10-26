import importlib.util
import json
import os
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/devnest/devnest-tg-relay.py"
SPEC = importlib.util.spec_from_file_location("devnest_tg_relay", SCRIPT)
relay = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(relay)

CHAT = -1003998821809
TONY = 8960073266
OTHER = 42

CARD = {
    "id": "devnest-telegram-team-channel",
    "ref": "OPS-0905",
    "title": "Connect DevNest household AI team to Telegram group",
    "column": "doing",
    "updated": "2026-10-26 17:00",
    "note": "wire board-api command routing next",
    "action": {"type": "dispatch", "status": "running", "runner": "idc02"},
    "checks": [{"k": "verify", "ok": True,
                "how": "comms: Verified relay capture on idc03"}],
    "comms": [{"at": "2026-10-26 16:00", "from": "devin",
               "text": "Verified capture path"}],
    "requests": [{"id": "pick-lane", "ask": "which lane?",
                  "status": "open"}],
}


def _update(text, sender=TONY, thread=None, update_id=1):
    msg = {
        "message_id": update_id * 10,
        "chat": {"id": CHAT, "type": "supergroup", "title": "DevNestHA"},
        "from": {"id": sender},
        "text": text,
    }
    if thread is not None:
        msg["message_thread_id"] = thread
    return {"update_id": update_id, "message": msg}


def _harness(monkeypatch, tmp_path, cards=None):
    """Board + Telegram fakes; returns (sent, posts)."""
    sent, posts = [], []
    monkeypatch.setattr(relay, "CHAT_IDS", {CHAT})
    monkeypatch.setattr(relay, "CALLERS", {TONY: "user-tony", OTHER: "user-x"})
    monkeypatch.setattr(relay, "APPROVER_IDS", {TONY})
    monkeypatch.setattr(relay, "STATE_DIR", tmp_path)
    monkeypatch.setattr(relay, "UPDATES_FILE", tmp_path / "updates.jsonl")
    monkeypatch.setattr(relay, "AUDIT_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(relay, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(relay, "_send_text",
                        lambda chat, text, thread=None:
                        sent.append({"chat": chat, "text": text,
                                     "thread": thread}))
    index = {}
    for c in cards if cards is not None else [CARD]:
        for key in (str(c.get("ref") or "").upper(), str(c.get("id") or "")):
            if key:
                index.setdefault(key, []).append(c)
    monkeypatch.setattr(relay, "_card_index", lambda: index)
    monkeypatch.setattr(relay, "_board_post",
                        lambda path, body:
                        posts.append({"path": path, "body": body})
                        or {"ok": True, "message": "mocked"})
    return sent, posts


def test_general_topic_has_no_thread():
    topic, thread = relay._topic({"chat": {"id": -100}, "message_id": 1})
    assert (topic, thread) == ("general", None)


def test_forum_topic_is_lane_candidate():
    topic, thread = relay._topic({
        "chat": {"id": -100},
        "message_id": 2,
        "message_thread_id": 42,
    })
    assert (topic, thread) == ("thread-42", 42)


def test_lane_mapping():
    assert relay._lane("HA Lab") == "ha-lab"
    assert relay._lane("unknown-topic") == "unknown"


def test_state_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(relay, "STATE_DIR", tmp_path)
    monkeypatch.setattr(relay, "OFFSET_FILE", tmp_path / "state.json")
    relay._save_offset(123)
    assert relay._state_offset() == 123


# --- command normalization -------------------------------------------------


def test_normalize_ref_variants():
    assert relay.normalize_ref("0905") == "OPS-0905"
    assert relay.normalize_ref("905") == "OPS-0905"
    assert relay.normalize_ref("ops-0905") == "OPS-0905"
    assert relay.normalize_ref("OPS 0905") == "OPS-0905"
    assert relay.normalize_ref("ada-0042") == "ADA-0042"
    assert relay.normalize_ref("devnest-tg-command-router") == \
        "devnest-tg-command-router"
    assert relay.normalize_ref("hello world") is None
    assert relay.normalize_ref("") is None


def test_parse_command_anchored():
    assert relay.parse_command("explain 0905") == ("explain", "0905")
    assert relay.parse_command("APPROVE OPS-0912") == ("approve", "OPS-0912")
    assert relay.parse_command("reject ops-0905") == ("reject", "ops-0905")
    assert relay.parse_command("status OPS-0905") == ("status", "OPS-0905")
    assert relay.parse_command("please explain 0905") is None
    assert relay.parse_command("explain 0905 thanks") == \
        ("explain", "0905 thanks")
    assert relay.parse_command("explain") == ("explain", "")
    assert relay.parse_command("list projects") is None


# --- explain (read-only) ----------------------------------------------------


def test_explain_returns_deterministic_summary(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain 0905"))
    assert posts == []  # read-only: no board mutation
    assert len(sent) == 1
    body = sent[0]["text"]
    assert "OPS-0905" in body and "devnest-telegram-team-channel" in body
    for field in ("status:", "phase:", "verified:", "next:", "ask:"):
        assert field in body
    assert "running" in body and "idc02" in body
    assert "which lane?" in body


def test_explain_makes_no_board_writes(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("status ops-0905"))
    assert posts == []
    assert len(sent) == 1


# --- approval authorization -------------------------------------------------


def test_approve_denied_for_non_approver(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("APPROVE OPS-0905", sender=OTHER))
    assert posts == []
    assert "not in approver allowlist" in sent[0]["text"]
    audit = (tmp_path / "audit.jsonl").read_text()
    assert "refused" in audit


def test_approve_answers_open_request(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("APPROVE OPS-0905"))
    assert posts == [{
        "path": "/respond",
        "body": {"id": "devnest-telegram-team-channel",
                 "request_id": "pick-lane",
                 "answer": "approve via devnest-tg", "from": "tony"},
    }]
    assert "APPROVE OPS-0905" in sent[0]["text"]
    assert "answered pick-lane" in sent[0]["text"]


def test_approve_review_card_uses_action_close(monkeypatch, tmp_path):
    review = dict(CARD, column="review", requests=[], review_kind="verify")
    sent, posts = _harness(monkeypatch, tmp_path, cards=[review])
    relay.handle_update(_update("APPROVE OPS-0905"))
    assert posts == [{
        "path": "/action",
        "body": {"id": "devnest-telegram-team-channel",
                 "do": "close", "from": "tony"},
    }]


def test_reject_review_card_uses_action_hold(monkeypatch, tmp_path):
    review = dict(CARD, column="review", requests=[], review_kind="verify")
    sent, posts = _harness(monkeypatch, tmp_path, cards=[review])
    relay.handle_update(_update("REJECT OPS-0905"))
    assert posts == [{
        "path": "/action",
        "body": {"id": "devnest-telegram-team-channel",
                 "do": "hold", "from": "tony"},
    }]


def test_approve_nothing_pending_refused(monkeypatch, tmp_path):
    idle = dict(CARD, column="doing", requests=[], action={})
    sent, posts = _harness(monkeypatch, tmp_path, cards=[idle])
    relay.handle_update(_update("APPROVE OPS-0905"))
    assert posts == []
    assert "nothing pending" in sent[0]["text"]


def test_approve_ambiguous_requests_refused(monkeypatch, tmp_path):
    busy = dict(CARD, requests=[
        {"id": "r1", "ask": "one?", "status": "open"},
        {"id": "r2", "ask": "two?", "status": "open"},
    ])
    sent, posts = _harness(monkeypatch, tmp_path, cards=[busy])
    relay.handle_update(_update("APPROVE OPS-0905"))
    assert posts == []
    assert "2 open requests" in sent[0]["text"]


# --- unknown / ambiguous refs ------------------------------------------------


def test_unknown_ref_refused_and_audited(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("APPROVE OPS-0912"))
    assert posts == []
    assert "unknown ref OPS-0912" in sent[0]["text"]
    audit = [json.loads(line)
             for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert audit[0]["result"] == "refused"
    assert audit[0]["command"] == "approve"
    assert audit[0]["normalized"] == "OPS-0912"


def test_explain_unknown_slug_refused(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain no-such-card"))
    assert "unknown ref" in sent[0]["text"]


def test_explain_by_slug_id(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain devnest-telegram-team-channel"))
    assert "OPS-0905" in sent[0]["text"]


def test_pdf_document_intake_creates_idempotent_project_card(
        monkeypatch, tmp_path):
    project_dir = tmp_path / "kk-video-abc123456789"
    source_dir = project_dir / "source"
    source_dir.mkdir(parents=True)
    (source_dir / "materials.pdf").write_bytes(b"%PDF-test")
    (project_dir / "project.json").write_text(
        '{"project_id":"kk-video-abc123456789","status":"intake_downloaded"}')
    posts = []
    sent = []
    monkeypatch.setattr(relay, "AUDIT_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(relay, "_download_document",
                        lambda document: (
                            source_dir / "materials.pdf",
                            "abc123456789",
                            9,
                        ))
    monkeypatch.setattr(relay, "_board_get", lambda path: {"cards": []})
    monkeypatch.setattr(
        relay, "_board_post",
        lambda path, body: posts.append((path, body)) or {
            "id": body["id"], "ref": "OPS-0999",
        })
    monkeypatch.setattr(
        relay, "_send_text",
        lambda chat, text, thread=None: sent.append(text))
    relay._handle_document(
        {"update_id": 99},
        {
            "message_id": 7,
            "document": {
                "file_name": "materials.pdf",
                "mime_type": "application/pdf",
                "file_id": "not-persisted-in-audit",
            },
            "caption": "Please assess these materials.",
        },
        CHAT,
        12,
    )
    assert posts[0][0] == "/card"
    assert posts[0][1]["id"] == "kk-video-abc123456789"
    assert "OPS-0999" in sent[0]
    manifest = json.loads((project_dir / "project.json").read_text())
    assert manifest["status"] == "intake_ready"
    assert manifest["card_ref"] == "OPS-0999"


def test_pdf_only_document_policy():
    assert relay._document_is_pdf({
        "file_name": "materials.pdf", "mime_type": "application/octet-stream"})
    assert not relay._document_is_pdf({
        "file_name": "materials.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"})


# --- topic-preserving replies ------------------------------------------------


def test_replies_stay_in_topic_thread(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain 0905", thread=42))
    assert sent[0]["chat"] == CHAT
    assert sent[0]["thread"] == 42


def test_refusal_stays_in_topic_thread(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("APPROVE OPS-0912", thread=7))
    assert sent[0]["thread"] == 7
    assert sent[0]["chat"] == CHAT
