from fastapi.testclient import TestClient

from main import app


def test_tasks_sequential_suggest_next_step_only() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/suggest",
        json={
            "task": {"notes": "- [x] a\n- [ ] b\n"},
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["next_step_text"] == "b"
    assert data["next_step_index"] == 1
    assert data["template"] is None


def test_tasks_sequential_suggest_with_template() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/suggest",
        json={
            "task": {"notes": "- [x] a\n- [ ] b\n"},
            "completed_tasks": [
                {"notes": "- [x] step one\n- [x] step two\n"},
                {"notes": "[x] step one\n[x] step two\n"},
                {"notes": "- [X] step one\n- [x] step two\n"},
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["next_step_text"] == "b"
    assert data["template"] == ["step one", "step two"]
