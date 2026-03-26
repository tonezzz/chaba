"""Smoke tests for the /jarvis/api/debug/status endpoint.

These tests import the FastAPI app directly (no real network) and assert
the response contract that the Jarvis UI depends on.
"""
from __future__ import annotations

import sys
import os

# Allow `from main import ...` when running pytest from the services/jarvis dir
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from main import app, build_debug_status

client = TestClient(app)

ENDPOINT = "/jarvis/api/debug/status"


class TestDebugStatusRoute:
    """Integration-style tests using FastAPI's TestClient (no live network)."""

    def test_returns_http_200(self):
        response = client.get(ENDPOINT)
        assert response.status_code == 200

    def test_response_is_json(self):
        response = client.get(ENDPOINT)
        # Will raise if Content-Type is not application/json
        data = response.json()
        assert isinstance(data, dict)

    def test_ok_field_present_and_bool(self):
        response = client.get(ENDPOINT)
        data = response.json()
        assert "ok" in data, "'ok' key missing from response"
        assert isinstance(data["ok"], bool), f"'ok' must be bool, got {type(data['ok'])}"

    def test_deps_field_present_and_list(self):
        response = client.get(ENDPOINT)
        data = response.json()
        assert "deps" in data, "'deps' key missing from response"
        assert isinstance(data["deps"], list), f"'deps' must be list, got {type(data['deps'])}"

    def test_version_field_present_and_string(self):
        response = client.get(ENDPOINT)
        data = response.json()
        assert "version" in data, "'version' key missing from response"
        assert isinstance(data["version"], str)

    def test_no_unexpected_5xx(self):
        """Endpoint must never return a server error, even under default conditions."""
        response = client.get(ENDPOINT)
        assert response.status_code < 500


class TestBuildDebugStatusUnit:
    """Unit tests for the build_debug_status() helper (no HTTP layer)."""

    def test_returns_dict(self):
        result = build_debug_status()
        assert isinstance(result, dict)

    def test_ok_is_bool(self):
        result = build_debug_status()
        assert isinstance(result["ok"], bool)

    def test_deps_is_list(self):
        result = build_debug_status()
        assert isinstance(result["deps"], list)

    def test_ok_true_when_no_deps(self):
        """With an empty dependency list the overall status should be healthy."""
        result = build_debug_status()
        if not result["deps"]:
            assert result["ok"] is True

    def test_shape_keys(self):
        result = build_debug_status()
        assert {"ok", "deps", "version"}.issubset(result.keys())
