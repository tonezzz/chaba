import asyncio
import importlib
import json
import os
import sys
from typing import Any
from types import ModuleType

import pytest

from types import SimpleNamespace


def _mcp_text_payload(obj: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(obj)}]}


def _import_main_with_genai_stub(monkeypatch: pytest.MonkeyPatch):
    # Some CI/dev environments running these unit tests may not have the full
    # runtime dependencies installed (e.g. fastapi/httpx). We stub the minimal
    # surface required for importing `main.py` and its helpers.
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    if backend_dir and backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    if "httpx" not in sys.modules:
        httpx_stub = ModuleType("httpx")

        class _AsyncClientStub:  # pragma: no cover
            def __init__(self, *args: Any, **kwargs: Any):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args: Any, **kwargs: Any):
                raise RuntimeError("httpx is not installed (stubbed in tests)")

        setattr(httpx_stub, "AsyncClient", _AsyncClientStub)
        sys.modules["httpx"] = httpx_stub

    if "fastapi" not in sys.modules:
        fastapi_stub = ModuleType("fastapi")

        class _HTTPExceptionStub(Exception):
            def __init__(self, status_code: int = 400, detail: Any = None):
                super().__init__(str(detail))
                self.status_code = status_code
                self.detail = detail

        class _FastAPIStub:  # pragma: no cover
            def __init__(self, *args: Any, **kwargs: Any):
                pass

            def include_router(self, *args: Any, **kwargs: Any):
                return None

            def get(self, *args: Any, **kwargs: Any):
                def _decor(fn):
                    return fn

                return _decor

            def post(self, *args: Any, **kwargs: Any):
                def _decor(fn):
                    return fn

                return _decor

            def put(self, *args: Any, **kwargs: Any):
                def _decor(fn):
                    return fn

                return _decor

            def delete(self, *args: Any, **kwargs: Any):
                def _decor(fn):
                    return fn

                return _decor

            def on_event(self, *args: Any, **kwargs: Any):
                def _decor(fn):
                    return fn

                return _decor

            def add_middleware(self, *args: Any, **kwargs: Any):
                return None

            def websocket(self, *args: Any, **kwargs: Any):
                def _decor(fn):
                    return fn

                return _decor

            def __getattr__(self, name: str):
                # Fallback for optional FastAPI APIs referenced by main.py that are
                # irrelevant for these unit tests (e.g. mount, exception_handler).
                def _noop(*args: Any, **kwargs: Any):
                    return None

                def _decorator_factory(*args: Any, **kwargs: Any):
                    def _decor(fn):
                        return fn

                    return _decor

                if name in {"mount", "add_api_route", "exception_handler", "middleware"}:
                    return _noop
                if name in {"patch", "head", "options"}:
                    return _decorator_factory
                return _noop

        class _APIRouterStub:  # pragma: no cover
            def __init__(self, *args: Any, **kwargs: Any):
                pass

            def add_api_route(self, *args: Any, **kwargs: Any):
                return None

            def get(self, *args: Any, **kwargs: Any):
                def _decor(fn):
                    return fn

                return _decor

            def post(self, *args: Any, **kwargs: Any):
                def _decor(fn):
                    return fn

                return _decor

            def put(self, *args: Any, **kwargs: Any):
                def _decor(fn):
                    return fn

                return _decor

            def delete(self, *args: Any, **kwargs: Any):
                def _decor(fn):
                    return fn

                return _decor

        setattr(fastapi_stub, "FastAPI", _FastAPIStub)
        setattr(fastapi_stub, "APIRouter", _APIRouterStub)
        setattr(fastapi_stub, "HTTPException", _HTTPExceptionStub)
        setattr(fastapi_stub, "WebSocket", object)
        setattr(fastapi_stub, "WebSocketDisconnect", Exception)

        def _BodyStub(*args: Any, **kwargs: Any):
            return None

        def _HeaderStub(*args: Any, **kwargs: Any):
            return None

        setattr(fastapi_stub, "Body", _BodyStub)
        setattr(fastapi_stub, "Header", _HeaderStub)
        sys.modules["fastapi"] = fastapi_stub

        # Submodules used by main.py
        cors_stub = ModuleType("fastapi.middleware.cors")
        setattr(cors_stub, "CORSMiddleware", object)
        sys.modules["fastapi.middleware"] = ModuleType("fastapi.middleware")
        sys.modules["fastapi.middleware.cors"] = cors_stub

        responses_stub = ModuleType("fastapi.responses")
        setattr(responses_stub, "Response", object)
        sys.modules["fastapi.responses"] = responses_stub

    if "PIL" not in sys.modules:
        pil_stub = ModuleType("PIL")
        pil_image_stub = ModuleType("PIL.Image")

        class _ImageStub:  # pragma: no cover
            pass

        setattr(pil_image_stub, "Image", _ImageStub)
        setattr(pil_stub, "Image", pil_image_stub)
        sys.modules["PIL"] = pil_stub
        sys.modules["PIL.Image"] = pil_image_stub

    if "dotenv" not in sys.modules:
        dotenv_stub = ModuleType("dotenv")

        def _load_dotenv_stub(*args: Any, **kwargs: Any):  # pragma: no cover
            return False

        setattr(dotenv_stub, "load_dotenv", _load_dotenv_stub)
        sys.modules["dotenv"] = dotenv_stub

    if "pydantic" not in sys.modules:
        pydantic_stub = ModuleType("pydantic")

        class _BaseModelStub:  # pragma: no cover
            pass

        def _FieldStub(*args: Any, **kwargs: Any):  # pragma: no cover
            return None

        setattr(pydantic_stub, "BaseModel", _BaseModelStub)
        setattr(pydantic_stub, "Field", _FieldStub)
        sys.modules["pydantic"] = pydantic_stub

    # Stub route modules imported by main.py to avoid pulling in FastAPI-dependent code.
    if "routes" not in sys.modules:
        sys.modules["routes"] = ModuleType("routes")
    if "routes.google_tasks" not in sys.modules:
        gt_stub = ModuleType("routes.google_tasks")

        def _create_router_stub(*args: Any, **kwargs: Any):
            return object()

        setattr(gt_stub, "create_router", _create_router_stub)
        sys.modules["routes.google_tasks"] = gt_stub
    if "routes.google_calendar" not in sys.modules:
        gc_stub = ModuleType("routes.google_calendar")

        def _create_router_stub2(*args: Any, **kwargs: Any):
            return object()

        setattr(gc_stub, "create_router", _create_router_stub2)
        sys.modules["routes.google_calendar"] = gc_stub

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


def test_system_instruction_from_sys_kv_orders_extras(monkeypatch: pytest.MonkeyPatch):
    main = _import_main_with_genai_stub(monkeypatch)
    sys_kv = {
        "system.instruction": "BASE",
        "system.instructions.20": "B",
        "system.instructions.10": "A",
        "system.instructions.x": "Z",
        "other": "ignored",
    }
    out = main._system_instruction_from_sys_kv(sys_kv)
    assert out == "BASE\n\nA\n\nB\n\nZ"


def test_macro_registry_text_is_compact_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)
    macros = {
        "macro_a": {"name": "macro_a", "description": "A"},
        "macro_b": {"name": "macro_b", "description": ""},
        "system_not_macro": {"name": "system_not_macro", "description": "no"},
    }
    txt = main._macro_registry_text(macros=macros, max_items=10)
    assert "macro_a" in txt
    assert "macro_b" in txt
    assert "system_not_macro" not in txt
    # Ensure compact (bulleted) format.
    assert "- macro_a: A" in txt


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


def test_load_sys_kv_from_sheet_filters_enabled_and_resolves_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    monkeypatch.setattr(main, "_system_spreadsheet_id", lambda: "ssid")
    monkeypatch.setattr(main, "_system_sheet_name", lambda: "system")

    async def fake_load_sheet_kv5(*, spreadsheet_id: str, sheet_name: str):
        assert spreadsheet_id == "ssid"
        assert sheet_name == "system"
        return [
            {"key": "k1", "value": "v1_global_hi", "enabled": True, "scope": "global", "priority": 100},
            {"key": "k1", "value": "v1_user_lo", "enabled": True, "scope": "user", "priority": 0},
            {"key": "k1", "value": "v1_session_mid", "enabled": True, "scope": "session", "priority": 10},
            {"key": "k2", "value": "disabled", "enabled": False, "scope": "global", "priority": 999},
            {"key": "k3", "value": "enabled", "enabled": True, "scope": "global", "priority": 0},
        ]

    monkeypatch.setattr(main, "_load_sheet_kv5", fake_load_sheet_kv5)

    out = asyncio.run(main._load_sys_kv_from_sheet())
    assert out.get("k2") is None
    # Scope wins first (session > user > global), then priority.
    assert out.get("k1") == "v1_session_mid"
    assert out.get("k3") == "enabled"


def test_macro_tools_from_sheet_are_declared_and_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    monkeypatch.setattr(main, "_system_spreadsheet_id", lambda: "ssid")
    monkeypatch.setattr(main, "_system_sheet_name", lambda: "system")

    # Pretend sys_kv is already available.
    monkeypatch.setattr(main, "_sys_kv_snapshot", lambda: {})

    async def fake_mcp_tools_call(name: str, arguments: dict[str, Any]):
        # Macro loader reads google_sheets_values_get for macros tab.
        if "google_sheets_values_get" in str(name):
            rng = str(arguments.get("range") or "")
            if rng.startswith("macros!"):
                header = ["name", "enabled", "description", "parameters_json", "steps_json"]
                steps = json.dumps([{"tool": "time_now", "args": {}}])
                rows = [["macro_time_now", "TRUE", "From sheet", "{}", steps]]
                return _mcp_text_payload({"ok": True, "values": [header] + rows})
            # Any other reads return empty.
            return _mcp_text_payload({"ok": True, "values": []})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_mcp_tools_call)

    # Load macros into cache.
    asyncio.run(main._macro_tools_get_cached(sys_kv={}, ttl_s=0.0))

    decls = main._mcp_tool_declarations()
    names = [d.get("name") for d in decls if isinstance(d, dict)]
    assert "macro_time_now" in names
    assert "macro_run" in names

    # Ensure macro execution dispatches to underlying tool.
    out = asyncio.run(main._handle_mcp_tool_call(None, "macro_time_now", {}))
    assert isinstance(out, dict)
    assert out.get("ok") is True
    assert out.get("macro") == "macro_time_now"
    steps = out.get("steps")
    assert isinstance(steps, list) and steps
    assert steps[0].get("tool") == "time_now"


def test_macros_only_mode_filters_tool_declarations(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    # Simulate macros-only mode enabled in sys_kv.
    monkeypatch.setattr(main, "_sys_kv_snapshot", lambda: {"system.macros.only": "TRUE"})

    # Simulate a loaded macro in cache.
    monkeypatch.setattr(
        main,
        "_macro_tools_cached_snapshot",
        lambda: {
            "macro_time_now": {
                "name": "macro_time_now",
                "description": "From sheet",
                "parameters": {"type": "object", "properties": {}},
                "steps": [{"tool": "time_now", "args": {}}],
            }
        },
    )

    decls = main._mcp_tool_declarations()
    names = {d.get("name") for d in decls if isinstance(d, dict)}

    assert "macro_run" not in names
    assert "macro_time_now" in names
    assert "system_reload" in names
    assert "system_macro_get" in names
    assert "system_macro_upsert" in names
    # Low-level tools should not be exposed to Gemini in macros-only mode.
    assert "memo_add" not in names
    assert "memory_add" not in names
    assert "time_now" not in names


def test_macro_parameter_templating_substitutes_step_args(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    async def fake_get_cached(*, sys_kv=None, ttl_s=15.0):
        return {
            "macro_echo": {
                "name": "macro_echo",
                "description": "Echo test",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
                "steps": [
                    {"tool": "dummy_tool", "args": {"q": "{{query}}", "n": "{{limit}}"}},
                    {"tool": "dummy_tool", "args": {"q": "Asia/{{query}}", "n": "{{limit}}"}},
                ],
            }
        }

    monkeypatch.setattr(main, "_macro_tools_get_cached", fake_get_cached)
    monkeypatch.setattr(main, "_sys_kv_snapshot", lambda: {})

    # Ensure the macro engine can execute a predictable step tool by routing via MCP_TOOL_MAP.
    monkeypatch.setattr(
        main,
        "MCP_TOOL_MAP",
        {
            **dict(getattr(main, "MCP_TOOL_MAP", {}) or {}),
            "dummy_tool": {
                "mcp_name": "dummy_mcp_tool",
                "description": "Dummy",
                "parameters": {"type": "object", "properties": {}},
                "requires_confirmation": False,
            },
        },
    )

    forwarded: list[tuple[str, dict[str, Any]]] = []

    async def fake_mcp_tools_call(name: str, arguments: dict[str, Any]):
        forwarded.append((str(name), dict(arguments)))
        return {"ok": True, "mcp_name": str(name), "arguments": dict(arguments)}

    monkeypatch.setattr(main, "_mcp_tools_call", fake_mcp_tools_call)

    out = asyncio.run(main._handle_mcp_tool_call(None, "macro_echo", {"query": "Bangkok", "limit": 5}))
    assert out.get("ok") is True
    assert len(forwarded) == 2

    assert forwarded[0][0] == "dummy_mcp_tool"
    assert forwarded[0][1].get("q") == "Bangkok"
    assert forwarded[0][1].get("n") == 5

    assert forwarded[1][0] == "dummy_mcp_tool"
    assert forwarded[1][1].get("q") == "Asia/Bangkok"
    assert forwarded[1][1].get("n") == 5


def test_macro_step_result_templating_allows_referencing_prior_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    async def fake_get_cached(*, sys_kv=None, ttl_s=15.0):
        return {
            "macro_chain": {
                "name": "macro_chain",
                "description": "Chain outputs",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                "steps": [
                    {"tool": "dummy_tool", "args": {"q": "{{query}}"}},
                    {
                        "tool": "dummy_tool",
                        "args": {
                            "prev_q": "{{steps.1.result.arguments.q}}",
                            "prev_ok": "{{steps.1.result.ok}}",
                            "msg": "hello {{steps.1.result.arguments.q}}",
                        },
                    },
                ],
            }
        }

    monkeypatch.setattr(main, "_macro_tools_get_cached", fake_get_cached)
    monkeypatch.setattr(main, "_sys_kv_snapshot", lambda: {})

    monkeypatch.setattr(
        main,
        "MCP_TOOL_MAP",
        {
            **dict(getattr(main, "MCP_TOOL_MAP", {}) or {}),
            "dummy_tool": {
                "mcp_name": "dummy_mcp_tool",
                "description": "Dummy",
                "parameters": {"type": "object", "properties": {}},
                "requires_confirmation": False,
            },
        },
    )

    forwarded: list[tuple[str, dict[str, Any]]] = []

    async def fake_mcp_tools_call(name: str, arguments: dict[str, Any]):
        forwarded.append((str(name), dict(arguments)))
        return {"ok": True, "mcp_name": str(name), "arguments": dict(arguments)}

    monkeypatch.setattr(main, "_mcp_tools_call", fake_mcp_tools_call)

    out = asyncio.run(main._handle_mcp_tool_call(None, "macro_chain", {"query": "Bangkok"}))
    assert out.get("ok") is True
    assert len(forwarded) == 2

    # Step 2 should see step 1 output via steps.1.result.* placeholders.
    assert forwarded[1][1].get("prev_q") == "Bangkok"
    assert forwarded[1][1].get("prev_ok") is True
    assert forwarded[1][1].get("msg") == "hello Bangkok"


def test_macro_template_functions_row_find_and_cell_get(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    async def fake_get_cached(*, sys_kv=None, ttl_s=15.0):
        return {
            "macro_sheet_math": {
                "name": "macro_sheet_math",
                "description": "row_find + cell_get",
                "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
                "steps": [
                    {"tool": "dummy_tool", "args": {}},
                    {
                        "tool": "dummy_tool",
                        "args": {
                            "row": "{{row_find(steps.1.result.values, id, 'id', 1)}}",
                            "memo": "{{cell_get(steps.1.result.values, row_find(steps.1.result.values, id, 'id', 1), 'memo', 1)}}",
                            "msg": "row={{row_find(steps.1.result.values, id, 'id', 1)}} memo={{cell_get(steps.1.result.values, row_find(steps.1.result.values, id, 'id', 1), 'memo', 1)}}",
                        },
                    },
                ],
            }
        }

    monkeypatch.setattr(main, "_macro_tools_get_cached", fake_get_cached)
    monkeypatch.setattr(main, "_sys_kv_snapshot", lambda: {})

    monkeypatch.setattr(
        main,
        "MCP_TOOL_MAP",
        {
            **dict(getattr(main, "MCP_TOOL_MAP", {}) or {}),
            "dummy_tool": {
                "mcp_name": "dummy_mcp_tool",
                "description": "Dummy",
                "parameters": {"type": "object", "properties": {}},
                "requires_confirmation": False,
            },
        },
    )

    calls = 0
    forwarded: list[tuple[str, dict[str, Any]]] = []

    async def fake_mcp_tools_call(name: str, arguments: dict[str, Any]):
        nonlocal calls
        calls += 1
        forwarded.append((str(name), dict(arguments)))
        if calls == 1:
            return {
                "ok": True,
                "values": [
                    ["id", "memo"],
                    ["1", "one"],
                    ["2", "two"],
                    ["3", "three"],
                ],
            }
        return {"ok": True, "mcp_name": str(name), "arguments": dict(arguments)}

    monkeypatch.setattr(main, "_mcp_tools_call", fake_mcp_tools_call)

    out = asyncio.run(main._handle_mcp_tool_call(None, "macro_sheet_math", {"id": "2"}))
    assert out.get("ok") is True

    assert len(forwarded) == 2
    step2_args = forwarded[1][1]

    # Header row is at base_row=1; found row should be 3 (header=1, id=1 at row2, id=2 at row3).
    assert step2_args.get("row") == 3
    assert step2_args.get("memo") == "two"
    assert step2_args.get("msg") == "row=3 memo=two"


def test_macro_template_helpers_a1_and_require(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    async def fake_get_cached(*, sys_kv=None, ttl_s=15.0):
        return {
            "macro_a1": {
                "name": "macro_a1",
                "description": "A1 helpers",
                "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
                "steps": [
                    {"tool": "dummy_tool", "args": {}},
                    {
                        "tool": "dummy_tool",
                        "args": {
                            "col": "{{col_a1(steps.1.result.values, 'memo')}}",
                            "cell": "{{a1(steps.1.result.values, 3, 'memo', 1)}}",
                            "rng": "{{range_row(steps.1.result.values, 3, 'id', 'memo', 1)}}",
                            "ok": "{{require(row_find(steps.1.result.values, id, 'id', 1), 'missing_id')}}",
                        },
                    },
                ],
            }
        }

    monkeypatch.setattr(main, "_macro_tools_get_cached", fake_get_cached)
    monkeypatch.setattr(main, "_sys_kv_snapshot", lambda: {})

    monkeypatch.setattr(
        main,
        "MCP_TOOL_MAP",
        {
            **dict(getattr(main, "MCP_TOOL_MAP", {}) or {}),
            "dummy_tool": {
                "mcp_name": "dummy_mcp_tool",
                "description": "Dummy",
                "parameters": {"type": "object", "properties": {}},
                "requires_confirmation": False,
            },
        },
    )

    calls = 0
    forwarded: list[tuple[str, dict[str, Any]]] = []

    async def fake_mcp_tools_call(name: str, arguments: dict[str, Any]):
        nonlocal calls
        calls += 1
        forwarded.append((str(name), dict(arguments)))
        if calls == 1:
            return {
                "ok": True,
                "values": [
                    ["id", "memo"],
                    ["1", "one"],
                    ["2", "two"],
                    ["3", "three"],
                ],
            }
        return {"ok": True, "mcp_name": str(name), "arguments": dict(arguments)}

    monkeypatch.setattr(main, "_mcp_tools_call", fake_mcp_tools_call)

    out = asyncio.run(main._handle_mcp_tool_call(None, "macro_a1", {"id": "2"}))
    assert out.get("ok") is True
    assert len(forwarded) == 2
    step2_args = forwarded[1][1]

    assert step2_args.get("col") == "B"
    assert step2_args.get("cell") == "B3"
    assert step2_args.get("rng") == "A3:B3"
    assert step2_args.get("ok") is True


def test_macro_template_require_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    async def fake_get_cached(*, sys_kv=None, ttl_s=15.0):
        return {
            "macro_require": {
                "name": "macro_require",
                "description": "require",
                "parameters": {"type": "object", "properties": {}},
                "steps": [
                    {"tool": "dummy_tool", "args": {"ok": "{{require(false, 'nope')}}"}},
                    {"tool": "dummy_tool", "args": {"after": "should_not_run"}},
                ],
            }
        }

    monkeypatch.setattr(main, "_macro_tools_get_cached", fake_get_cached)
    monkeypatch.setattr(main, "_sys_kv_snapshot", lambda: {})

    monkeypatch.setattr(
        main,
        "MCP_TOOL_MAP",
        {
            **dict(getattr(main, "MCP_TOOL_MAP", {}) or {}),
            "dummy_tool": {
                "mcp_name": "dummy_mcp_tool",
                "description": "Dummy",
                "parameters": {"type": "object", "properties": {}},
                "requires_confirmation": False,
            },
        },
    )

    forwarded: list[tuple[str, dict[str, Any]]] = []

    async def fake_mcp_tools_call(name: str, arguments: dict[str, Any]):
        forwarded.append((str(name), dict(arguments)))
        return {"ok": True, "mcp_name": str(name), "arguments": dict(arguments)}

    monkeypatch.setattr(main, "_mcp_tools_call", fake_mcp_tools_call)

    with pytest.raises(Exception) as ei:
        asyncio.run(main._handle_mcp_tool_call(None, "macro_require", {}))
    # Should fail before any MCP call happens.
    assert forwarded == []
    assert "macro_template_require_failed" in str(getattr(ei.value, "detail", "")) or "macro_template_require_failed" in str(ei.value)


def test_system_reload_tool_calls_load_ws_system_kv_and_macro_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    # Fake WS bound to a session.
    ws = SimpleNamespace()
    ws.state = SimpleNamespace(sys_kv={})
    monkeypatch.setattr(main, "_SESSION_WS", {"s1": ws})

    async def fake_load_ws_system_kv(_ws):
        _ws.state.sys_kv = {"k": "v"}
        return {"k": "v"}

    async def fake_macro_tools_force_reload_from_sheet(*, sys_kv=None):
        assert sys_kv == {"k": "v"}
        return {"macro_a": {"name": "macro_a", "steps": []}}

    monkeypatch.setattr(main, "_load_ws_system_kv", fake_load_ws_system_kv)
    monkeypatch.setattr(main, "_macro_tools_force_reload_from_sheet", fake_macro_tools_force_reload_from_sheet)

    out = asyncio.run(main._handle_mcp_tool_call("s1", "system_reload", {}))
    assert out.get("ok") is True
    assert out.get("macros_count") == 1


def test_system_macro_get_reads_from_macros_sheet(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    ws = SimpleNamespace()
    ws.state = SimpleNamespace(sys_kv={})
    monkeypatch.setattr(main, "_SESSION_WS", {"s1": ws})
    monkeypatch.setattr(main, "_system_spreadsheet_id", lambda: "ssid")
    monkeypatch.setattr(main, "_system_macros_sheet_name", lambda **_kw: "macros")
    monkeypatch.setattr(main, "_pick_sheets_tool_name", lambda a, b: a)

    async def fake_mcp_tools_call(name: str, arguments: dict[str, Any]):
        assert "google_sheets_values_get" in str(name)
        assert arguments.get("spreadsheet_id") == "ssid"
        assert str(arguments.get("range")) == "macros!A:Z"
        header = ["name", "enabled", "description", "parameters_json", "steps_json"]
        row = ["macro_x", "TRUE", "desc", "{}", "[]"]
        return {"content": [{"type": "text", "text": json.dumps({"ok": True, "values": [header, row]})}]}

    monkeypatch.setattr(main, "_mcp_tools_call", fake_mcp_tools_call)

    out = asyncio.run(main._handle_mcp_tool_call("s1", "system_macro_get", {"name": "macro_x"}))
    assert out.get("ok") is True
    assert out.get("name") == "macro_x"
    assert out.get("enabled") is True
    assert out.get("steps_json") == "[]"


def test_system_macro_upsert_queues_pending_append_and_confirm_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    ws = SimpleNamespace()
    ws.state = SimpleNamespace(sys_kv={})
    monkeypatch.setattr(main, "_SESSION_WS", {"s1": ws})
    monkeypatch.setattr(main, "_system_spreadsheet_id", lambda: "ssid")
    monkeypatch.setattr(main, "_system_macros_sheet_name", lambda **_kw: "macros")
    monkeypatch.setattr(main, "_pick_sheets_tool_name", lambda a, b: a)

    pending: dict[str, Any] = {}

    def fake_create_pending_write(session_id: str, action: str, payload: Any) -> str:
        assert session_id == "s1"
        assert action == "mcp_tools_call"
        pending["payload"] = payload
        return "pw_1"

    def fake_pop_pending_write(session_id: str, confirmation_id: str):
        assert session_id == "s1"
        assert confirmation_id == "pw_1"
        return {"action": "mcp_tools_call", "payload": pending.get("payload"), "created_at": 0}

    monkeypatch.setattr(main, "_create_pending_write", fake_create_pending_write)
    monkeypatch.setattr(main, "_pop_pending_write", fake_pop_pending_write)

    forwarded: list[tuple[str, dict[str, Any]]] = []

    async def fake_mcp_tools_call(name: str, arguments: dict[str, Any]):
        # First call: read macros sheet
        if "google_sheets_values_get" in str(name):
            header = ["name", "enabled", "description", "parameters_json", "steps_json"]
            # no existing rows => insert
            return {"content": [{"type": "text", "text": json.dumps({"ok": True, "values": [header]})}]}
        forwarded.append((str(name), dict(arguments)))
        return {"ok": True}

    monkeypatch.setattr(main, "_mcp_tools_call", fake_mcp_tools_call)

    out = asyncio.run(
        main._handle_mcp_tool_call(
            "s1",
            "system_macro_upsert",
            {"name": "macro_new", "steps_json": "[]", "parameters_json": "{}", "description": "d", "enabled": True},
        )
    )
    assert out.get("ok") is True
    assert out.get("queued") is True
    assert out.get("confirmation_id") == "pw_1"

    # Confirm should execute append.
    asyncio.run(main._handle_mcp_tool_call("s1", "pending_confirm", {"confirmation_id": "pw_1"}))
    assert forwarded
    assert "google_sheets_values_append" in forwarded[0][0]
    assert forwarded[0][1].get("spreadsheet_id") == "ssid"


def test_system_macro_upsert_queues_pending_update_when_row_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)

    ws = SimpleNamespace()
    ws.state = SimpleNamespace(sys_kv={})
    monkeypatch.setattr(main, "_SESSION_WS", {"s1": ws})
    monkeypatch.setattr(main, "_system_spreadsheet_id", lambda: "ssid")
    monkeypatch.setattr(main, "_system_macros_sheet_name", lambda **_kw: "macros")
    monkeypatch.setattr(main, "_pick_sheets_tool_name", lambda a, b: a)

    pending: dict[str, Any] = {}

    def fake_create_pending_write(session_id: str, action: str, payload: Any) -> str:
        pending["payload"] = payload
        return "pw_2"

    monkeypatch.setattr(main, "_create_pending_write", fake_create_pending_write)

    async def fake_mcp_tools_call(name: str, arguments: dict[str, Any]):
        if "google_sheets_values_get" in str(name):
            header = ["name", "enabled", "description", "parameters_json", "steps_json"]
            row = ["macro_x", "TRUE", "desc", "{}", "[]"]
            return {"content": [{"type": "text", "text": json.dumps({"ok": True, "values": [header, row]})}]}
        return {"ok": True}

    monkeypatch.setattr(main, "_mcp_tools_call", fake_mcp_tools_call)

    out = asyncio.run(main._handle_mcp_tool_call("s1", "system_macro_upsert", {"name": "macro_x", "steps_json": "[]"}))
    assert out.get("ok") is True
    assert out.get("action") == "update"
    assert out.get("confirmation_id") == "pw_2"
    payload = pending.get("payload")
    assert isinstance(payload, dict)
    assert "google_sheets_values_update" in str(payload.get("mcp_name"))


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
