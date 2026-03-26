#!/usr/bin/env python3
"""
Lightweight test suite for jarvis-backend.

Run against a live instance:
  JARVIS_BASE_URL=http://127.0.0.1:18018 python test_main.py

Or start the service locally first:
  uvicorn main:app --port 18018
  python test_main.py
"""
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    print("requests not installed — run: pip install requests")
    sys.exit(1)

BASE_URL = os.getenv("JARVIS_BASE_URL", "http://127.0.0.1:18018").rstrip("/")


def _invoke(tool: str, arguments: dict | None = None) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/invoke",
        json={"tool": tool, "arguments": arguments or {}},
        timeout=10,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health() -> bool:
    print("Testing GET /health ...")
    r = requests.get(f"{BASE_URL}/health", timeout=10)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert data.get("ok") is True, f"Expected ok=true, got {data}"
    assert "macros_count" in data, f"Expected macros_count field, got {data}"
    print("  PASS /health")
    return True


def test_debug_status() -> bool:
    print("Testing GET /jarvis/api/debug/status ...")
    r = requests.get(f"{BASE_URL}/jarvis/api/debug/status", timeout=10)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert data.get("ok") is True, f"Expected ok=true, got {data}"
    assert "dependencies" in data, f"Expected dependencies, got {data}"
    print("  PASS /jarvis/api/debug/status")
    return True


def test_mcp_manifest() -> bool:
    print("Testing GET /.well-known/mcp.json ...")
    r = requests.get(f"{BASE_URL}/.well-known/mcp.json", timeout=10)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    tool_names = {t["name"] for t in data.get("capabilities", {}).get("tools", [])}
    assert "system_reload_macros" in tool_names, f"system_reload_macros missing from tools: {tool_names}"
    assert "system_macros_reload" in tool_names, f"system_macros_reload missing from tools: {tool_names}"
    assert "system_reload" in tool_names, f"system_reload missing from tools: {tool_names}"
    print("  PASS manifest exposes all three tools")
    return True


def test_system_reload_macros_all() -> bool:
    print("Testing system_reload_macros mode=all ...")
    r = _invoke("system_reload_macros", {"mode": "all"})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("ok") is True, f"Expected ok=true, got {data}"
    assert data.get("mode") == "all", f"Expected mode=all, got {data}"
    assert "loaded" in data, f"Expected loaded key, got {data}"
    print("  PASS system_reload_macros mode=all")
    return True


def test_system_reload_macros_default_mode() -> bool:
    print("Testing system_reload_macros without mode (defaults to all) ...")
    r = _invoke("system_reload_macros", {})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("mode") == "all", f"Expected mode=all by default, got {data}"
    print("  PASS system_reload_macros default mode=all")
    return True


def test_system_reload_macros_by_id_missing_param() -> bool:
    print("Testing system_reload_macros mode=by_id without id (should 422) ...")
    r = _invoke("system_reload_macros", {"mode": "by_id"})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    print("  PASS system_reload_macros mode=by_id missing id → 422")
    return True


def test_system_reload_macros_by_name_missing_param() -> bool:
    print("Testing system_reload_macros mode=by_name without name (should 422) ...")
    r = _invoke("system_reload_macros", {"mode": "by_name"})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    print("  PASS system_reload_macros mode=by_name missing name → 422")
    return True


def test_system_reload_macros_unknown_mode() -> bool:
    print("Testing system_reload_macros with unknown mode (should 422) ...")
    r = _invoke("system_reload_macros", {"mode": "bad_mode"})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    print("  PASS system_reload_macros unknown mode → 422")
    return True


def test_system_macros_reload_alias() -> bool:
    print("Testing system_macros_reload (deprecated alias) ...")
    r = _invoke("system_macros_reload", {})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("ok") is True, f"Expected ok=true, got {data}"
    assert data.get("mode") == "all", f"Expected alias to default to mode=all, got {data}"
    print("  PASS system_macros_reload alias works, defaults to mode=all")
    return True


def test_system_macros_reload_alias_by_id() -> bool:
    print("Testing system_macros_reload alias with mode=by_id (should 404, no macros loaded) ...")
    r = _invoke("system_macros_reload", {"mode": "by_id", "id": "nonexistent-id"})
    # No macros file → 404 for specific id
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
    print("  PASS system_macros_reload alias forwards mode correctly → 404 for missing id")
    return True


def test_macros_list_endpoint() -> bool:
    print("Testing GET /macros ...")
    r = requests.get(f"{BASE_URL}/macros", timeout=10)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert "macros" in data, f"Expected 'macros' key, got {data}"
    assert isinstance(data["macros"], list), f"Expected list, got {data}"
    print("  PASS /macros returns list")
    return True


def test_system_reload_calls_macros() -> bool:
    print("Testing system_reload (should include macros component by default) ...")
    r = _invoke("system_reload", {})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("ok") is True, f"Expected ok=true, got {data}"
    assert "macros" in data.get("components", {}), f"Expected macros component, got {data}"
    assert data["components"]["macros"].get("mode") == "all", f"Expected mode=all in macros component, got {data}"
    print("  PASS system_reload includes macros component with mode=all")
    return True


def test_system_reload_bypass_macros() -> bool:
    print("Testing system_reload with bypass_macros=true ...")
    r = _invoke("system_reload", {"bypass_macros": True})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("ok") is True, f"Expected ok=true, got {data}"
    assert "macros" not in data.get("components", {}), f"Expected no macros component, got {data}"
    print("  PASS system_reload bypass_macros=true skips macros")
    return True


def test_unknown_tool() -> bool:
    print("Testing unknown tool (should 404) ...")
    r = _invoke("nonexistent_tool", {})
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
    print("  PASS unknown tool → 404")
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all_tests() -> bool:
    print(f"\n🧪  jarvis-backend test suite  →  {BASE_URL}\n")

    tests = [
        test_health,
        test_debug_status,
        test_mcp_manifest,
        test_macros_list_endpoint,
        test_system_reload_macros_all,
        test_system_reload_macros_default_mode,
        test_system_reload_macros_by_id_missing_param,
        test_system_reload_macros_by_name_missing_param,
        test_system_reload_macros_unknown_mode,
        test_system_macros_reload_alias,
        test_system_macros_reload_alias_by_id,
        test_system_reload_calls_macros,
        test_system_reload_bypass_macros,
        test_unknown_tool,
    ]

    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            print(f"  FAIL {t.__name__}: {exc}")
            failed += 1
        print()

    print(f"📊  Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("🎉  All tests passed!")
        return True
    print("💥  Some tests failed!")
    return False


if __name__ == "__main__":
    time.sleep(1)
    ok = run_all_tests()
    sys.exit(0 if ok else 1)
