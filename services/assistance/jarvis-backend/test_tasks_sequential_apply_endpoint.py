from fastapi.testclient import TestClient

from main import app


def test_tasks_sequential_apply_marks_step_done() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply",
        json={"notes": "- [ ] a\n- [ ] b\n", "step_index": 1},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["changed"] is True
    assert data["notes"] == "- [ ] a\n- [x] b\n"


def test_tasks_sequential_apply_is_idempotent() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply",
        json={"notes": "- [x] a\n", "step_index": 0},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["changed"] is False
    assert data["notes"] == "- [x] a\n"
