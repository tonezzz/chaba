import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path

import pytest


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


def _forum_created(name, thread, sender=TONY, update_id=50):
    return {"update_id": update_id, "message": {
        "message_id": update_id * 10,
        "chat": {"id": CHAT, "type": "supergroup", "title": "DevNestHA"},
        "from": {"id": sender},
        "message_thread_id": thread,
        "forum_topic_created": {"name": name},
    }}


def _forum_edited(name, thread, sender=TONY, update_id=51):
    return {"update_id": update_id, "message": {
        "message_id": update_id * 10,
        "chat": {"id": CHAT, "type": "supergroup", "title": "DevNestHA"},
        "from": {"id": sender},
        "message_thread_id": thread,
        "forum_topic_edited": {"name": name},
    }}


def _doc_update(caption="", filename="materials.pdf", thread=None,
                sender=TONY, update_id=60):
    msg = {
        "message_id": update_id * 10,
        "chat": {"id": CHAT, "type": "supergroup", "title": "DevNestHA"},
        "from": {"id": sender},
        "caption": caption,
        "document": {
            "file_name": filename,
            "mime_type": "application/pdf",
            "file_id": "tg-file-1",
            "file_size": 9,
        },
    }
    if thread is not None:
        msg["message_thread_id"] = thread
    return {"update_id": update_id, "message": msg}


def _fake_download(monkeypatch, api_calls, topic_thread=77):
    """Real _download_document against stubbed Telegram file endpoints, and
    a stubbed createForumTopic. Returns the api_calls list."""
    def fake_api(method, params=None):
        api_calls.append((method, params or {}))
        if method == "getFile":
            return {"ok": True, "result": {"file_path": "docs/file_1.pdf"}}
        if method == "createForumTopic":
            return {"ok": True,
                    "result": {"message_thread_id": topic_thread}}
        raise AssertionError(f"unexpected Telegram method {method}")
    monkeypatch.setattr(relay, "_api", fake_api)


def _fake_file_urlopen(monkeypatch, payload):
    monkeypatch.setattr(
        relay, "urlopen",
        lambda url, timeout=None: io.BytesIO(payload))


def _board_stubs(monkeypatch, posts, ref="OPS-0999"):
    monkeypatch.setattr(relay, "_board_get", lambda path: {"cards": []})
    monkeypatch.setattr(
        relay, "_board_post",
        lambda path, body: posts.append((path, body)) or (
            {"id": body["id"], "ref": ref} if path == "/card"
            else {"ok": True, "message": "mocked"}))


def _harness(monkeypatch, tmp_path, cards=None):
    """Board + Telegram fakes; returns (sent, posts)."""
    sent, posts = [], []
    monkeypatch.setattr(relay, "CHAT_IDS", {CHAT})
    monkeypatch.setattr(relay, "CALLERS", {TONY: "user-tony", OTHER: "user-x"})
    monkeypatch.setattr(relay, "APPROVER_IDS", {TONY})
    monkeypatch.setattr(relay, "STATE_DIR", tmp_path)
    monkeypatch.setattr(relay, "OFFSET_FILE", tmp_path / "state.json")
    monkeypatch.setattr(relay, "UPDATES_FILE", tmp_path / "updates.jsonl")
    monkeypatch.setattr(relay, "AUDIT_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(relay, "TOPICS_FILE", tmp_path / "topics.json")
    monkeypatch.setattr(relay, "CONTEXT_FILE", tmp_path / "card-context.json")
    monkeypatch.setattr(relay, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(relay, "PROJECTS_DIR", tmp_path / "projects")
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
    monkeypatch.setattr(relay, "TOPICS_FILE", tmp_path / "topics.json")
    monkeypatch.setattr(relay, "PROJECTS_DIR", tmp_path / "projects")
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
    relay.handle_update(_forum_created("Ops", 42))
    relay.handle_update(_update("explain 0905", thread=42))
    assert sent[-1]["chat"] == CHAT
    assert sent[-1]["thread"] == 42


def test_refusal_stays_in_topic_thread(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_forum_created("Ops", 7))
    relay.handle_update(_update("APPROVE OPS-0912", thread=7))
    assert sent[-1]["thread"] == 7
    assert sent[-1]["chat"] == CHAT


# --- durable topic registry -------------------------------------------------


def _topics(tmp_path):
    return json.loads((tmp_path / "topics.json").read_text())["topics"]


def test_permanent_topic_set():
    for name in ("general", "inbox", "control", "ops", "research",
                 "education", "archive"):
        assert name in relay.PERMANENT_TOPICS
    assert relay._classify_topic_name("Inbox")["lane"] == "inbox"
    assert relay._classify_topic_name("inbox")["kind"] == "permanent"


def test_project_topic_name_convention():
    assert relay._parse_project_topic_name(
        "PRJ kk-video-abc123 — Movie materials") == \
        ("kk-video-abc123", "Movie materials")
    assert relay._parse_project_topic_name("Inbox") is None
    name = relay._project_topic_name("kk-video-abc123", "Movie")
    assert name == "PRJ kk-video-abc123 — Movie"
    assert len(name) <= relay.TOPIC_NAME_MAX


def test_forum_created_registers_permanent(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_forum_created("Inbox", 7))
    entry = _topics(tmp_path)["7"]
    assert entry["kind"] == "permanent"
    assert entry["lane"] == "inbox"
    assert entry["visibility"] == "public"
    assert sent[-1]["thread"] == 7
    assert "registered" in sent[-1]["text"]


def test_forum_created_prj_binds_manifest(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    project = tmp_path / "projects" / "kk-video-abc123"
    project.mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({
        "project_id": "kk-video-abc123", "card_id": "kk-video-abc123",
        "card_ref": "OPS-0999", "status": "intake_ready"}))
    relay.handle_update(
        _forum_created("PRJ kk-video-abc123 — Movie materials", 9))
    entry = _topics(tmp_path)["9"]
    assert entry["kind"] == "project"
    assert entry["project_id"] == "kk-video-abc123"
    assert entry["card_ref"] == "OPS-0999"
    assert entry["lane"] == "project" and entry["visibility"] == "project"
    manifest = json.loads((project / "project.json").read_text())
    assert manifest["topic"]["thread_id"] == 9
    assert manifest["topic"]["status"] == "active"
    assert posts[-1]["path"] == "/comment"
    assert posts[-1]["body"]["id"] == "kk-video-abc123"
    assert posts[-1]["body"]["from"] == "devnest-tg"
    assert "thread_id=9" in posts[-1]["body"]["text"]


def test_forum_created_unknown_name_quarantined(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_forum_created("Random Chat", 11))
    entry = _topics(tmp_path)["11"]
    assert entry["kind"] == "quarantine"
    assert entry["lane"] == "unknown"
    assert "quarantined" in sent[-1]["text"]


def test_forum_edited_promotes_quarantined_topic(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_forum_created("Random Chat", 11))
    relay.handle_update(_forum_edited("Ops", 11))
    entry = _topics(tmp_path)["11"]
    assert entry["kind"] == "permanent" and entry["lane"] == "ops"


def test_unknown_thread_is_quarantined_once(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain 0905", thread=42))
    relay.handle_update(_update("explain 0905", thread=42, update_id=2))
    # one policy notice, no command execution, no board traffic
    assert len(sent) == 1
    assert "quarantined" in sent[0]["text"]
    assert sent[0]["thread"] == 42
    assert posts == []
    entry = _topics(tmp_path)["42"]
    assert entry["kind"] == "quarantine" and entry["notified"] is True
    events = [json.loads(line) for line in
              (tmp_path / "updates.jsonl").read_text().splitlines()]
    assert events[0]["topic_status"] == "unknown"
    assert events[1]["topic_status"] == "quarantine"


def test_registered_thread_runs_commands(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_forum_created("Ops", 42))
    relay.handle_update(_update("explain 0905", thread=42))
    assert "OPS-0905" in sent[-1]["text"]


# --- PDF intake -> project topic -------------------------------------------


def test_intake_creates_and_binds_project_topic(monkeypatch, tmp_path):
    """Handoff: PDF in Inbox -> new PRJ topic -> bound manifest/card ->
    next PDF in the project thread attaches to the same project."""
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_forum_created("Inbox", 5))
    api_calls = []
    _fake_download(monkeypatch, api_calls, topic_thread=77)
    _fake_file_urlopen(monkeypatch, b"%PDF-materials-one")
    _board_stubs(monkeypatch, posts)
    relay.handle_update(
        _doc_update(caption="KK movie materials", thread=5))
    sha = hashlib.sha256(b"%PDF-materials-one").hexdigest()
    pid = f"kk-video-{sha[:12]}"
    assert ("createForumTopic", {
        "chat_id": CHAT,
        "name": f"PRJ {pid} — KK movie materials"}) in api_calls
    entry = _topics(tmp_path)["77"]
    assert entry["kind"] == "project" and entry["project_id"] == pid
    assert entry["card_ref"] == "OPS-0999"
    manifest = json.loads(
        (tmp_path / "projects" / pid / "project.json").read_text())
    assert manifest["status"] == "intake_ready"
    assert manifest["topic"]["thread_id"] == 77
    assert manifest["topic"]["status"] == "active"
    paths = [p for p, _ in posts]
    assert "/card" in paths and "/comment" in paths
    comment = dict(posts)["/comment"]
    assert "thread_id=77" in comment["text"]
    # ack in Inbox names the new topic; announcement lands in the PRJ topic
    assert sent[-2]["thread"] == 5 and "thread 77" in sent[-2]["text"]
    assert sent[-1]["thread"] == 77 and pid in sent[-1]["text"]

    # same-topic intake: a second PDF inside the project thread attaches
    posts.clear()
    api_calls.clear()
    _fake_file_urlopen(monkeypatch, b"%PDF-materials-two")
    relay.handle_update(
        _doc_update(caption="more pages", thread=77, update_id=61))
    assert ("createForumTopic", {}) not in api_calls
    assert [p for p, _ in posts] == []  # no new card, no new topic
    manifest = json.loads(
        (tmp_path / "projects" / pid / "project.json").read_text())
    shas = {s["sha256"] for s in manifest["sources"]}
    assert shas == {sha, hashlib.sha256(b"%PDF-materials-two").hexdigest()}
    assert sent[-1]["thread"] == 77 and "INTAKE attached" in sent[-1]["text"]


def test_intake_topic_failure_returns_manual_instruction(
        monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_forum_created("Inbox", 5))
    calls = []

    def failing_api(method, params=None):
        calls.append(method)
        if method == "getFile":
            return {"ok": True, "result": {"file_path": "docs/f.pdf"}}
        raise RuntimeError("bot lacks can_manage_topics")
    monkeypatch.setattr(relay, "_api", failing_api)
    _fake_file_urlopen(monkeypatch, b"%PDF-manual")
    _board_stubs(monkeypatch, posts)
    relay.handle_update(_doc_update(caption="manual path", thread=5))
    pid = f"kk-video-{hashlib.sha256(b'%PDF-manual').hexdigest()[:12]}"
    assert sent[-1]["thread"] == 5
    assert f"PRJ {pid} — manual path" in sent[-1]["text"]
    assert "create a forum topic" in sent[-1]["text"]
    manifest = json.loads(
        (tmp_path / "projects" / pid / "project.json").read_text())
    assert manifest["topic"]["status"] == "manual_pending"
    assert manifest["topic"]["suggested_name"] == f"PRJ {pid} — manual path"

    # Tony creates the topic by hand -> forum_topic_created completes bind
    relay.handle_update(_forum_created(f"PRJ {pid} — manual path", 88))
    entry = _topics(tmp_path)["88"]
    assert entry["kind"] == "project" and entry["project_id"] == pid
    assert entry["card_ref"] == "OPS-0999"
    manifest = json.loads(
        (tmp_path / "projects" / pid / "project.json").read_text())
    assert manifest["topic"]["thread_id"] == 88


def test_pdf_in_project_thread_does_not_create_topic(
        monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    project = tmp_path / "projects" / "kk-video-abc123"
    (project / "source").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({
        "project_id": "kk-video-abc123", "status": "intake_ready"}))
    relay._register_topic(9, {
        "kind": "project", "name": "PRJ kk-video-abc123 — Movie",
        "lane": "project", "visibility": "project",
        "project_id": "kk-video-abc123", "card_ref": "OPS-0999",
        "card_id": "kk-video-abc123"})
    api_calls = []
    _fake_download(monkeypatch, api_calls)
    _fake_file_urlopen(monkeypatch, b"%PDF-attach")
    _board_stubs(monkeypatch, posts)
    relay.handle_update(_doc_update(thread=9))
    assert ("createForumTopic", {}) not in api_calls
    assert [p for p, _ in posts] == []
    manifest = json.loads((project / "project.json").read_text())
    assert manifest["sources"][-1]["sha256"] == \
        hashlib.sha256(b"%PDF-attach").hexdigest()
    assert sent[-1]["thread"] == 9


def test_pdf_in_quarantined_thread_refused(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_doc_update(thread=42))
    assert len(sent) == 1 and "quarantined" in sent[0]["text"]
    assert posts == []


# --- notification routing + milestone mirror -------------------------------


def test_project_send_routes_to_bound_thread(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay._register_topic(9, {
        "kind": "project", "name": "PRJ p — t", "lane": "project",
        "visibility": "project", "project_id": "kk-video-abc123",
        "card_ref": "OPS-0999", "card_id": "kk-video-abc123"})
    res = relay.route_send(
        {"chat_id": CHAT, "text": "job done", "project_id": "kk-video-abc123"})
    assert res["message_thread_id"] == 9
    assert res["mirrored_general"] is False
    assert sent == [{"chat": CHAT, "text": "job done", "thread": 9}]


def test_milestone_send_mirrors_to_general(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay._register_topic(9, {
        "kind": "project", "name": "PRJ p — t", "lane": "project",
        "visibility": "project", "project_id": "kk-video-abc123",
        "card_ref": "OPS-0999", "card_id": "kk-video-abc123"})
    res = relay.route_send({"chat_id": CHAT, "text": "milestone: brief done",
                            "card_ref": "OPS-0999", "milestone": True})
    assert res["mirrored_general"] is True
    assert sent[-2] == {"chat": CHAT, "text": "milestone: brief done",
                        "thread": 9}
    assert sent[-1] == {"chat": CHAT, "text": "milestone: brief done",
                        "thread": None}


def test_unbound_project_send_refused(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    with pytest.raises(LookupError):
        relay.route_send({"chat_id": CHAT, "text": "hi",
                          "project_id": "no-such-project"})
    assert sent == []


def test_non_project_send_to_general_unchanged(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    res = relay.route_send({"text": "plain notice"})
    assert res["message_thread_id"] is None
    assert res["mirrored_general"] is False
    assert sent == [{"chat": CHAT, "text": "plain notice", "thread": None}]


# --- persistence + rollback -------------------------------------------------


def test_registry_survives_reload(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay._register_topic(9, {
        "kind": "project", "name": "PRJ p — t", "lane": "project",
        "visibility": "project", "project_id": "kk-video-abc123",
        "card_ref": "OPS-0999"})
    reloaded = relay._load_topics()
    assert reloaded["topics"]["9"]["project_id"] == "kk-video-abc123"
    assert reloaded["topics"]["9"]["card_ref"] == "OPS-0999"


def test_registry_rebuilds_from_manifest(monkeypatch, tmp_path):
    """Restart persistence: a lost topics.json heals from project
    manifests, which are the source of truth."""
    sent, posts = _harness(monkeypatch, tmp_path)
    project = tmp_path / "projects" / "kk-video-abc123"
    project.mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({
        "project_id": "kk-video-abc123", "card_ref": "OPS-0999",
        "card_id": "kk-video-abc123",
        "topic": {"thread_id": 9, "name": "PRJ kk-video-abc123 — Movie",
                  "status": "active"}}))
    entry = relay._topic_entry(9)
    assert entry["kind"] == "project"
    assert entry["project_id"] == "kk-video-abc123"
    assert entry["card_ref"] == "OPS-0999"


def test_rollback_marks_entry_never_deletes(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay._register_topic(9, {
        "kind": "project", "name": "PRJ p — t", "lane": "project",
        "visibility": "project", "project_id": "kk-video-abc123"})
    entry = relay._rollback_topic_binding(9, "bind failed")
    assert entry["status"] == "rolled_back"
    assert _topics(tmp_path)["9"]["status"] == "rolled_back"
    # binding history stays; routing skips rolled-back entries
    assert relay._find_project_topic("kk-video-abc123") is None
    with pytest.raises(RuntimeError, match="never deleted"):
        relay._api("deleteForumTopic", {"chat_id": CHAT,
                                        "message_thread_id": 9})


# --- per-topic card context + read-only follow-ups ---------------------------


def _audit_events(tmp_path):
    return [json.loads(line) for line in
            (tmp_path / "audit.jsonl").read_text().splitlines()]


def test_parse_followup_anchored_phrases():
    assert relay.parse_followup("easier.") == ("simple", None)
    assert relay.parse_followup("in Thai") == ("thai", None)
    assert relay.parse_followup("what evidence?") == ("evidence", None)
    assert relay.parse_followup("what's next") == ("next", None)
    assert relay.parse_followup("why") == ("why", None)
    assert relay.parse_followup("history") == ("history", None)
    assert relay.parse_followup("spec") == ("spec", None)
    # embedded ref overrides context; filler words are ignored
    assert relay.parse_followup("0959 with easy language.") == \
        ("simple", "OPS-0959")
    assert relay.parse_followup("spec ops-0905") == ("spec", "OPS-0905")
    # ordinary chat never matches
    assert relay.parse_followup("the next meeting is monday") is None
    # leftover non-alias words keep ordinary chat from matching
    assert relay.parse_followup("what happened in 2026") is None
    assert relay.parse_followup("what happened") == ("history", None)
    assert relay.parse_followup("hello") is None
    assert relay.parse_followup("please explain 0905") is None


def test_explain_sets_durable_context(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain 0905"))
    contexts = json.loads(
        (tmp_path / "card-context.json").read_text())["contexts"]
    record = contexts[f"{CHAT}:0"]
    assert record["card_ref"] == "OPS-0905"
    assert record["card_id"] == "devnest-telegram-team-channel"
    assert record["sender_id"] == TONY
    assert record["at"]


def test_context_followup_resolves_last_card(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain 0905"))
    relay.handle_update(_update("easier.", update_id=2))
    assert posts == []  # follow-ups never mutate the board
    reply = sent[-1]["text"]
    assert "in plain terms" in reply
    assert "Connect DevNest household AI team" in reply
    assert "being worked on by idc02" in reply
    audit = _audit_events(tmp_path)
    assert audit[-1]["result"] == "followup_ok"
    assert audit[-1]["kind"] == "simple"
    assert audit[-1]["card"] == "devnest-telegram-team-channel"
    assert audit[-1]["ref_source"] == "context"


def test_followup_fetches_fresh_board_state(monkeypatch, tmp_path):
    """Context stores the card identity only — every reply re-reads the
    board, so edits between messages are reflected."""
    sent, posts = _harness(monkeypatch, tmp_path)
    fetches = []
    index = {"OPS-0905": [CARD], "devnest-telegram-team-channel": [CARD]}
    monkeypatch.setattr(
        relay, "_card_index", lambda: fetches.append(1) or index)
    relay.handle_update(_update("explain 0905"))
    moved = dict(CARD, column="review", action={}, note="verify on staging")
    index["OPS-0905"] = index["devnest-telegram-team-channel"] = [moved]
    relay.handle_update(_update("what next?", update_id=2))
    assert len(fetches) == 2
    reply = sent[-1]["text"]
    assert "verify on staging" in reply
    assert "running" not in reply


def test_followup_without_context_asks_for_ref(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("easier"))
    assert "name a ref" in sent[-1]["text"]
    audit = _audit_events(tmp_path)
    assert audit[-1]["result"] == "need_ref"
    assert audit[-1]["detail"] == "no card in context"


def test_followup_expired_context_asks_for_ref(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain 0905"))
    monkeypatch.setattr(relay, "CONTEXT_TTL", -1)
    relay.handle_update(_update("next", update_id=2))
    assert "expired" in sent[-1]["text"]
    assert "OPS-0905" in sent[-1]["text"]
    audit = _audit_events(tmp_path)
    assert audit[-1]["result"] == "need_ref"
    assert audit[-1]["detail"].startswith("context for OPS-0905 expired")


def test_followup_wrong_sender_asks_for_ref(monkeypatch, tmp_path):
    """Another sender's follow-up is ambiguous — ask for a ref rather
    than guessing across people."""
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain 0905"))
    relay.handle_update(_update("easier", sender=OTHER, update_id=2))
    assert "another sender" in sent[-1]["text"]
    audit = _audit_events(tmp_path)
    assert audit[-1]["result"] == "need_ref"
    assert audit[-1]["context"] == "wrong_sender"


def test_followup_wrong_topic_has_no_context(monkeypatch, tmp_path):
    """Context is per (chat, thread): explaining in one topic does not
    leak into another."""
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_forum_created("Ops", 42))
    relay.handle_update(_forum_created("Research", 43, update_id=51))
    relay.handle_update(_update("explain 0905", thread=42, update_id=2))
    relay.handle_update(_update("easier", thread=43, update_id=3))
    assert "name a ref" in sent[-1]["text"]
    assert sent[-1]["thread"] == 43
    # ...and the context still answers in the topic that set it
    relay.handle_update(_update("easier", thread=42, update_id=4))
    assert "in plain terms" in sent[-1]["text"]
    assert sent[-1]["thread"] == 42


def test_followup_explicit_ref_ignores_context(monkeypatch, tmp_path):
    """'0959 with easy language' resolves the named card, not the
    topic context."""
    other = dict(CARD, id="other-card", ref="OPS-0999",
                 title="Other card entirely", column="backlog", action={})
    sent, posts = _harness(monkeypatch, tmp_path, cards=[CARD, other])
    relay.handle_update(_update("explain 0905"))
    relay.handle_update(
        _update("0999 with easy language.", update_id=2))
    reply = sent[-1]["text"]
    assert "Other card entirely" in reply
    # context now points at the card that was actually discussed
    contexts = json.loads(
        (tmp_path / "card-context.json").read_text())["contexts"]
    assert contexts[f"{CHAT}:0"]["card_ref"] == "OPS-0999"


def test_followup_unknown_ref_refused(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("OPS-0912 evidence"))
    assert posts == []
    assert "unknown ref OPS-0912" in sent[-1]["text"]
    audit = _audit_events(tmp_path)
    assert audit[-1]["result"] == "refused"
    assert audit[-1]["command"] == "followup"


def test_thai_followup_rendering(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain 0905"))
    relay.handle_update(_update("in Thai", update_id=2))
    body = sent[-1]["text"]
    assert "สถานะ:" in body and "ขั้นตอน:" in body
    assert "การยืนยัน:" in body and "ถัดไป:" in body
    assert "คำถามที่รอ:" in body
    assert "กำลังรันโดย idc02" in body
    assert "OPS-0905" in body


def test_bare_explain_uses_context(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain 0905"))
    relay.handle_update(_update("status", update_id=2))
    body = sent[-1]["text"]
    for field in ("status:", "phase:", "verified:", "next:", "ask:"):
        assert field in body
    # with no context a bare explain asks for a ref instead
    relay.handle_update(_forum_created("Ops", 42, update_id=52))
    relay.handle_update(_update("explain", thread=42, update_id=3))
    assert "name a ref" in sent[-1]["text"]


def test_evidence_next_history_spec_replies(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain 0905"))
    relay.handle_update(_update("what evidence?", update_id=2))
    assert "evidence" in sent[-1]["text"]
    assert "Verified relay capture" in sent[-1]["text"]
    relay.handle_update(_update("history", update_id=3))
    assert "history" in sent[-1]["text"]
    assert "Verified capture path" in sent[-1]["text"]
    spec_card = dict(CARD, spec="do the thing", brief="why it matters")
    monkeypatch.setattr(relay, "_card_index", lambda: {
        "OPS-0905": [spec_card],
        "devnest-telegram-team-channel": [spec_card]})
    relay.handle_update(_update("spec", update_id=4))
    assert "spec" in sent[-1]["text"]
    assert "do the thing" in sent[-1]["text"]
    assert posts == []


def test_approve_still_requires_explicit_ref(monkeypatch, tmp_path):
    """Context never feeds the mutating verbs — bare APPROVE is refused
    even with a live context."""
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain 0905"))
    relay.handle_update(_update("APPROVE", update_id=2))
    assert posts == []
    assert "usage: APPROVE <ref>" in sent[-1]["text"]
    audit = _audit_events(tmp_path)
    assert audit[-1]["result"] == "refused"
    assert audit[-1]["command"] == "approve"


def test_followup_audit_entries(monkeypatch, tmp_path):
    sent, posts = _harness(monkeypatch, tmp_path)
    relay.handle_update(_update("explain 0905"))
    relay.handle_update(_update("easier", update_id=2))
    relay.handle_update(_update("in thai", update_id=3))
    audit = _audit_events(tmp_path)
    assert audit[0]["result"] == "explained"
    assert audit[1]["kind"] == "simple" and audit[1]["context"] == "hit"
    assert audit[1]["context_ref"] == "OPS-0905"
    assert audit[2]["kind"] == "thai"
    assert all("at" in e for e in audit)
