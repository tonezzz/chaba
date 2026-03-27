import asyncio
import importlib
import json
import re
import sys
from types import ModuleType, SimpleNamespace

import pytest


def _mcp_text_payload(obj: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(obj)}]}


_RFC3339_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def _assert_rfc3339_utc_z(s: str) -> None:
    assert isinstance(s, str)
    assert _RFC3339_Z_RE.match(s), f"not_rfc3339_utc_z: {s}"


def _import_main_with_genai_stub(monkeypatch: pytest.MonkeyPatch):
    # In some local environments, google-genai isn't installed; main.py imports it at module import time.
    # Stub it so we can unit-test internal logic without external deps.
    if "google" not in sys.modules:
        sys.modules["google"] = ModuleType("google")
    if "google.genai" not in sys.modules:
        sys.modules["google.genai"] = ModuleType("google.genai")
    if "google.genai.types" not in sys.modules:
        sys.modules["google.genai.types"] = ModuleType("google.genai.types")
    if "google.genai.errors" not in sys.modules:
        sys.modules["google.genai.errors"] = ModuleType("google.genai.errors")

    # Ensure `from google import genai` works.
    try:
        setattr(sys.modules["google"], "genai", sys.modules["google.genai"])
    except Exception:
        pass

    # Ensure `from google.genai import types` works.
    try:
        setattr(sys.modules["google.genai"], "types", sys.modules["google.genai.types"])
    except Exception:
        pass

    # Ensure `from google.genai import errors as genai_errors` works.
    try:
        setattr(sys.modules["google.genai"], "errors", sys.modules["google.genai.errors"])
    except Exception:
        pass

    # main.py pulls in mcp_client which depends on httpx; tests don't exercise that.
    if "httpx" not in sys.modules:
        sys.modules["httpx"] = ModuleType("httpx")

    # main.py imports fastapi at module import time; unit tests here don't need the web framework.
    if "fastapi" not in sys.modules:
        fastapi_mod = ModuleType("fastapi")

        class _HTTPException(Exception):
            def __init__(self, status_code: int = 500, detail: object = None):
                super().__init__(str(detail) if detail is not None else "")
                self.status_code = status_code
                self.detail = detail

        class _FastAPI:
            def __init__(self, *args, **kwargs):
                pass

            def get(self, *args, **kwargs):
                def _wrap(fn):
                    return fn

                return _wrap

            def post(self, *args, **kwargs):
                def _wrap(fn):
                    return fn

                return _wrap

            def websocket(self, *args, **kwargs):
                def _wrap(fn):
                    return fn

                return _wrap

            def include_router(self, *args, **kwargs):
                return None

            def add_middleware(self, *args, **kwargs):
                return None

            def on_event(self, *args, **kwargs):
                def _wrap(fn):
                    return fn

                return _wrap

        class _APIRouter:
            def __init__(self, *args, **kwargs):
                pass

            def get(self, *args, **kwargs):
                def _wrap(fn):
                    return fn

                return _wrap

            def post(self, *args, **kwargs):
                def _wrap(fn):
                    return fn

                return _wrap

            def include_router(self, *args, **kwargs):
                return None

        class _WebSocket:
            pass

        class _WebSocketDisconnect(Exception):
            pass

        def _Body(*args, **kwargs):
            return None

        def _Header(*args, **kwargs):
            return None

        fastapi_mod.FastAPI = _FastAPI
        fastapi_mod.APIRouter = _APIRouter
        fastapi_mod.HTTPException = _HTTPException
        fastapi_mod.WebSocket = _WebSocket
        fastapi_mod.WebSocketDisconnect = _WebSocketDisconnect
        fastapi_mod.Body = _Body
        fastapi_mod.Header = _Header

        sys.modules["fastapi"] = fastapi_mod

    if "fastapi.middleware" not in sys.modules:
        sys.modules["fastapi.middleware"] = ModuleType("fastapi.middleware")
    if "fastapi.middleware.cors" not in sys.modules:
        cors_mod = ModuleType("fastapi.middleware.cors")

        class _CORSMiddleware:
            def __init__(self, *args, **kwargs):
                pass

        cors_mod.CORSMiddleware = _CORSMiddleware
        sys.modules["fastapi.middleware.cors"] = cors_mod

    if "fastapi.responses" not in sys.modules:
        resp_mod = ModuleType("fastapi.responses")

        class _Response:
            def __init__(self, *args, **kwargs):
                pass

        resp_mod.Response = _Response
        sys.modules["fastapi.responses"] = resp_mod

    # google_schemas imports pydantic; we don't need schema validation in these unit tests.
    if "pydantic" not in sys.modules:
        pydantic_mod = ModuleType("pydantic")

        class _BaseModel:
            def __init__(self, *args, **kwargs):
                pass

        def _Field(*args, **kwargs):
            # Behave like a default value factory in annotations contexts.
            default = kwargs.get("default")
            if default is None and args:
                default = args[0]
            return default

        pydantic_mod.BaseModel = _BaseModel
        pydantic_mod.Field = _Field
        sys.modules["pydantic"] = pydantic_mod

    # main.py imports Pillow (PIL.Image) for image helpers; tests here don't need it.
    if "PIL" not in sys.modules:
        pil_mod = ModuleType("PIL")
        sys.modules["PIL"] = pil_mod
    if "PIL.Image" not in sys.modules:
        pil_image_mod = ModuleType("PIL.Image")

        class _Image:
            pass

        pil_image_mod.Image = _Image
        sys.modules["PIL.Image"] = pil_image_mod
        try:
            setattr(sys.modules["PIL"], "Image", pil_image_mod)
        except Exception:
            pass

    # main.py imports python-dotenv; tests here don't need env file loading.
    if "dotenv" not in sys.modules:
        dotenv_mod = ModuleType("dotenv")

        def _load_dotenv(*args, **kwargs):
            return False

        dotenv_mod.load_dotenv = _load_dotenv
        sys.modules["dotenv"] = dotenv_mod

    if "main" in sys.modules:
        return importlib.reload(sys.modules["main"])
    return importlib.import_module("main")


def test_sys_kv_upsert_header_mode_preserves_created_at_and_unrelated_cols(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)
    monkeypatch.setenv("CHABA_SYSTEM_SPREADSHEET_ID", "ssid")
    monkeypatch.setenv("CHABA_SYSTEM_SHEET_NAME", "System")

    header = ["key", "value", "enabled", "scope", "priority", "created_at", "updated_at", "notes"]
    existing = [
        "My.Key",
        "old",
        "false",
        "global",
        "5",
        "2020-01-01T00:00:00Z",
        "2020-01-02T00:00:00Z",
        "keepme",
    ]

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if "google_sheets_values_get" in name:
            return _mcp_text_payload({"ok": True, "values": [header, existing]})
        if "google_sheets_values_update" in name:
            return _mcp_text_payload({"ok": True, "data": {"updatedRange": arguments.get("range")}})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    out = asyncio.run(main._sys_kv_upsert_sheet(key="my.key", value="new"))
    assert out.get("ok") is True
    assert out.get("action") == "update"

    upd = [c for c in calls if "google_sheets_values_update" in c[0]]
    assert len(upd) == 1
    upd_args = upd[0][1]
    assert isinstance(upd_args.get("values"), list)
    row = upd_args["values"][0]

    assert row[0] == "my.key"
    assert row[1] == "new"
    assert row[2] == "true"
    assert row[3] == "global"
    assert row[4] == "5"

    assert row[5] == "2020-01-01T00:00:00Z"
    _assert_rfc3339_utc_z(str(row[6]))
    assert row[7] == "keepme"


def test_sys_kv_upsert_header_mode_append_sets_created_at_and_updated_at(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)
    monkeypatch.setenv("CHABA_SYSTEM_SPREADSHEET_ID", "ssid")
    monkeypatch.setenv("CHABA_SYSTEM_SHEET_NAME", "System")

    header = ["key", "value", "enabled", "scope", "priority", "created_at", "updated_at"]

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if "google_sheets_values_get" in name:
            return _mcp_text_payload({"ok": True, "values": [header]})
        if "google_sheets_values_append" in name:
            return _mcp_text_payload({"ok": True, "data": {"updates": {"updatedRange": "System!A2:G2"}}})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    out = asyncio.run(main._sys_kv_upsert_sheet(key="new.key", value="v"))
    assert out.get("ok") is True
    assert out.get("action") == "append"

    app = [c for c in calls if "google_sheets_values_append" in c[0]]
    assert len(app) == 1
    row = app[0][1]["values"][0]

    assert row[0] == "new.key"
    assert row[1] == "v"
    assert row[2] == "true"
    assert row[3] == "global"
    assert row[4] == "0"
    _assert_rfc3339_utc_z(str(row[5]))
    _assert_rfc3339_utc_z(str(row[6]))


def test_sys_kv_upsert_case_insensitive_updates_instead_of_append(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)
    monkeypatch.setenv("CHABA_SYSTEM_SPREADSHEET_ID", "ssid")
    monkeypatch.setenv("CHABA_SYSTEM_SHEET_NAME", "System")

    header = ["key", "value", "enabled", "scope", "priority", "created_at", "updated_at"]
    existing = ["GEMINI.TEXT.MODEL_TOOLCALL", "old", "true", "global", "0", "2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z"]

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if "google_sheets_values_get" in name:
            return _mcp_text_payload({"ok": True, "values": [header, existing]})
        if "google_sheets_values_update" in name:
            return _mcp_text_payload({"ok": True, "data": {"updatedRange": arguments.get("range")}})
        if "google_sheets_values_append" in name:
            raise AssertionError("should_not_append")
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    out = asyncio.run(main._sys_kv_upsert_sheet(key="gemini.text.model_toolcall", value="new"))
    assert out.get("ok") is True
    assert out.get("action") == "update"

    upd = [c for c in calls if "google_sheets_values_update" in c[0]]
    assert len(upd) == 1
    row = upd[0][1]["values"][0]
    assert row[0] == "gemini.text.model_toolcall"
    assert row[1] == "new"


def test_memory_sheet_upsert_header_mode_preserves_created_at_and_unrelated_cols(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)
    monkeypatch.setenv("CHABA_SYSTEM_SPREADSHEET_ID", "ssid")
    monkeypatch.setenv("CHABA_SYSTEM_SHEET_NAME", "System")

    ws = SimpleNamespace(state=SimpleNamespace(memory_sheet_name="Memory"))

    header = ["key", "value", "enabled", "scope", "priority", "created_at", "updated_at", "notes"]
    existing = [
        "mem.key",
        "old",
        "false",
        "global",
        "1",
        "2020-01-01T00:00:00Z",
        "2020-01-02T00:00:00Z",
        "keepme",
    ]

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if "google_sheets_values_get" in name:
            return _mcp_text_payload({"ok": True, "data": {"values": [header, existing]}})
        if "google_sheets_values_update" in name:
            return _mcp_text_payload({"ok": True, "data": {"updatedRange": arguments.get("range")}})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    out = asyncio.run(
        main._memory_sheet_upsert(
            ws,
            key="mem.key",
            value="new",
            scope="global",
            priority=1,
            enabled=True,
            source="test",
        )
    )
    assert out.get("ok") is True
    assert out.get("mode") == "update"

    upd = [c for c in calls if "google_sheets_values_update" in c[0]]
    assert len(upd) == 1
    row = upd[0][1]["values"][0]

    assert row[0] == "mem.key"
    assert row[1] == "new"
    assert row[2] == "true"
    assert row[3] == "global"
    assert row[4] == 1

    assert row[5] == "2020-01-01T00:00:00Z"
    _assert_rfc3339_utc_z(str(row[6]))
    assert row[7] == "keepme"


def test_memory_sheet_upsert_header_mode_append_sets_created_at_and_updated_at(monkeypatch: pytest.MonkeyPatch) -> None:
    main = _import_main_with_genai_stub(monkeypatch)
    monkeypatch.setenv("CHABA_SYSTEM_SPREADSHEET_ID", "ssid")
    monkeypatch.setenv("CHABA_SYSTEM_SHEET_NAME", "System")

    ws = SimpleNamespace(state=SimpleNamespace(memory_sheet_name="Memory"))

    header = ["key", "value", "enabled", "scope", "priority", "created_at", "updated_at"]

    calls: list[tuple[str, dict]] = []

    async def fake_call(name: str, arguments: dict):
        calls.append((name, dict(arguments)))
        if "google_sheets_values_get" in name:
            return _mcp_text_payload({"ok": True, "data": {"values": [header]}})
        if "google_sheets_values_append" in name:
            return _mcp_text_payload({"ok": True, "data": {"updates": {"updatedRange": "Memory!A2:G2"}}})
        raise AssertionError(f"unexpected_tool_name {name}")

    monkeypatch.setattr(main, "_mcp_tools_call", fake_call)

    out = asyncio.run(
        main._memory_sheet_upsert(
            ws,
            key="mem.new",
            value="v",
            scope="global",
            priority=0,
            enabled=True,
            source="test",
        )
    )
    assert out.get("ok") is True
    assert out.get("mode") == "append"

    app = [c for c in calls if "google_sheets_values_append" in c[0]]
    assert len(app) == 1
    row = app[0][1]["values"][0]

    assert row[0] == "mem.new"
    assert row[1] == "v"
    assert row[2] == "true"
    assert row[3] == "global"
    assert row[4] == 0
    _assert_rfc3339_utc_z(str(row[5]))
    _assert_rfc3339_utc_z(str(row[6]))
