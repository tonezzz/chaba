import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import main


def _mcp_text_payload(obj: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(obj)}]}


def test_google_tasks_undo_list_and_undo_last(monkeypatch: pytest.MonkeyPatch) -> None:
    # isolate sqlite DB per test
    tmpdir = tempfile.mkdtemp(prefix="jarvis_test_")
    monkeypatch.setattr(main, "SESSION_DB_PATH", os.path.join(tmpdir, "session.sqlite"))

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if name.endswith("google_tasks_list_tasklists"):
            return _mcp_text_payload({"ok": True, "data": {"items": [{"id": "tl1", "title": "Inbox"}]}})
        if name.endswith("google_tasks_create_task"):
            return _mcp_text_payload({"ok": True, "data": {"id": "t1", "title": arguments.get("title"), "notes": arguments.get("notes")}})
        if name.endswith("google_tasks_delete_task"):
            return _mcp_text_payload({"ok": True})
        raise AssertionError(f"unexpected_tool {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)

    # create a task (this should write an undo record)
    res = client.post(
        "/google-tasks/tasks/create",
        json={"tasklist_title": "Inbox", "title": "Undo me", "notes": "x", "confirm": True},
    )
    assert res.status_code == 200

    # list undo records
    res = client.get("/google-tasks/undo/list?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert len(data["items"]) >= 1

    # confirm-gating for undo
    res = client.post("/google-tasks/undo/last", json={"n": 1})
    assert res.status_code == 409

    # perform undo: should call delete_task
    res = client.post("/google-tasks/undo/last", json={"n": 1, "confirm": True})
    assert res.status_code == 200
    out = res.json()
    assert out["ok"] is True
    assert out["undone"] == 1
    assert any(n.endswith("google_tasks_delete_task") for n, _ in calls)
