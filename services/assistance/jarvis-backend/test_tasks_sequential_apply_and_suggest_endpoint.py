from fastapi.testclient import TestClient

from main import app


def test_apply_and_suggest_suggest_only() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply_and_suggest",
        json={"mode": "suggest", "notes": "- [ ] a\n- [ ] b\n"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["changed"] is False
    assert data["notes"] == "- [ ] a\n- [ ] b\n"
    assert data["next_step_text"] == "a"
    assert data["next_step_index"] == 0


def test_apply_and_suggest_index_mode() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply_and_suggest",
        json={"mode": "index", "notes": "- [ ] a\n- [ ] b\n", "step_index": 0},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["changed"] is True
    assert data["notes"].startswith("- [x] a")
    assert data["next_step_text"] == "b"


def test_apply_and_suggest_text_mode_sets_matched_index() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply_and_suggest",
        json={"mode": "text", "notes": "- [ ] a\n- [ ] b\n", "step_text": "b"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["changed"] is True
    assert data["matched_step_index"] == 1
    assert "[x] b" in data["notes"]


def test_apply_and_suggest_all_mode_returns_count() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply_and_suggest",
        json={"mode": "all", "notes": "- [ ] a\n- [x] b\n"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["changed"] is True
    assert data["changed_count"] == 1
    assert data["next_step_text"] is None


def test_apply_and_suggest_text_mode_requires_step_text() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply_and_suggest",
        json={"mode": "text", "notes": "- [ ] a\n"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "missing_step_text"


def test_apply_and_suggest_text_mode_ambiguous_match_returns_409() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply_and_suggest",
        json={"mode": "text", "notes": "- [ ] a\n- [ ] a\n", "step_text": "a"},
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["ambiguous_step_text"] is True
    assert detail["step_text"] == "a"
    assert detail["match_indices"] == [0, 1]


def test_apply_and_suggest_text_mode_ambiguous_match_can_use_hint() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply_and_suggest",
        json={
            "mode": "text",
            "notes": "- [ ] a\n- [ ] a\n",
            "step_text": "a",
            "step_index_hint": 1,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["changed"] is True
    assert data["matched_step_index"] == 1
    assert data["notes"] == "- [ ] a\n- [x] a\n"


def test_apply_and_suggest_text_mode_ambiguous_match_invalid_hint_still_409() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply_and_suggest",
        json={
            "mode": "text",
            "notes": "- [ ] a\n- [ ] a\n",
            "step_text": "a",
            "step_index_hint": 3,
        },
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["match_indices"] == [0, 1]


def test_apply_and_suggest_template_passthrough() -> None:
    client = TestClient(app)
    res = client.post(
        "/tasks/sequential/apply_and_suggest",
        json={
            "mode": "suggest",
            "notes": "- [ ] a\n",
            "completed_tasks": [
                {"notes": "- [x] step one\n- [x] step two\n"},
                {"notes": "[x] step one\n[x] step two\n"},
                {"notes": "- [X] step one\n- [x] step two\n"},
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["template"] == ["step one", "step two"]
