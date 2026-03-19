import asyncio
import importlib
import json
import sys
from types import ModuleType

import pytest


def _mcp_text_payload(obj: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(obj)}]}


def _import_main_with_genai_stub(monkeypatch: pytest.MonkeyPatch):
    if "google" not in sys.modules:
        sys.modules["google"] = ModuleType("google")
    if "google.genai" not in sys.modules:
        sys.modules["google.genai"] = ModuleType("google.genai")
    if "google.genai.types" not in sys.modules:
        sys.modules["google.genai.types"] = ModuleType("google.genai.types")
    if "google.genai.errors" not in sys.modules:
        sys.modules["google.genai.errors"] = ModuleType("google.genai.errors")

    try:
        setattr(sys.modules["google"], "genai", sys.modules["google.genai"])
    except Exception:
        pass

    try:
        setattr(sys.modules["google.genai"], "types", sys.modules["google.genai.types"])
    except Exception:
        pass

    try:
        setattr(sys.modules["google.genai"], "errors", sys.modules["google.genai.errors"])
    except Exception:
        pass

    if "main" in sys.modules:
        return importlib.reload(sys.modules["main"])
    return importlib.import_module("main")


def test_memo_header_canonical_order_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    calls: list[tuple[str, dict]] = []

    async def fake_sheet_get_header_row(**kwargs):
        # Simulate a legacy/out-of-order header so ensure_header rewrites.
        return [
            "id",
            "active",
            "group",
            "memo",
            "status",
            "subject",
            "result",
            "date_time",
            "_created",
            "_updated",
        ]

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        return _mcp_text_payload({"ok": True, "data": {"updatedRange": arguments.get("range")}})

    awaitable = main.memo_sheet.ensure_header(
        spreadsheet_id="ssid",
        sheet_a1="memo",
        force=False,
        sheet_get_header_row=fake_sheet_get_header_row,
        mcp_tools_call=fake_call,
        pick_sheets_tool_name=lambda a, b: a,
    )
    asyncio.run(awaitable)

    upd = [c for c in calls if "google_sheets_values_update" in c[0]]
    assert len(upd) >= 1

    header_written = upd[0][1]["values"][0]
    assert header_written == [
        "id",
        "date_time",
        "active",
        "status",
        "group",
        "subject",
        "memo",
        "result",
        "_created",
        "_updated",
    ]


def test_load_sheet_kv5_parses_enabled_scope_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    header = ["key", "value", "enabled", "scope", "priority"]
    rows = [
        ["a", "1", "TRUE", "global", "10"],
        ["b", "2", "false", "user", "0"],
        ["c", "3", "", "session", "5"],
    ]

    async def fake_call(name: str, arguments: dict):
        if "google_sheets_values_get" in name:
            return _mcp_text_payload({"ok": True, "values": [header] + rows})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    out = asyncio.run(main._load_sheet_kv5(spreadsheet_id="ssid", sheet_name="Any"))
    assert isinstance(out, list)
    assert out[0]["key"] == "a"
    assert out[0]["value"] == "1"
    assert out[0]["enabled"] is True
    assert out[0]["scope"] == "global"
    assert out[0]["priority"] == 10

    assert out[1]["enabled"] is False
    assert out[1]["scope"] == "user"

    # Empty enabled parses as disabled in _load_sheet_kv5.
    assert out[2]["enabled"] is False
    assert out[2]["scope"] == "session"
    assert out[2]["priority"] == 5
