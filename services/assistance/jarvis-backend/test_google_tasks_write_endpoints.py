import json

import pytest
from fastapi.testclient import TestClient

import main


def _mcp_text_payload(obj: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(obj)}]}


def test_google_tasks_create_requires_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
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
    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if name.endswith("google_tasks_list_tasklists"):
            return _mcp_text_payload({"ok": True, "data": {"items": [{"id": "tl1", "title": "Chaba"}]}})
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
