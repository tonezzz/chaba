from fastapi.testclient import TestClient

from main import app


def test_tasks_sequential_apply_by_text_marks_step_done() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply_by_text",
        json={"notes": "- [ ] a\n- [ ] b\n", "step_text": "b"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["changed"] is True
    assert data["matched_step_index"] == 1
    assert data["notes"] == "- [ ] a\n- [x] b\n"


def test_tasks_sequential_apply_all_marks_all_steps_done() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply_all",
        json={"notes": "- [ ] a\n- [x] b\n"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["changed"] is True
    assert data["changed_count"] == 1
    assert data["notes"] == "- [x] a\n- [x] b\n"
