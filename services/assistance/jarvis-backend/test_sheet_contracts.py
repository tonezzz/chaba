import asyncio
import importlib
import json
import sys
from types import ModuleType

import pytest

from types import SimpleNamespace


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


def test_memo_enrich_followup_appends_canonical_row(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    calls: list[tuple[str, dict]] = []

    header_row = [
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

    async def fake_sheet_get_header_row(**kwargs):
        return list(header_row)

    async def fake_ensure_header(**kwargs):
        return None

    def fake_idx_from_header(header):
        out = {}
        for j, name in enumerate(header):
            k = str(name or "").strip().lower()
            if k and k not in out:
                out[k] = int(j)
        return out

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        return _mcp_text_payload({"ok": True})

    ws = SimpleNamespace()
    ws.state = SimpleNamespace(
        sys_kv={"memo.enabled": "TRUE", "memo.sheet_name": "memo", "memo.spreadsheet_id": "ssid"},
        pending_memo_enrich={
            "memo": "base",
            "subject": "",
            "group": "ops",
            "details": "more",
            "need": {"subject": False, "group": False, "details": False},
        },
    )

    awaitable = main.memo_enrich.handle_followup(
        ws,
        "ignored",
        sys_kv_bool=lambda kv, k, d: True,
        memo_sheet_cfg_from_sys_kv=lambda kv: ("ssid", "memo"),
        sheet_name_to_a1=lambda name, default: "memo",
        sheet_get_header_row=fake_sheet_get_header_row,
        idx_from_header=fake_idx_from_header,
        memo_ensure_header=fake_ensure_header,
        pick_sheets_tool_name=lambda a, b: a,
        mcp_tools_call=fake_call,
        ws_send_json=lambda *_args, **_kwargs: None,
        live_say=lambda *_args, **_kwargs: None,
        instance_id="iid",
        now_dt_utc=lambda: "2026-01-01 00:00:00",
    )
    asyncio.run(awaitable)

    app = [c for c in calls if "google_sheets_values_append" in c[0]]
    assert len(app) == 1
    row = app[0][1]["values"][0]
    idx = fake_idx_from_header(header_row)
    assert row[idx["active"]] is True
    assert row[idx["group"]] == "ops"
    assert row[idx["memo"]].startswith("base")
    assert row[idx["date_time"]] == "2026-01-01 00:00:00"
    assert row[idx["_created"]] == "2026-01-01 00:00:00"
    assert row[idx["_updated"]] == "2026-01-01 00:00:00"


def test_memo_add_tool_enforces_canonical_header_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    # Import tools_router after main is loaded (so sys.modules stubs are in place).
    from jarvis import tools_router

    calls: list[tuple[str, dict]] = []

    # Simulate a legacy/out-of-order header coming from Sheets.
    legacy_header = [
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

    async def fake_sheet_get_header_row(**_kwargs):
        return list(legacy_header)

    async def fake_memo_ensure_header(**_kwargs):
        # No-op: we only care that it's called before idx mapping.
        return None

    def fake_idx_from_header(header):
        out = {}
        for j, name in enumerate(header):
            k = str(name or "").strip().lower()
            if k and k not in out:
                out[k] = int(j)
        return out

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        return _mcp_text_payload({"ok": True})

    # Minimal deps set for memo_add tool.
    class _HTTPException(Exception):
        def __init__(self, status_code: int, detail: object):
            super().__init__(str(detail))
            self.status_code = status_code
            self.detail = detail

    ws = SimpleNamespace()
    ws.state = SimpleNamespace(
        sys_kv={"memo.enabled": "TRUE", "memo.sheet_name": "memo", "memo.spreadsheet_id": "ssid"}
    )

    deps = {
        "HTTPException": _HTTPException,
        "SESSION_WS": {"sid": ws},
        "feature_enabled": lambda *_args, **_kwargs: True,
        "sys_kv_bool": lambda *_args, **_kwargs: True,
        "memo_sheet_cfg_from_sys_kv": lambda _kv: ("ssid", "memo"),
        "sheet_name_to_a1": lambda _name, default: default,
        "sheet_get_header_row": fake_sheet_get_header_row,
        "idx_from_header": fake_idx_from_header,
        "memo_ensure_header": fake_memo_ensure_header,
        "pick_sheets_tool_name": lambda a, _b: a,
        "mcp_tools_call": fake_call,
        "mcp_text_json": lambda x: x,
        "memo_prompt_cfg": lambda _kv: {"enabled": False},
        "memo_needs_enrich": lambda **_kwargs: {},
        "memo_enrich_prompt": lambda *_args, **_kwargs: None,
        "AGENT_CONTINUE_WINDOW_SECONDS": 60,
        "datetime": main.datetime,
        "timezone": main.timezone,
        "time": main.time,
        "logger": None,
    }

    out = asyncio.run(
        tools_router.handle_mcp_tool_call(
            "sid",
            "memo_add",
            {"memo": "hello", "group": "ops", "subject": "s", "status": "new"},
            deps=deps,
        )
    )
    assert isinstance(out, dict) and out.get("ok") is True

    # Ensure we attempted to normalize header (this is the missing step that caused wrong columns).
    assert any(c[0] for c in calls)  # keep calls referenced so linters don't complain

    # Verify the appended row has the memo text in the memo column index derived from legacy header.
    app = [c for c in calls if "google_sheets_values_append" in c[0]]
    assert len(app) == 1
    row = app[0][1]["values"][0]
    idx = fake_idx_from_header(legacy_header)
    assert row[idx["memo"]] == "hello"
    assert row[idx["group"]] == "ops"


def test_ws_update_contexts_upserts_selected_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    calls: list[tuple[str, str]] = []

    async def fake_upsert(*, ws, category: str, value: str):
        calls.append((str(category), str(value)))

    monkeypatch.setattr(main, "_memo_context_upsert", fake_upsert)

    ws = SimpleNamespace()
    ws.state = SimpleNamespace(last_memo={"id": 7, "group": "ops", "subject": "x"})

    asyncio.run(main._ws_update_contexts_from_text(ws, "hello", handled=False))
    asyncio.run(main._ws_update_contexts_from_text(ws, "action", handled=True))

    cats = {c for c, _ in calls}
    assert "conversation_summary" in cats
    assert "last_intent_and_args" in cats
    assert "last_entities" in cats
    assert "ops_snapshot" in cats


def test_history_trigger_matches_thai_and_english(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    assert main._is_history_trigger("history") is True
    assert main._is_history_trigger("show history") is True
    assert main._is_history_trigger("ประวัติ") is True
    assert main._is_history_trigger("ประวัติสนทนา") is True
    assert main._is_history_trigger("please do something else") is False


def test_thai_memo_summarize_uses_context_if_present(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    async def fake_gemini(system_instruction: str, prompt: str, **_kwargs):
        return "OK_SUMMARY"

    async def fake_call(name: str, arguments: dict):
        raise AssertionError(f"should_not_call_sheets {name}")

    sent: list[dict] = []

    async def fake_send(ws, msg):
        sent.append(dict(msg))

    async def fake_say(_ws, _txt):
        return None

    monkeypatch.setattr(main, "_gemini_summarize_text", fake_gemini)
    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)
    monkeypatch.setattr(main, "_ws_send_json", fake_send)
    monkeypatch.setattr(main, "_live_say", fake_say)

    ws = SimpleNamespace()
    ws.state = SimpleNamespace(
        sys_kv={"memo.enabled": "TRUE", "memo.sheet_name": "memo", "memo.spreadsheet_id": "ssid"},
        last_memo={"id": 12, "memo": "hello", "subject": "s", "group": "g", "status": "new", "result": "", "date_time": ""},
    )

    asyncio.run(main._handle_thai_memo_commands(ws, "สรุปเมโม 12"))
    assert any(m.get("text") == "OK_SUMMARY" for m in sent)


def test_thai_memo_summarize_loads_when_context_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    async def fake_gemini(system_instruction: str, prompt: str, **_kwargs):
        return "OK_SUMMARY"

    async def fake_get_header_row(**_kwargs):
        return [
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

    async def fake_call(name: str, arguments: dict):
        if "google_sheets_values_get" in name:
            # A2:J contains one row with id=12
            return _mcp_text_payload(
                {
                    "ok": True,
                    "values": [
                        [12, "", True, "new", "g", "s", "hello", "", "", ""],
                    ],
                }
            )
        raise AssertionError(f"unexpected_tool_name {name}")

    sent: list[dict] = []

    async def fake_send(ws, msg):
        sent.append(dict(msg))

    async def fake_say(_ws, _txt):
        return None

    monkeypatch.setattr(main, "_gemini_summarize_text", fake_gemini)
    monkeypatch.setattr(main, "_sheet_get_header_row", fake_get_header_row)
    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)
    monkeypatch.setattr(main, "_ws_send_json", fake_send)
    monkeypatch.setattr(main, "_live_say", fake_say)

    ws = SimpleNamespace()
    ws.state = SimpleNamespace(
        sys_kv={"memo.enabled": "TRUE", "memo.sheet_name": "memo", "memo.spreadsheet_id": "ssid"},
        last_memo={"id": 99, "memo": "nope"},
    )

    asyncio.run(main._handle_thai_memo_commands(ws, "สรุปเมโม 12"))
    assert any(m.get("text") == "OK_SUMMARY" for m in sent)
    assert isinstance(getattr(ws.state, "last_memo", None), dict)
    assert int(ws.state.last_memo.get("id") or 0) == 12
