import json

import pytest
from fastapi.testclient import TestClient

import main


def _mcp_text_payload(obj: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(obj)}]}


def test_google_tasks_sequential_summary_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call(name: str, arguments: dict):
        if name.endswith("google_tasks_auth_status"):
            return _mcp_text_payload({"ok": True})
        if name.endswith("google_tasks_list_tasklists"):
            return _mcp_text_payload({"ok": True, "data": {"items": [{"id": "tl1", "title": "Inbox"}]}})
        if name.endswith("google_tasks_list_tasks"):
            return _mcp_text_payload(
                {
                    "ok": True,
                    "data": {
                        "items": [
                            {"id": "t1", "title": "One", "status": "needsAction", "notes": "- [ ] a\n- [ ] b\n"},
                            {"id": "t2", "title": "Two", "status": "completed", "notes": "- [x] s1\n- [x] s2\n"},
                            {"id": "t3", "title": "Three", "status": "completed", "notes": "[x] s1\n[x] s2\n"},
                            {"id": "t4", "title": "Four", "status": "completed", "notes": "- [X] s1\n- [x] s2\n"},
                        ]
                    },
                }
            )
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.get("/google-tasks/sequential/summary")
    assert res.status_code == 200
    data = res.json()

    assert data["ok"] is True
    assert data["tasklist_id"] == "tl1"
    assert data["tasklist_title"] == "Inbox"
    assert isinstance(data["tasks"], list)

    t1 = next(t for t in data["tasks"] if t["task_id"] == "t1")
    assert t1["next_step_text"] == "a"
    assert t1["next_step_index"] == 0

    assert data["template"] == ["s1", "s2"]


def test_google_tasks_sequential_summary_tasklist_title_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call(name: str, arguments: dict):
        if name.endswith("google_tasks_auth_status"):
            return _mcp_text_payload({"ok": True})
        if name.endswith("google_tasks_list_tasklists"):
            return _mcp_text_payload(
                {
                    "ok": True,
                    "data": {
                        "items": [
                            {"id": "tl1", "title": "Inbox"},
                            {"id": "tl2", "title": "Chaba"},
                        ]
                    },
                }
            )
        if name.endswith("google_tasks_list_tasks"):
            assert arguments.get("tasklist_id") == "tl2"
            return _mcp_text_payload({"ok": True, "data": {"items": []}})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.get("/google-tasks/sequential/summary?tasklist_title=Chaba")
    assert res.status_code == 200
    data = res.json()
    assert data["tasklist_id"] == "tl2"
    assert data["tasklist_title"] == "Chaba"


def test_google_tasks_sequential_summary_filters_and_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call(name: str, arguments: dict):
        if name.endswith("google_tasks_auth_status"):
            return _mcp_text_payload({"ok": True})
        if name.endswith("google_tasks_list_tasklists"):
            return _mcp_text_payload({"ok": True, "data": {"items": [{"id": "tl1", "title": "Inbox"}]}})
        if name.endswith("google_tasks_list_tasks"):
            return _mcp_text_payload(
                {
                    "ok": True,
                    "data": {
                        "items": [
                            {"id": "t1", "title": "No notes", "status": "needsAction", "notes": ""},
                            {"id": "t2", "title": "Has notes", "status": "needsAction", "notes": "hello"},
                            {"id": "t3", "title": "Checklist", "status": "needsAction", "notes": "- [ ] a\n"},
                            {"id": "t4", "title": "Done", "status": "completed", "notes": "- [ ] a\n"},
                        ]
                    },
                }
            )
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.get(
        "/google-tasks/sequential/summary?only_incomplete=true&only_with_notes=true&only_with_checklists=true&include_notes=false&debug=true"
    )
    assert res.status_code == 200
    data = res.json()
    # Only task t3 should survive all filters.
    assert [t["task_id"] for t in data["tasks"]] == ["t3"]
    assert data["tasks"][0]["notes"] == ""
    assert data["tasks"][0]["next_step_text"] == "a"
    assert isinstance(data.get("debug"), dict)
    assert data["debug"].get("tasks_raw_count") == 4


def test_google_tasks_sequential_summary_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call(name: str, arguments: dict):
        if name.endswith("google_tasks_auth_status"):
            return _mcp_text_payload({"ok": False})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.get("/google-tasks/sequential/summary")
    assert res.status_code == 401
    assert res.json()["detail"] == "google_tasks_not_authenticated"


def test_google_tasks_sequential_summary_propagates_http_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call(name: str, arguments: dict):
        if name.endswith("google_tasks_auth_status"):
            raise main.HTTPException(
                status_code=403,
                detail={
                    "error": "google_tools_disabled",
                    "tool": name,
                    "required_sys_kv_key": "google.tasks.enabled",
                },
            )
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    client = TestClient(main.app)
    res = client.get("/google-tasks/sequential/summary")
    assert res.status_code == 403
    detail = res.json().get("detail")
    assert isinstance(detail, dict)
    assert detail.get("error") == "google_tools_disabled"
