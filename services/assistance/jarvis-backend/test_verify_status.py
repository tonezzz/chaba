import pytest
from fastapi.testclient import TestClient

import main


async def _stub_debug_status() -> dict:
    return {"ok": True, "checks": []}


async def _stub_verify_frontend_bundle(base_url: str, *, timeout_s: float = 6.0) -> dict:
    return {"name": "jarvis-frontend", "ok": True, "markers": {}}


def test_verify_status_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "debug_status", _stub_debug_status)
    monkeypatch.setattr(main, "_verify_frontend_bundle", _stub_verify_frontend_bundle)
    monkeypatch.setattr(main, "feature_enabled", lambda _name: True)

    client = TestClient(main.app)
    res = client.get("/jarvis/api/verify/status")

    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, dict)
    assert isinstance(data["ok"], bool)
    assert isinstance(data["checks"], list)

    names = {c["name"] for c in data["checks"] if isinstance(c, dict)}
    assert "jarvis-backend" in names
    assert "jarvis-backend-debug-status" in names
    assert "jarvis-frontend" in names
