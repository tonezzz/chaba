import os

import pytest
from fastapi.testclient import TestClient

import main


class _FakeGenaiResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeModels:
    def __init__(self, recorder: dict):
        self._recorder = recorder

    async def generate_content(self, *, model: str, contents: str, config: dict):
        self._recorder["model"] = model
        self._recorder["contents"] = contents
        self._recorder["config"] = config
        return _FakeGenaiResponse("OK")


class _FakeAio:
    def __init__(self, recorder: dict):
        self.models = _FakeModels(recorder)


class _FakeClient:
    def __init__(self, *, api_key: str, recorder: dict):
        self.api_key = api_key
        self.aio = _FakeAio(recorder)


def test_gem_demo_uses_system_instruction_and_model_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("GEMINI_TEXT_MODEL", "models/gemini-2.0-flash")

    recorder: dict = {}

    def fake_client(*, api_key: str):
        return _FakeClient(api_key=api_key, recorder=recorder)

    monkeypatch.setattr(main.genai, "Client", fake_client)

    client = TestClient(main.app)
    res = client.post(
        "/gem/demo",
        json={
            "text": "hello",
            "gem": "triage",
            "model": "models/gemini-2.0-flash",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["gem"] == "triage"
    assert data["model"] == "gemini-2.0-flash"
    assert data["text"] == "OK"

    cfg = recorder.get("config")
    assert isinstance(cfg, dict)
    sys = cfg.get("system_instruction")
    assert isinstance(sys, str)
    assert "You are Jarvis. Respond to the user with ONLY the final answer." in sys
    assert "triage mode" in sys


def test_gem_demo_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    client = TestClient(main.app)
    res = client.post("/gem/demo", json={"text": "x"})
    assert res.status_code == 500
    assert res.json()["detail"] == "missing_api_key"
