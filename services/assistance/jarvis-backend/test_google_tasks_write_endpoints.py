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


def test_google_tasks_create_requires_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    async def fake_call(name: str, arguments: dict):
        raise AssertionError("should_not_call_mcp")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.post(
        "/google-tasks/tasks/create",
        json={"tasklist_title": "Chirawat's list", "title": "X", "notes": "- [ ] a\n"},
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["requires_confirmation"] is True
    assert detail["action"] == "google_tasks_create_task"


def test_google_tasks_create_confirmed_calls_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if name.endswith("google_tasks_list_tasklists"):
            return _mcp_text_payload({"ok": True, "data": {"items": [{"id": "tl1", "title": "Chirawat's list"}]}})
        if name.endswith("google_tasks_create_task"):
            return _mcp_text_payload({"ok": True, "data": {"id": "t1"}})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.post(
        "/google-tasks/tasks/create",
        json={
            "tasklist_title": "Chirawat's list",
            "title": "Jarvis test",
            "notes": "- [ ] step one\n- [ ] step two\n",
            "confirm": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["result"]["ok"] is True

    assert any(n.endswith("google_tasks_list_tasklists") for n, _ in calls)
    assert any(n.endswith("google_tasks_create_task") for n, _ in calls)


def test_google_tasks_update_requires_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    async def fake_call(name: str, arguments: dict):
        raise AssertionError("should_not_call_mcp")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.post(
        "/google-tasks/tasks/update",
        json={"task_id": "t1", "notes": "hello"},
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["requires_confirmation"] is True
    assert detail["action"] == "google_tasks_update_task"


def test_google_tasks_update_confirmed_calls_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if name.endswith("google_tasks_list_tasklists"):
            return _mcp_text_payload({"ok": True, "data": {"items": [{"id": "tl1", "title": "Chaba"}]}})
        if name.endswith("google_tasks_list_tasks"):
            return _mcp_text_payload({"ok": True, "data": {"items": [{"id": "t123", "title": "X", "notes": ""}]}})
        if name.endswith("google_tasks_update_task"):
            return _mcp_text_payload({"ok": True, "data": {"id": arguments.get("task_id")}})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.post(
        "/google-tasks/tasks/update",
        json={
            "tasklist_title": "Chaba",
            "task_id": "t123",
            "notes": "- [x] step one\n- [ ] step two\n",
            "confirm": True,
        },
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert any(n.endswith("google_tasks_update_task") for n, _ in calls)


def test_google_tasks_complete_requires_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    async def fake_call(name: str, arguments: dict):
        raise AssertionError("should_not_call_mcp")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.post(
        "/google-tasks/tasks/complete",
        json={"task_id": "t1"},
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["requires_confirmation"] is True
    assert detail["action"] == "google_tasks_complete_task"


def test_google_tasks_complete_confirmed_calls_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if name.endswith("google_tasks_list_tasklists"):
            return _mcp_text_payload({"ok": True, "data": {"items": [{"id": "tl1", "title": "Chirawat's list"}]}})
        if name.endswith("google_tasks_list_tasks"):
            return _mcp_text_payload({"ok": True, "data": {"items": [{"id": "t123", "title": "X", "notes": "", "status": "needsAction"}]}})
        if name.endswith("google_tasks_complete_task"):
            return _mcp_text_payload({"ok": True, "data": {"id": arguments.get("task_id")}})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.post(
        "/google-tasks/tasks/complete",
        json={"tasklist_title": "Chirawat's list", "task_id": "t123", "confirm": True},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert any(n.endswith("google_tasks_complete_task") for n, _ in calls)


def test_google_tasks_delete_requires_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    async def fake_call(name: str, arguments: dict):
        raise AssertionError("should_not_call_mcp")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.post(
        "/google-tasks/tasks/delete",
        json={"task_id": "t1"},
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["requires_confirmation"] is True
    assert detail["action"] == "google_tasks_delete_task"


def test_google_tasks_delete_confirmed_calls_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_session_db(monkeypatch)

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if name.endswith("google_tasks_list_tasklists"):
            return _mcp_text_payload({"ok": True, "data": {"items": [{"id": "tl1", "title": "Chirawat's list"}]}})
        if name.endswith("google_tasks_list_tasks"):
            return _mcp_text_payload({"ok": True, "data": {"items": [{"id": "t123", "title": "X", "notes": ""}]}})
        if name.endswith("google_tasks_delete_task"):
            return _mcp_text_payload({"ok": True})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.post(
        "/google-tasks/tasks/delete",
        json={"tasklist_title": "Chirawat's list", "task_id": "t123", "confirm": True},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert any(n.endswith("google_tasks_delete_task") for n, _ in calls)
