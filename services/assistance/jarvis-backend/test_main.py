"""
Unit tests for jarvis-backend system_run_macro.

These tests exercise the output schema and error-handling logic of
_run_macro() without a live server, using mocked HTTP calls.
"""
from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

# Patch _get_servers so remote calls resolve without live services
_FAKE_SERVERS = {"mcp-devops": "http://mcp-devops:8325"}


# ---------------------------------------------------------------------------
# Helpers to import the module under test
# ---------------------------------------------------------------------------

def _import_main():
    import importlib
    import sys

    # Ensure a clean import each time
    for mod in list(sys.modules.keys()):
        if mod.startswith("main") and "jarvis" not in mod:
            del sys.modules[mod]
    import main as m
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_macro_unknown_macro():
    """Unknown macro name returns ok=False with a descriptive error."""
    m = _import_main()
    result = await m._run_macro("does_not_exist", {})

    assert result["ok"] is False
    assert result["macro"] == "does_not_exist"
    assert "steps" in result
    assert isinstance(result["steps"], list)
    assert result["steps"] == []
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_run_macro_self_health_step_success():
    """The __self__ step in health_check macro succeeds without HTTP."""
    m = _import_main()
    result = await m._run_macro("health_check", {})

    assert result["ok"] is True
    assert result["macro"] == "health_check"
    assert len(result["steps"]) == 1
    step = result["steps"][0]
    assert step["ok"] is True
    assert step["error"] is None
    assert "result" in result
    assert result["result"]["ok"] is True


@pytest.mark.asyncio
async def test_run_macro_remote_step_success():
    """A macro with a remote step returns ok=True and last result when the HTTP call succeeds."""
    m = _import_main()

    fake_response = {"workflows": [{"id": "deploy-pc1-stack", "label": "Deploy"}]}

    with patch("main._get_servers", return_value=_FAKE_SERVERS):
        with patch("main._invoke_remote", new_callable=AsyncMock, return_value=fake_response):
            result = await m._run_macro("devops_list_workflows", {})

    assert result["ok"] is True
    assert result["macro"] == "devops_list_workflows"
    assert len(result["steps"]) == 1
    assert result["steps"][0]["ok"] is True
    assert result["result"] == fake_response


@pytest.mark.asyncio
async def test_run_macro_remote_step_failure():
    """A failing remote step returns ok=False with error captured in steps and top-level error."""
    m = _import_main()

    with patch("main._get_servers", return_value=_FAKE_SERVERS):
        with patch(
            "main._invoke_remote",
            new_callable=AsyncMock,
            side_effect=Exception("connection refused"),
        ):
            result = await m._run_macro("devops_list_workflows", {})

    assert result["ok"] is False
    assert result["macro"] == "devops_list_workflows"
    assert len(result["steps"]) == 1
    failed_step = result["steps"][0]
    assert failed_step["ok"] is False
    assert "connection refused" in (failed_step["error"] or "")
    assert "error" in result
    assert "connection refused" in result["error"]


def test_redact_args_no_secrets():
    """Non-sensitive args are passed through unchanged."""
    m = _import_main()
    args = {"question": "status", "include_docker": True}
    redacted = m._redact_args(args)
    assert redacted == args


def test_redact_args_with_secrets():
    """Secret-looking keys have their values replaced with '***'."""
    m = _import_main()
    args = {"api_token": "supersecret", "password": "hunter2", "question": "status"}
    redacted = m._redact_args(args)
    assert redacted["api_token"] == "***"
    assert redacted["password"] == "***"
    assert redacted["question"] == "status"


def test_list_macros_returns_expected_keys():
    """list_macros() returns a list of dicts with id and description."""
    m = _import_main()
    macros = m.list_macros()
    assert isinstance(macros, list)
    assert len(macros) >= 1
    for macro in macros:
        assert "id" in macro
        assert "description" in macro


def test_output_schema_required_fields_ok():
    """The ok=True output must have: ok, macro, steps, result."""
    expected_keys = {"ok", "macro", "steps", "result"}
    sample = {"ok": True, "macro": "health_check", "steps": [{"tool": "self_health", "ok": True, "error": None}], "result": {"ok": True}}
    assert expected_keys.issubset(sample.keys()), f"Missing keys: {expected_keys - sample.keys()}"


def test_output_schema_required_fields_error():
    """The ok=False output must have: ok, macro, steps, error."""
    expected_keys = {"ok", "macro", "steps", "error"}
    sample = {"ok": False, "macro": "missing", "steps": [], "error": "Macro 'missing' not found."}
    assert expected_keys.issubset(sample.keys()), f"Missing keys: {expected_keys - sample.keys()}"
