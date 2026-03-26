"""
Contract tests for jarvis-backend /jarvis/api/debug/status endpoint.

These tests import the real FastAPI application from main.py and exercise the
production route definitions using FastAPI's built-in TestClient (no external
network required).
"""
from __future__ import annotations

import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Stub any optional heavyweight dependencies before importing main so that
# the test can run in a minimal CI environment without them installed.
# (Add stubs here if main.py ever gains optional deps like google-genai.)
# ---------------------------------------------------------------------------


def _ensure_stub(module_name: str) -> None:
    """Insert an empty stub module if it is not already importable."""
    if module_name not in sys.modules:
        parts = module_name.split(".")
        for i in range(1, len(parts) + 1):
            pkg = ".".join(parts[:i])
            if pkg not in sys.modules:
                sys.modules[pkg] = types.ModuleType(pkg)


# No optional deps in the current main.py, but the helper is ready if needed.


from fastapi.testclient import TestClient  # noqa: E402  (after potential stubs)

from main import app  # noqa: E402

client = TestClient(app)

# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

ROUTE = "/jarvis/api/debug/status"


class TestDebugStatusRoute:
    """Contract tests for the /jarvis/api/debug/status endpoint."""

    def test_route_exists_and_returns_200(self) -> None:
        """The endpoint must exist and respond with HTTP 200."""
        response = client.get(ROUTE)
        assert response.status_code == 200, (
            f"Expected HTTP 200 from {ROUTE}, got {response.status_code}"
        )

    def test_response_is_json(self) -> None:
        """The response must be valid JSON."""
        response = client.get(ROUTE)
        data = response.json()
        assert isinstance(data, dict), "Response body must be a JSON object"

    def test_response_contains_ok_bool(self) -> None:
        """Response must contain an 'ok' key with a boolean value."""
        response = client.get(ROUTE)
        data = response.json()
        assert "ok" in data, "Response JSON must contain 'ok'"
        assert isinstance(data["ok"], bool), f"'ok' must be bool, got {type(data['ok'])}"

    def test_response_contains_deps_list(self) -> None:
        """Response must contain a 'deps' key with a list value."""
        response = client.get(ROUTE)
        data = response.json()
        assert "deps" in data, "Response JSON must contain 'deps'"
        assert isinstance(data["deps"], list), f"'deps' must be list, got {type(data['deps'])}"

    def test_no_5xx_even_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Endpoint must never return 5xx; dependency failures belong in the payload."""
        import main as _main

        monkeypatch.setattr(_main, "GEMINI_API_KEY", "")
        response = client.get(ROUTE)
        assert response.status_code < 500, (
            f"Endpoint must not return 5xx; got {response.status_code}"
        )
        data = response.json()
        assert "ok" in data
        assert "deps" in data

    def test_deps_entries_have_required_fields(self) -> None:
        """Each entry in 'deps' must have 'name' (str) and 'ok' (bool)."""
        response = client.get(ROUTE)
        deps = response.json()["deps"]
        for entry in deps:
            assert "name" in entry, f"dep entry missing 'name': {entry}"
            assert "ok" in entry, f"dep entry missing 'ok': {entry}"
            assert isinstance(entry["name"], str), f"dep 'name' must be str: {entry}"
            assert isinstance(entry["ok"], bool), f"dep 'ok' must be bool: {entry}"

    def test_base_debug_status_route_also_works(self) -> None:
        """The shorter /debug/status alias must also return 200 with the same shape."""
        response = client.get("/debug/status")
        assert response.status_code == 200
        data = response.json()
        assert "ok" in data
        assert "deps" in data
