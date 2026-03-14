import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import main


def _mcp_text_payload(obj: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(obj)}]}


def _isolate_session_db(monkeypatch: pytest.MonkeyPatch) -> None:
    tmpdir = tempfile.mkdtemp(prefix="jarvis_test_")
    monkeypatch.setattr(main, "SESSION_DB_PATH", os.path.join(tmpdir, "session.sqlite"))


def test_google_calendar_undo_list_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    client = TestClient(main.app)
    res = client.get("/google-calendar/undo/list?limit=10")
    assert res.status_code == 200
    assert res.json() == {"ok": True, "items": []}


def test_google_calendar_undo_last_requires_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    main._google_calendar_undo_log("google_calendar_create_event", "e1", before=None, after={"id": "e1"})

    client = TestClient(main.app)
    res = client.post("/google-calendar/undo/last", json={"n": 1})
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["requires_confirmation"] is True
    assert detail["action"] == "google_calendar_undo_last"


def test_google_calendar_undo_last_create_deletes_event(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if name.endswith("google_calendar_delete_event"):
            return _mcp_text_payload({"ok": True})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    main._google_calendar_undo_log("google_calendar_create_event", "e1", before=None, after={"id": "e1"})

    client = TestClient(main.app)
    res = client.post("/google-calendar/undo/last", json={"n": 1, "confirm": True})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["undone"] == 1
    assert any(n.endswith("google_calendar_delete_event") for n, _ in calls)


def test_google_calendar_undo_last_update_reverts_event(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if name.endswith("google_calendar_update_event"):
            return _mcp_text_payload({"ok": True, "data": {"id": arguments.get("event_id")}})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    before = {
        "id": "e1",
        "summary": "Before",
        "description": "desc",
        "start": {"dateTime": "2026-03-14T10:00:00+07:00", "timeZone": "Asia/Bangkok"},
        "end": {"dateTime": "2026-03-14T10:05:00+07:00", "timeZone": "Asia/Bangkok"},
    }
    main._google_calendar_undo_log("google_calendar_update_event", "e1", before=before, after={"id": "e1"})

    client = TestClient(main.app)
    res = client.post("/google-calendar/undo/last", json={"n": 1, "confirm": True})
    assert res.status_code == 200
    assert res.json()["undone"] == 1
    assert any(n.endswith("google_calendar_update_event") for n, _ in calls)


def test_google_calendar_undo_last_delete_recreates_event(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if name.endswith("google_calendar_create_event"):
            return _mcp_text_payload({"ok": True, "data": {"id": "e2"}})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    before = {
        "id": "e1",
        "summary": "Meeting",
        "description": "desc",
        "start": {"dateTime": "2026-03-14T10:00:00+07:00", "timeZone": "Asia/Bangkok"},
        "end": {"dateTime": "2026-03-14T10:05:00+07:00", "timeZone": "Asia/Bangkok"},
    }
    main._google_calendar_undo_log("google_calendar_delete_event", "e1", before=before, after=None)

    client = TestClient(main.app)
    res = client.post("/google-calendar/undo/last", json={"n": 1, "confirm": True})
    assert res.status_code == 200
    assert res.json()["undone"] == 1
    assert any(n.endswith("google_calendar_create_event") for n, _ in calls)
