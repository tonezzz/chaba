"""Contract tests for /jarvis/api/verify/status.

These tests are deterministic and require no external network access.
Network-dependent functions are monkeypatched to return fixed payloads.
"""
import pytest
from fastapi.testclient import TestClient

import main

_FIXED_DEBUG_STATUS: dict = {
    "ok": True,
    "service": "jarvis-backend",
    "instance_id": "test-instance",
    "ts": 0,
    "checks": [],
}

_FIXED_FRONTEND_CHECK: dict = {
    "name": "jarvis-frontend",
    "ok": True,
    "url": "http://stub.local/jarvis/",
}


@pytest.fixture()
def _patch_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace all network-dependent callables with deterministic stubs."""

    async def _fake_debug_status() -> dict:
        return dict(_FIXED_DEBUG_STATUS)

    async def _fake_verify_frontend_bundle(base_url: str, *, timeout_s: float = 6.0) -> dict:
        return dict(_FIXED_FRONTEND_CHECK)

    monkeypatch.setattr(main, "debug_status", _fake_debug_status)
    monkeypatch.setattr(main, "_verify_frontend_bundle", _fake_verify_frontend_bundle)


def test_verify_status_route_returns_200(_patch_network) -> None:
    client = TestClient(main.app)
    res = client.get("/jarvis/api/verify/status")
    assert res.status_code == 200


def test_verify_status_response_is_json(_patch_network) -> None:
    client = TestClient(main.app)
    res = client.get("/jarvis/api/verify/status")
    data = res.json()
    assert isinstance(data, dict)


def test_verify_status_ok_is_bool(_patch_network) -> None:
    client = TestClient(main.app)
    res = client.get("/jarvis/api/verify/status")
    data = res.json()
    assert isinstance(data["ok"], bool)


def test_verify_status_checks_is_list(_patch_network) -> None:
    client = TestClient(main.app)
    res = client.get("/jarvis/api/verify/status")
    data = res.json()
    assert isinstance(data["checks"], list)


def test_verify_status_checks_contain_required_names(_patch_network) -> None:
    client = TestClient(main.app)
    res = client.get("/jarvis/api/verify/status")
    data = res.json()
    names = {c["name"] for c in data["checks"] if isinstance(c, dict) and "name" in c}
    assert "jarvis-backend" in names
    assert "jarvis-backend-debug-status" in names
    assert "jarvis-frontend" in names
