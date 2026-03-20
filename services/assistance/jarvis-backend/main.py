import asyncio
import base64
import os
import logging
import json
import sqlite3
import time
import uuid
import re
import hashlib
from io import BytesIO
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import db_session
import mcp_client
import google_common
from typing import Any, Optional, Literal
from pathlib import Path
import xml.etree.ElementTree as ET

from jarvis.feature_flags import feature_enabled
from jarvis import memo_sheet
from jarvis import memo_enrich
from jarvis import daily_brief
from jarvis import sheets_utils
from jarvis import tools_router

from routes.google_tasks import create_router as _create_google_tasks_router
from routes.google_calendar import create_router as _create_google_calendar_router

from PIL import Image

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Body, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from dotenv import load_dotenv

from tasks_sequential_v0 import suggest_next_step_from_task, suggest_template_from_completed_tasks
from checklist_v0 import next_actionable_step, parse_checklist_steps
from checklist_mutation_v0 import (
    find_checklist_step_indices_by_text,
    mark_all_checklist_steps_done,
    mark_checklist_step_done,
    mark_checklist_step_done_by_text,
)

try:
    from google import genai
    from google.genai import types
    from google.genai import errors as genai_errors
except Exception:
    class _GenaiErrorsStub:
        class ClientError(Exception):
            pass

    class _GenaiStub:
        class Client:
            def __init__(self, *args: Any, **kwargs: Any):
                raise RuntimeError("google-genai is not installed")

    class _GenaiTypesStub:
        pass

    genai = _GenaiStub()
    types = _GenaiTypesStub()
    genai_errors = _GenaiErrorsStub()
from pydantic import BaseModel, Field


_SHEET_MEMORY_CACHE: dict[str, Any] = {
    "loaded_at": 0,
    "created_at": 0,
    "updated_at": 0,
    "sys_kv": None,
    "memory_items": None,
    "memory_sheet_name": None,
    "memory_context_text": "",
}

_SHEET_KNOWLEDGE_CACHE: dict[str, Any] = {
    "loaded_at": 0,
    "created_at": 0,
    "updated_at": 0,
    "knowledge_items": None,
    "knowledge_sheet_name": None,
    "knowledge_context_text": "",
}

_SHEET_MEMORY_REFRESHING: bool = False
_SHEET_MEMORY_LAST_REFRESH_AT: int = 0

_SHEET_KNOWLEDGE_REFRESHING: bool = False
_SHEET_KNOWLEDGE_LAST_REFRESH_AT: int = 0

_STARTUP_PREWARM_LOCK: asyncio.Lock = asyncio.Lock()
_STARTUP_PREWARM_STATUS: dict[str, Any] = {
    "ts": 0,
    "ok": False,
    "error": "",
    "memory_n": 0,
    "knowledge_n": 0,
    "running": False,
}


def _memory_cache_ttl_seconds() -> int:
    try:
        return max(5, int(os.getenv("JARVIS_MEMORY_CACHE_TTL_SECONDS") or "60"))
    except Exception:
        return 60


def _knowledge_cache_ttl_seconds() -> int:
    try:
        return max(5, int(os.getenv("JARVIS_KNOWLEDGE_CACHE_TTL_SECONDS") or "120"))
    except Exception:
        return 120


def _get_cached_sheet_memory() -> Optional[dict[str, Any]]:
    now = int(time.time())
    loaded_at = int(_SHEET_MEMORY_CACHE.get("loaded_at") or 0)
    if loaded_at <= 0:
        return None
    if now - loaded_at > _memory_cache_ttl_seconds():
        return None
    return dict(_SHEET_MEMORY_CACHE)


def _set_cached_sheet_memory(payload: dict[str, Any]) -> None:
    now = int(time.time())
    try:
        if int(_SHEET_MEMORY_CACHE.get("created_at") or 0) <= 0:
            _SHEET_MEMORY_CACHE["created_at"] = now
    except Exception:
        _SHEET_MEMORY_CACHE["created_at"] = now
    _SHEET_MEMORY_CACHE["updated_at"] = now
    _SHEET_MEMORY_CACHE["loaded_at"] = now
    _SHEET_MEMORY_CACHE["sys_kv"] = payload.get("sys_kv")
    _SHEET_MEMORY_CACHE["memory_items"] = payload.get("memory_items")
    _SHEET_MEMORY_CACHE["memory_sheet_name"] = payload.get("memory_sheet_name")
    _SHEET_MEMORY_CACHE["memory_context_text"] = str(payload.get("memory_context_text") or "")


def _clear_sheet_caches() -> None:
    try:
        _SHEET_MEMORY_CACHE["loaded_at"] = 0
        _SHEET_MEMORY_CACHE["created_at"] = 0
        _SHEET_MEMORY_CACHE["updated_at"] = 0
        _SHEET_MEMORY_CACHE["sys_kv"] = None
        _SHEET_MEMORY_CACHE["memory_items"] = None
        _SHEET_MEMORY_CACHE["memory_sheet_name"] = None
        _SHEET_MEMORY_CACHE["memory_context_text"] = ""
    except Exception:
        pass
    try:
        _SHEET_KNOWLEDGE_CACHE["loaded_at"] = 0
        _SHEET_KNOWLEDGE_CACHE["created_at"] = 0
        _SHEET_KNOWLEDGE_CACHE["updated_at"] = 0
        _SHEET_KNOWLEDGE_CACHE["knowledge_items"] = None
        _SHEET_KNOWLEDGE_CACHE["knowledge_sheet_name"] = None
        _SHEET_KNOWLEDGE_CACHE["knowledge_context_text"] = ""
    except Exception:
        pass
    try:
        _SHEET_GEMS_CACHE["loaded_at"] = 0
        _SHEET_GEMS_CACHE["gems"] = None
        _SHEET_GEMS_CACHE["gem_ids"] = None
        _SHEET_GEMS_CACHE["source"] = None
    except Exception:
        pass


def _apply_cached_sheet_memory_to_ws(ws: WebSocket, cached: dict[str, Any]) -> None:
    try:
        ws.state.sys_kv = cached.get("sys_kv")
        ws.state.memory_items = cached.get("memory_items")
        ws.state.memory_sheet_name = cached.get("memory_sheet_name")
        ws.state.memory_context_text = cached.get("memory_context_text")
    except Exception:
        pass


def _set_cached_sys_kv_only(sys_kv: dict[str, str]) -> None:
    try:
        now = int(time.time())
        if _SHEET_MEMORY_CACHE.get("created_at", 0) <= 0:
            _SHEET_MEMORY_CACHE["created_at"] = now
        _SHEET_MEMORY_CACHE["updated_at"] = now
        _SHEET_MEMORY_CACHE["loaded_at"] = now
        _SHEET_MEMORY_CACHE["sys_kv"] = dict(sys_kv)
    except Exception:
        pass


def _get_cached_sheet_knowledge() -> Optional[dict[str, Any]]:
    now = int(time.time())
    loaded_at = int(_SHEET_KNOWLEDGE_CACHE.get("loaded_at") or 0)
    if loaded_at <= 0:
        return None
    if now - loaded_at > _knowledge_cache_ttl_seconds():
        return None
    return dict(_SHEET_KNOWLEDGE_CACHE)


def _set_cached_sheet_knowledge(payload: dict[str, Any]) -> None:
    now = int(time.time())
    try:
        if int(_SHEET_KNOWLEDGE_CACHE.get("created_at") or 0) <= 0:
            _SHEET_KNOWLEDGE_CACHE["created_at"] = now
    except Exception:
        _SHEET_KNOWLEDGE_CACHE["created_at"] = now
    _SHEET_KNOWLEDGE_CACHE["updated_at"] = now
    _SHEET_KNOWLEDGE_CACHE["loaded_at"] = now
    _SHEET_KNOWLEDGE_CACHE["knowledge_items"] = payload.get("knowledge_items")
    _SHEET_KNOWLEDGE_CACHE["knowledge_sheet_name"] = payload.get("knowledge_sheet_name")
    _SHEET_KNOWLEDGE_CACHE["knowledge_context_text"] = str(payload.get("knowledge_context_text") or "")


def _apply_cached_sheet_knowledge_to_ws(ws: WebSocket, cached: dict[str, Any]) -> None:
    try:
        ws.state.knowledge_items = cached.get("knowledge_items")
        ws.state.knowledge_sheet_name = cached.get("knowledge_sheet_name")
        ws.state.knowledge_context_text = cached.get("knowledge_context_text")
    except Exception:
        pass


_SHEET_GEMS_CACHE: dict[str, Any] = {
    "loaded_at": 0,
    "gems": None,
    "gem_ids": None,
    "source": None,
}

_SHEET_GEMS_REFRESHING: bool = False
_SHEET_GEMS_LAST_REFRESH_AT: int = 0


_GEMS_DRAFTS: dict[str, dict[str, Any]] = {}


def _gems_draft_ttl_seconds() -> int:
    try:
        v = int(str(os.getenv("JARVIS_GEMS_DRAFT_TTL_SECONDS") or "3600").strip())
        return v if v > 60 else 3600
    except Exception:
        return 3600


def _gems_drafts_prune() -> None:
    try:
        ttl = _gems_draft_ttl_seconds()
        now = int(time.time())
        dead: list[str] = []
        for did, d in list(_GEMS_DRAFTS.items()):
            try:
                created = int(d.get("created_at") or 0)
            except Exception:
                created = 0
            if created <= 0 or (now - created) > ttl:
                dead.append(did)
        for did in dead:
            try:
                _GEMS_DRAFTS.pop(did, None)
            except Exception:
                pass
    except Exception:
        pass


def _gems_cache_ttl_seconds() -> int:
    try:
        v = int(str(os.getenv("JARVIS_GEMS_CACHE_TTL_SECONDS") or "120").strip())
        return v if v > 0 else 120
    except Exception:
        return 120


def _get_cached_sheet_gems() -> Optional[dict[str, Any]]:
    now = int(time.time())
    loaded_at = int(_SHEET_GEMS_CACHE.get("loaded_at") or 0)
    if loaded_at <= 0:
        return None
    if now - loaded_at > _gems_cache_ttl_seconds():
        return None
    gems = _SHEET_GEMS_CACHE.get("gems")
    if not isinstance(gems, dict) or not gems:
        return None
    return dict(_SHEET_GEMS_CACHE)


def _set_cached_sheet_gems(payload: dict[str, Any]) -> None:
    _SHEET_GEMS_CACHE["loaded_at"] = int(time.time())
    _SHEET_GEMS_CACHE["gems"] = payload.get("gems")
    _SHEET_GEMS_CACHE["gem_ids"] = payload.get("gem_ids")
    _SHEET_GEMS_CACHE["source"] = payload.get("source")


def _normalize_gem_id(v: Any) -> str:
    return str(v or "").strip().lower()


def _get_sheets_tool_name(alias: str) -> str:
    meta = MCP_TOOL_MAP.get(alias) if isinstance(MCP_TOOL_MAP, dict) else None
    name = str(meta.get("mcp_name") or "").strip() if isinstance(meta, dict) else ""
    return name


def _pick_sheets_tool_name(alias: str, fallback: str) -> str:
    name = _get_sheets_tool_name(alias)
    return name or fallback


def _sys_kv_bool(sys_kv: Any, key: str, default: bool) -> bool:
    if not isinstance(sys_kv, dict):
        return default
    raw = sys_kv.get(key)
    if raw is None:
        return default
    try:
        return _parse_bool_cell(raw)
    except Exception:
        return default


def _memory_capture_enabled(sys_kv: Any) -> bool:
    raw = str(os.getenv("JARVIS_MEMORY_CAPTURE_ENABLED") or "").strip()
    if raw:
        try:
            enabled = _parse_bool_cell(raw)
        except Exception:
            return False

    else:
        enabled = _sys_kv_bool(sys_kv, "memory.capture.enabled", default=False)

    if not enabled:
        return False

    # Back-compat: keep env var but capture no longer depends on memory.write.enabled.
    # (memory.write.enabled still gates user-initiated memory writes via the memory tool.)
    return True


def _redact_capture_text(text: str) -> str:
    s = str(text or "")
    if not s:
        return ""
    try:
        s = re.sub(r"(?i)(PORTAINER_TOKEN\s*[:=]\s*)([^\s]+)", r"\1[REDACTED]", s)
    except Exception:
        pass
    try:
        s = re.sub(r"\bptr_[A-Za-z0-9+/=]+\b", "ptr_[REDACTED]", s)
    except Exception:
        pass
    try:
        s = re.sub(r"(?i)(bearer\s+)([A-Za-z0-9\-\._~\+/]+=*)", r"\1[REDACTED]", s)
    except Exception:
        pass
    return s


def _truncate_capture_text(text: str, limit: int = 1800) -> str:
    s = str(text or "")
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "…"


async def _maybe_capture_to_memory(ws: WebSocket, *, key: str, value: str, source: str) -> None:
    sys_kv = getattr(ws.state, "sys_kv", None)
    if not _memory_capture_enabled(sys_kv):
        try:
            raw_env = str(os.getenv("JARVIS_MEMORY_CAPTURE_ENABLED") or "").strip()
            sys_flag = None
            if isinstance(sys_kv, dict):
                sys_flag = sys_kv.get("memory.capture.enabled")
            print(f"memory_capture_skipped_disabled key={key} source={source} env={raw_env!r} sys_kv.memory.capture.enabled={sys_flag!r}")
        except Exception:
            pass
        return
    k = str(key or "").strip()
    v = _truncate_capture_text(_redact_capture_text(str(value or "").strip()))
    if not (k and v):
        return
    try:
        await _memory_sheet_upsert(
            ws,
            key=k,
            value=v,
            scope="global",
            priority=10,
            enabled=True,
            source=str(source or "capture").strip() or "capture",
        )
    except Exception as e:
        try:
            print(f"memory_capture_failed key={k} source={source} error={type(e).__name__}: {e}")
        except Exception:
            pass
        return


async def _load_sheet_table(*, spreadsheet_id: str, sheet_name: str, max_rows: int = 250, max_cols: str = "Q") -> list[list[Any]]:
    tool = _pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
    res = await _mcp_tools_call(
        tool,
        {
            "spreadsheet_id": spreadsheet_id,
            "range": f"{sheet_name}!A1:{max_cols}{max_rows}",
        },
    )
    parsed = _mcp_text_json(res)

    # Best-effort: extract the row number from the append response so we can report a stable id.
    # Google usually returns e.g. `notes!B12:F12`. We map sheet row -> note id by subtracting 1 (header row).
    note_id: Optional[int] = None
    try:
        updated_range = ""
        if isinstance(parsed, dict):
            updated_range = str((((parsed.get("data") or {}).get("updates") or {}).get("updatedRange") or "")).strip()
        m = re.search(r"!(?:[A-Z]+)(\d+):", updated_range)
        if not m:
            m = re.search(r"!(?:[A-Z]+)(\d+)$", updated_range)
        if m:
            row_num = int(m.group(1))
            note_id = max(1, row_num - 1)
    except Exception:
        note_id = None
    if not isinstance(parsed, dict):
        raise RuntimeError("google_sheets_values_get_invalid_response")
    values = parsed.get("values")
    if not isinstance(values, list) or not values:
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if isinstance(data, dict):
            values = data.get("values")
    if not isinstance(values, list) or not values:
        raise RuntimeError(
            f"google_sheets_values_get_missing_values spreadsheet_id={spreadsheet_id} sheet={sheet_name}"
        )
    out: list[list[Any]] = []
    for row in values:
        if isinstance(row, list):
            out.append(row)
    return out


def _idx_from_header(header: list[Any]) -> dict[str, int]:
    return sheets_utils.idx_from_header(header)


def _normalize_thai_compact(s: str) -> str:
    try:
        return re.sub(r"[\u0E31-\u0E4E]", "", str(s or ""))
    except Exception:
        return str(s or "")


def _memo_match_anywhere(text: str) -> tuple[bool, str | None]:
    # Returns (matched, extracted_memo_text_or_none).
    raw = str(text or "").strip()
    if not raw:
        return (False, None)

    s0 = raw
    low = raw.lower()
    try:
        low = re.sub(
            r"^(hey|hi|ok|okay|please|pls|jarvis|assistant|ช่วย|ขอ|กรุณา|นะ|ครับ|ค่ะ|ขอให้)\b[\s,:-]*",
            "",
            low,
            flags=re.IGNORECASE,
        ).strip()
        s0 = re.sub(
            r"^(ช่วย|ขอ|กรุณา|นะ|ครับ|ค่ะ|ขอให้)[\s,:-]*",
            "",
            s0,
        ).strip()
    except Exception:
        pass

    # EN patterns (allow keyword anywhere).
    m_en = re.search(r"\b(?:add|save|create)?\s*memo\b\s*[:\-]?\s*(.*)$", low, flags=re.IGNORECASE)
    if m_en:
        tail = str(m_en.group(1) or "").strip()
        return (True, tail or None)

    # Thai patterns (normalize tone/marks: เมโม่ -> เมโม).
    s0n = _normalize_thai_compact(s0)
    m_th = re.search(r"(?:เพิ่ม|บันทึก|สร้าง)?\s*(เมโม|เมมโม)\s*[:\-]?\s*(.*)$", s0n)
    if m_th:
        # Use original string slicing only for the tail segment (keep original marks).
        tail_norm = str(m_th.group(2) or "").strip()
        if tail_norm:
            return (True, tail_norm)
        return (True, None)

    return (False, None)


def _is_memo_trigger(text: str) -> bool:
    ok, _tail = _memo_match_anywhere(str(text or ""))
    return ok


def _extract_memo_text(text: str) -> Optional[str]:
    ok, tail = _memo_match_anywhere(str(text or ""))
    if not ok:
        return None
    return str(tail or "").strip() or None


def _parse_memo_merge(text: str) -> tuple[Optional[int], Optional[int]]:
    s = " ".join(str(text or "").strip().split())
    if not s:
        return (None, None)
    low = s.lower()
    if not low.startswith("memo merge"):
        return (None, None)
    tail = s[len("memo merge") :].strip(" :")
    parts = [p for p in tail.split(" ") if p]
    if len(parts) < 2:
        return (None, None)
    try:
        src = int(parts[0])
        dst = int(parts[1])
        if src <= 1 or dst <= 1:
            return (None, None)
        return (src, dst)
    except Exception:
        return (None, None)


def _memo_prompt_cfg(sys_kv: Any) -> dict[str, Any]:
    return memo_enrich.prompt_cfg(sys_kv, sys_kv_bool=_sys_kv_bool, safe_int=_safe_int)


def _memo_needs_enrich(*, memo: str, subject: str, group: str, cfg: dict[str, Any]) -> dict[str, bool]:
    return memo_enrich.needs_enrich(memo=memo, subject=subject, group=group, cfg=cfg)


async def _memo_enrich_prompt(ws: WebSocket) -> None:
    await memo_enrich.enrich_prompt(
        ws,
        ws_send_json=_ws_send_json,
        live_say=_live_say,
        instance_id=INSTANCE_ID,
    )


async def _handle_memo_enrich_followup(ws: WebSocket, text: str) -> bool:
    def _now_dt_utc() -> str:
        return datetime.now(tz=timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

    return await memo_enrich.handle_followup(
        ws,
        text,
        sys_kv_bool=_sys_kv_bool,
        memo_sheet_cfg_from_sys_kv=_memo_sheet_cfg_from_sys_kv,
        sheet_name_to_a1=_sheet_name_to_a1,
        pick_sheets_tool_name=_pick_sheets_tool_name,
        mcp_tools_call=_mcp_tools_call,
        ws_send_json=_ws_send_json,
        live_say=_live_say,
        instance_id=INSTANCE_ID,
        now_dt_utc=_now_dt_utc,
    )


async def _handle_memo_trigger(ws: WebSocket, text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False

    src_row, dst_row = _parse_memo_merge(s)
    is_merge = src_row is not None and dst_row is not None
    if not is_merge and not _is_memo_trigger(s):
        return False

    sys_kv = getattr(ws.state, "sys_kv", None)
    if not _sys_kv_bool(sys_kv, "memo.enabled", default=False):
        try:
            lang = str(getattr(ws.state, "user_lang", "") or "").strip().lower()
        except Exception:
            lang = ""
        msg = "memo_disabled"
        if lang.startswith("th"):
            msg = "ปิดการใช้งานเมโม (memo_disabled)"
        try:
            await _ws_send_json(ws, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
        except Exception:
            pass
        return True

    spreadsheet_id = ""
    if isinstance(sys_kv, dict):
        spreadsheet_id = str(
            sys_kv.get("memo.spreadsheet_name")
            or sys_kv.get("memo.spreadsheet_id")
            or sys_kv.get("memo_ss")
            or ""
        ).strip()
    if not spreadsheet_id:
        spreadsheet_id = _system_spreadsheet_id()
    if not spreadsheet_id:
        await _ws_send_json(ws, {"type": "text", "text": "missing_memo_ss", "instance_id": INSTANCE_ID})
        return True

    sheet_name = ""
    if isinstance(sys_kv, dict):
        sheet_name = str(sys_kv.get("memo.sheet_name") or sys_kv.get("memo_sheet_name") or sys_kv.get("memo_sh") or "").strip()
    if not sheet_name:
        await _ws_send_json(ws, {"type": "text", "text": "missing_memo_sheet_name", "instance_id": INSTANCE_ID})
        return True

    sheet_name_a1 = _sheet_name_to_a1(sheet_name, default="memo")
    tool_get = _pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
    tool_update = _pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
    tool_append = _pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")

    now_dt = datetime.now(tz=timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

    # Ensure header exists (best-effort) using canonical memo header.
    try:
        await _memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_name_a1)
    except Exception:
        pass

    if is_merge:
        lo = min(int(src_row or 0), int(dst_row or 0))
        hi = max(int(src_row or 0), int(dst_row or 0))
        res = await _mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_name_a1}!A{lo}:J{hi}"})
        parsed = _mcp_text_json(res)
        vals = parsed.get("values") if isinstance(parsed, dict) else None
        if not isinstance(vals, list):
            await _ws_send_json(ws, {"type": "text", "text": "memo_merge_read_failed", "instance_id": INSTANCE_ID})
            return True

        header = []
        try:
            header = await _sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_name_a1, max_cols="J")
        except Exception:
            header = []
        idx = _idx_from_header(header)

        def _row_at(rn: int) -> list[Any]:
            i = rn - lo
            if 0 <= i < len(vals) and isinstance(vals[i], list):
                return list(vals[i])
            return []

        def _get(row: list[Any], col: str, default: Any = "") -> Any:
            j = idx.get(col)
            if j is None or j < 0 or j >= len(row):
                return default
            return row[j]

        def _set(row: list[Any], col: str, value: Any) -> None:
            j = idx.get(col)
            if j is None:
                return
            while len(row) <= j:
                row.append("")
            row[j] = value

        src_vals = _row_at(int(src_row or 0))
        dst_vals = _row_at(int(dst_row or 0))

        src_memo = str(_get(src_vals, "memo") or "").strip()
        dst_memo = str(_get(dst_vals, "memo") or "").strip()
        if not src_memo or not dst_memo:
            await _ws_send_json(ws, {"type": "text", "text": "memo_merge_missing_memo", "instance_id": INSTANCE_ID})
            return True

        merged = dst_memo.rstrip() + "\n\n---\n" + src_memo

        _set(dst_vals, "memo", merged)
        _set(dst_vals, "status", str(_get(dst_vals, "status") or "").strip() or "new")

        _set(src_vals, "status", "merged")
        _set(src_vals, "_updated", now_dt)
        _set(dst_vals, "_updated", now_dt)

        await _mcp_tools_call(
            tool_update,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_name_a1}!A{int(dst_row or 0)}:J{int(dst_row or 0)}",
                "values": [dst_vals[:10]],
                "value_input_option": "USER_ENTERED",
            },
        )
        await _mcp_tools_call(
            tool_update,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_name_a1}!A{int(src_row or 0)}:J{int(src_row or 0)}",
                "values": [src_vals[:10]],
                "value_input_option": "USER_ENTERED",
            },
        )
        await _ws_send_json(ws, {"type": "text", "text": f"Memo merged: {src_row} -> {dst_row}", "instance_id": INSTANCE_ID})
        return True

    memo_text = _extract_memo_text(s)
    if not memo_text:
        await _ws_send_json(ws, {"type": "text", "text": "memo_missing_text", "instance_id": INSTANCE_ID})
        return True

    row: list[Any] = [
        "",
        True,
        "",
        memo_text,
        "new",
        "",
        "",
        now_dt,
        now_dt,
        now_dt,
    ]
    try:
        await _mcp_tools_call(
            tool_append,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_name_a1}!A:Z",
                "values": [row],
                "value_input_option": "USER_ENTERED",
                "insert_data_option": "INSERT_ROWS",
            },
        )
    except Exception:
        await _ws_send_json(ws, {"type": "text", "text": "memo_append_failed", "instance_id": INSTANCE_ID})
        return True
    await _ws_send_json(ws, {"type": "text", "text": "Memo saved.", "instance_id": INSTANCE_ID})

    # Soft-mode enrichment prompt (append happened already).
    cfg = _memo_prompt_cfg(sys_kv)
    if cfg.get("enabled"):
        need = _memo_needs_enrich(memo=memo_text, subject="", group="", cfg=cfg)
        if need.get("subject") or need.get("group") or need.get("details"):
            try:
                ws.state.pending_memo_enrich = {"memo": memo_text, "subject": "", "group": "", "details": "", "need": need}
                ws.state.active_agent_id = "memo_enrich"
                ws.state.active_agent_until_ts = int(time.time()) + AGENT_CONTINUE_WINDOW_SECONDS
            except Exception:
                pass
            await _memo_enrich_prompt(ws)
    return True


def _get_cell(row: list[Any], idx: dict[str, int], col: str, default: Any = "") -> Any:
    j = idx.get(col)
    if j is None or j < 0 or j >= len(row):
        return default
    return row[j]


def _compose_gem_instruction(purpose: str, persona: str) -> str:
    p = str(purpose or "").strip()
    s = str(persona or "").strip()
    if p and s:
        return f"PURPOSE: {p}\n\n{s}".strip()
    return (s or p).strip()


async def _load_sheet_gems(*, sys_kv: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    spreadsheet_id = _system_spreadsheet_id()
    sheet_name = "gems"
    if isinstance(sys_kv, dict) and sys_kv:
        spreadsheet_id = str(sys_kv.get("gems_ss") or spreadsheet_id).strip()
        sheet_name = str(sys_kv.get("gems_sh") or sheet_name).strip() or "gems"
    if not spreadsheet_id:
        return {"gems": {}, "gem_ids": []}

    rows = await _load_sheet_table(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name, max_rows=300, max_cols="Q")
    if not rows:
        return {"gems": {}, "gem_ids": []}
    header = rows[0] if isinstance(rows[0], list) else []
    idx = _idx_from_header(header)

    gems: dict[str, dict[str, Any]] = {}
    for raw in rows[1:]:
        if not isinstance(raw, list) or not raw:
            continue
        gem_id = _normalize_gem_id(_get_cell(raw, idx, "id", default=(raw[0] if raw else "")))
        if not gem_id:
            continue
        enabled_raw = _get_cell(raw, idx, "enabled", default="TRUE")
        enabled = _parse_bool_cell(enabled_raw)
        if not enabled:
            continue

        name = str(_get_cell(raw, idx, "name", default="")).strip()
        purpose = str(_get_cell(raw, idx, "purpose", default="")).strip()
        persona = str(_get_cell(raw, idx, "persona", default="")).strip()
        model = str(_get_cell(raw, idx, "model", default="")).strip()
        language = str(_get_cell(raw, idx, "language", default="")).strip()
        output_format = str(_get_cell(raw, idx, "output_format", default="")).strip()
        tools_policy = str(_get_cell(raw, idx, "tools_policy", default="")).strip()

        gems[gem_id] = {
            "id": gem_id,
            "name": name,
            "purpose": purpose,
            "persona": persona,
            "instruction": _compose_gem_instruction(purpose, persona),
            "model": model,
            "language": language,
            "output_format": output_format,
            "tools_policy": tools_policy,
        }

    gem_ids = sorted(list(gems.keys()))
    return {
        "gems": gems,
        "gem_ids": gem_ids,
        "source": {"spreadsheet_id": spreadsheet_id, "sheet": sheet_name},
    }


async def _sheet_gems_find_row(*, spreadsheet_id: str, sheet_name: str, gem_id: str) -> tuple[list[Any], int, dict[str, int]]:
    rows = await _load_sheet_table(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name, max_rows=600, max_cols="Q")
    if not rows or not isinstance(rows[0], list):
        raise RuntimeError("gems_sheet_missing_header")
    header = rows[0]
    idx = _idx_from_header(header)
    gid_key = "id" if "id" in idx else ("gem_id" if "gem_id" in idx else "")
    if not gid_key:
        raise RuntimeError("gems_sheet_missing_id_column")
    for i, raw in enumerate(rows[1:], start=2):
        if not isinstance(raw, list):
            continue
        rid = _normalize_gem_id(_get_cell(raw, idx, gid_key, default=""))
        if rid and rid == gem_id:
            return header, i, idx
    return header, 0, idx


def _sheet_gems_build_row(*, header: list[Any], idx: dict[str, int], gem: dict[str, Any]) -> list[Any]:
    # Build a row aligned to header length.
    n = len(header)
    out: list[Any] = [""] * n

    def set_col(key: str, value: Any) -> None:
        if key not in idx:
            return
        j = int(idx[key])
        if 0 <= j < n:
            out[j] = "" if value is None else value

    gid = _normalize_gem_id(gem.get("id") or gem.get("gem_id"))
    set_col("id", gid)
    set_col("gem_id", gid)
    set_col("name", str(gem.get("name") or "").strip())
    set_col("purpose", str(gem.get("purpose") or "").strip())
    set_col("system_instruction", str(gem.get("system_instruction") or "").strip())
    set_col("user_instruction", str(gem.get("user_instruction") or "").strip())
    set_col("output_format", str(gem.get("output_format") or "").strip())
    set_col("tools_policy", str(gem.get("tools_policy") or "").strip())
    return out


async def _sheet_gems_append(*, spreadsheet_id: str, sheet_name: str, row: list[Any]) -> dict[str, Any]:
    tool = _pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
    res = await _mcp_tools_call(
        tool,
        {
            "spreadsheet_id": spreadsheet_id,
            "range": f"{sheet_name}!A:Q",
            "values": [row],
            "value_input_option": "RAW",
        },
    )
    parsed = _mcp_text_json(res)
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    s = str(text or "").strip()
    if not s:
        return None
    # Best-effort: grab first {...} block.
    try:
        i = s.find("{")
        j = s.rfind("}")
        if i >= 0 and j > i:
            s = s[i : j + 1]
        parsed = json.loads(s)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


async def _gems_analyze_suggest_update(
    *,
    ws: WebSocket,
    gem: dict[str, Any],
    criteria: str,
    model_override: str | None = None,
) -> tuple[Optional[dict[str, Any]], str]:
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return None, "missing_api_key"

    gid = _normalize_gem_id(gem.get("id"))
    if not gid:
        return None, "missing_gem_id"

    sys_kv = getattr(ws.state, "sys_kv", None)
    model = _normalize_model_name(str(os.getenv("GEMINI_TEXT_MODEL") or "gemini-2.0-flash").strip() or "gemini-2.0-flash")
    if model_override:
        try:
            model = _normalize_model_name(str(model_override or "").strip())
        except Exception:
            pass
    if isinstance(sys_kv, dict):
        # Optional override via sys kv.
        try:
            override = str(sys_kv.get("gems.analyze.model") or "").strip()
            if override:
                model = _normalize_model_name(override)
        except Exception:
            pass

    current = {
        "id": gid,
        "name": str(gem.get("name") or "").strip(),
        "purpose": str(gem.get("purpose") or "").strip(),
        "system_instruction": str(gem.get("system_instruction") or "").strip(),
        "user_instruction": str(gem.get("user_instruction") or "").strip(),
        "output_format": str(gem.get("output_format") or "").strip(),
        "tools_policy": str(gem.get("tools_policy") or "").strip(),
    }

    criteria_text = str(criteria or "").strip()
    if not criteria_text:
        criteria_text = "Improve clarity, safety, and determinism. Keep it concise and actionable."

    system_instruction = (
        "You are an expert prompt engineer. You will propose an improved gem configuration. "
        "Return ONLY valid JSON for the updated gem object. "
        "Do not include markdown, code fences, or commentary. "
        "Do not rename the gem id."
    ).strip()

    prompt = (
        "Update this gem according to the user's criteria. "
        "Only include these keys: id,name,purpose,system_instruction,user_instruction,output_format,tools_policy. "
        "Keep fields short and practical. Preserve user's language (Thai stays Thai).\n\n"
        f"User criteria:\n{criteria_text}\n\n"
        f"Current gem JSON:\n{json.dumps(current, ensure_ascii=False)}\n"
    )

    try:
        client = genai.Client(api_key=api_key)
        cfg = {"system_instruction": system_instruction}
        res = await client.aio.models.generate_content(model=model, contents=prompt, config=cfg)
        txt = getattr(res, "text", None)
        if txt is None:
            txt = str(res)
        parsed = _extract_json_object(str(txt or ""))
        if not isinstance(parsed, dict):
            return None, "invalid_json"
        out_id = _normalize_gem_id(parsed.get("id"))
        if out_id and out_id != gid:
            return None, "gem_id_mismatch"
        parsed["id"] = gid
        return parsed, ""
    except Exception as e:
        return None, str(e)


async def _sheet_gems_update_row(*, spreadsheet_id: str, sheet_name: str, row_number: int, row: list[Any]) -> dict[str, Any]:
    tool = _pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
    rng = f"{sheet_name}!A{int(row_number)}:Q{int(row_number)}"
    res = await _mcp_tools_call(
        tool,
        {
            "spreadsheet_id": spreadsheet_id,
            "range": rng,
            "values": [row],
            "value_input_option": "RAW",
        },
    )
    parsed = _mcp_text_json(res)
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


async def _refresh_sheet_gems_background(ws: WebSocket, lang: str) -> None:
    global _SHEET_GEMS_REFRESHING, _SHEET_GEMS_LAST_REFRESH_AT
    now = int(time.time())
    if _SHEET_GEMS_REFRESHING:
        return
    if _SHEET_GEMS_LAST_REFRESH_AT and now - int(_SHEET_GEMS_LAST_REFRESH_AT) < 10:
        return
    _SHEET_GEMS_REFRESHING = True
    _SHEET_GEMS_LAST_REFRESH_AT = now
    try:
        sys_kv = getattr(ws.state, "sys_kv", None)
        payload = await _load_sheet_gems(sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
        _set_cached_sheet_gems(payload)
    except Exception:
        pass
    finally:
        _SHEET_GEMS_REFRESHING = False


async def _resolve_sheet_gem(gem_name: str, sys_kv: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    gem_id = _normalize_gem_id(gem_name)
    if not gem_id:
        return None
    cached = _get_cached_sheet_gems()
    if isinstance(cached, dict):
        gems = cached.get("gems")
        if isinstance(gems, dict) and isinstance(gems.get(gem_id), dict):
            return gems.get(gem_id)
    payload = await _load_sheet_gems(sys_kv=sys_kv)
    try:
        _set_cached_sheet_gems(payload)
    except Exception:
        pass
    gems = payload.get("gems") if isinstance(payload, dict) else None
    if isinstance(gems, dict) and isinstance(gems.get(gem_id), dict):
        return gems.get(gem_id)
    return None


async def _resolve_gem_instruction_and_model(*, gem_name: str | None, sys_kv: Optional[dict[str, Any]] = None) -> tuple[str, Optional[str]]:
    effective_name: str | None = gem_name
    if (effective_name is None or not str(effective_name).strip()) and isinstance(sys_kv, dict) and sys_kv:
        sys_default = str(sys_kv.get("jarvis.gem_default") or "").strip()
        if sys_default:
            effective_name = sys_default

    name = _resolve_gem_name(effective_name)
    sheet_gem = None
    try:
        sheet_gem = await _resolve_sheet_gem(name, sys_kv=sys_kv)
    except Exception:
        sheet_gem = None
    if isinstance(sheet_gem, dict):
        instruction = str(sheet_gem.get("instruction") or "").strip()
        model = str(sheet_gem.get("model") or "").strip() or None
        if instruction:
            return instruction, model
    return _gem_instruction(name), None


async def _load_sys_kv_from_sheet() -> dict[str, str]:
    spreadsheet_id = _system_spreadsheet_id()
    if not spreadsheet_id:
        return {}
    sys_sheet = _system_sheet_name()
    try:
        rows = await _load_sheet_kv5(spreadsheet_id=spreadsheet_id, sheet_name=sys_sheet)
    except Exception:
        rows = []
    out: dict[str, str] = {}
    for it in rows:
        if not isinstance(it, dict):
            continue
        k = str(it.get("key") or "").strip()
        v = str(it.get("value") or "").strip()
        if k:
            out[k] = v
    return out


def _require_env(name: str) -> str:
    value = str(os.getenv(name, "") or "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


load_dotenv()

_PROCESS_START_TS = time.time()

GEMINI_LIVE_MODEL_OVERRIDE = str(os.getenv("GEMINI_LIVE_MODEL") or "").strip()
GEMINI_LIVE_MODEL_DEFAULT = "gemini-2.5-flash-native-audio-preview-12-2025"

JARVIS_GEM_DEFAULT = str(os.getenv("JARVIS_GEM_DEFAULT") or "").strip() or "default"

_JARVIS_GEMS: dict[str, str] = {
    "default": "",
    "triage": (
        "You are Jarvis in triage mode. Ask only the minimum clarifying questions. "
        "Prefer short, actionable steps. If the user provides logs/errors, summarize the likely cause and the next diagnostic step."
    ),
    "writer": (
        "You are Jarvis in writing mode. Produce polished text. "
        "Use clear structure. Avoid filler. Maintain the user's language."
    ),
    "newsbrief_th": (
        "You are Jarvis in Thai morning-brief mode. Produce a concise Thai news brief. "
        "If given a single article, summarize in 3-5 short sentences. "
        "If given multiple items, group by topic and output bullet points. "
        "Prioritize: who/what/when, numbers, impact, and what to watch next. "
        "Do NOT add facts beyond the provided text. "
        "End with a 'Sources:' line listing any provided URLs (one per line)."
    ),
}


def _resolve_gem_name(value: str | None) -> str:
    name = str(value or "").strip().lower() or JARVIS_GEM_DEFAULT
    if name in _JARVIS_GEMS:
        return name
    return "default"


def _gem_instruction(name: str | None) -> str:
    resolved = _resolve_gem_name(name)
    return str(_JARVIS_GEMS.get(resolved) or "").strip()

_REMINDER_TITLE_MODEL_SINGLE = (
    str(os.getenv("JARVIS_REMINDER_TITLE_MODEL") or os.getenv("GEMINI_TEXT_MODEL") or "gemini-2.0-flash").strip()
    or "gemini-2.0-flash"
)


def _parse_model_list(value: str) -> list[str]:
    parts = [p.strip() for p in str(value or "").split(",")]
    return [p for p in parts if p]


def _normalize_model_name(name: str) -> str:
    s = str(name or "").strip()
    if s.startswith("models/"):
        s = s[len("models/") :]
    return s


def _normalize_models_prefix(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return ""
    return s if s.startswith("models/") else f"models/{s}"


REMINDER_TITLE_MODELS: list[str] = [
    _normalize_model_name(m) for m in _parse_model_list(str(os.getenv("JARVIS_REMINDER_TITLE_MODELS") or "").strip())
]
if not REMINDER_TITLE_MODELS:
    REMINDER_TITLE_MODELS = [
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
        "gemini-pro-latest",
        _normalize_model_name(_REMINDER_TITLE_MODEL_SINGLE),
    ]

INSTANCE_ID = str(os.getenv("JARVIS_INSTANCE_ID") or "").strip() or f"jarvis_{uuid.uuid4().hex[:10]}"

logger = logging.getLogger("jarvis-backend")
logging.basicConfig(level=logging.INFO)


def _system_spreadsheet_id() -> str:
    # Required.
    v = str(os.getenv("CHABA_SYSTEM_SPREADSHEET_ID") or "").strip()
    if not v:
        raise RuntimeError("missing_env: CHABA_SYSTEM_SPREADSHEET_ID")
    return v


def _system_sheet_name() -> str:
    # Required.
    v = str(os.getenv("CHABA_SYSTEM_SHEET_NAME") or "").strip()
    if not v:
        raise RuntimeError("missing_env: CHABA_SYSTEM_SHEET_NAME")
    return v

_WS_RECORD_PATH = str(os.getenv("JARVIS_WS_RECORD_PATH") or "").strip() or None
_WS_RECORD_ENABLED = bool(_WS_RECORD_PATH) or str(os.getenv("JARVIS_WS_RECORD") or "").strip().lower() in ("1", "true", "yes", "on")
_WS_RECORD_LOCK: asyncio.Lock | None = None

_SHEETS_LOGS_QUEUE: list[dict[str, Any]] = []
_SHEETS_LOGS_LOCK: asyncio.Lock | None = None
_SHEETS_LOGS_TASK: asyncio.Task[None] | None = None
_SHEETS_LOGS_SERVER_TASK: asyncio.Task[None] | None = None
_SHEETS_LOGS_LAST_HDR: float = 0.0

_LOGS_DIR = str(os.getenv("JARVIS_LOGS_DIR") or "/data/jarvis_logs").strip() or "/data/jarvis_logs"


def _today_ymd() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _ensure_logs_dir() -> str:
    d = _LOGS_DIR
    try:
        Path(d).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _ws_record_daily_path() -> str:
    base = _WS_RECORD_PATH
    if base:
        return base
    d = _ensure_logs_dir()
    return str(Path(d) / f"jarvis-ws-{_today_ymd()}.jsonl")


def _ui_log_daily_path() -> str:
    d = _ensure_logs_dir()
    return str(Path(d) / f"jarvis-ui-{_today_ymd()}.jsonl")


def _append_ui_log_entries(entries: list[dict[str, Any]]) -> int:
    if not entries:
        return 0
    path = _ui_log_daily_path()
    try:
        _ensure_logs_dir()
        appended = 0
        with open(path, "a", encoding="utf-8") as f:
            for it in entries[:500]:
                if not isinstance(it, dict):
                    continue
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
                appended += 1
        return appended
    except Exception:
        return 0


def _read_text_file_tail(path: str, max_bytes: int = 200000) -> str:
    p = str(path or "").strip()
    if not p:
        return ""
    try:
        if not os.path.exists(p):
            return ""
    except Exception:
        return ""
    try:
        size = os.path.getsize(p)
        start = max(0, int(size) - int(max_bytes))
        with open(p, "rb") as f:
            if start > 0:
                f.seek(start)
            b = f.read(int(max_bytes) + 1)
        txt = b.decode("utf-8", errors="replace")
        if start > 0:
            nl = txt.find("\n")
            if nl >= 0:
                txt = txt[nl + 1 :]
        return txt
    except Exception:
        return ""


def _read_text_file_tail_lines(path: str, max_lines: int = 100, max_bytes: int = 200000) -> str:
    p = str(path or "").strip()
    if not p:
        return ""
    n = int(max_lines) if isinstance(max_lines, int) or str(max_lines).strip().isdigit() else 100
    n = max(1, min(int(n), 5000))
    txt = _read_text_file_tail(p, max_bytes=max(1000, int(max_bytes)))
    if not txt:
        return ""
    lines = txt.splitlines()
    if len(lines) <= n:
        return txt
    return "\n".join(lines[-n:])


async def _ws_record(ws: WebSocket, direction: str, msg: Any) -> None:
    global _WS_RECORD_LOCK
    try:
        await _sheets_logs_enqueue_ws(ws, direction, msg)
    except Exception:
        pass
    if not _WS_RECORD_ENABLED:
        return
    path = _ws_record_daily_path()
    try:
        if _WS_RECORD_LOCK is None:
            _WS_RECORD_LOCK = asyncio.Lock()
        trace_id = None
        try:
            trace_id = getattr(ws.state, "trace_id", None)
        except Exception:
            trace_id = None
        rec = {
            "ts": int(time.time() * 1000),
            "direction": str(direction),
            "session_id": getattr(ws.state, "session_id", None),
            "trace_id": trace_id,
            "type": msg.get("type") if isinstance(msg, dict) else None,
            "msg": msg,
        }
        async with _WS_RECORD_LOCK:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        return


def _sheets_logs_cfg() -> dict[str, Any]:
    sys_kv = _sys_kv_snapshot()

    def _get_sys(k: str) -> str:
        return str(sys_kv.get(k) or "").strip() if isinstance(sys_kv, dict) else ""

    def _get_env(k: str) -> str:
        return str(os.getenv(k) or "").strip()

    # Env defaults (can be overridden/disabled by sys_kv).
    raw_enabled_env = _get_env("JARVIS_SHEETS_LOGS_ENABLED")
    enabled = False
    if raw_enabled_env:
        try:
            enabled = _parse_bool_cell(raw_enabled_env)
        except Exception:
            enabled = False

    sheet_name = _get_env("JARVIS_SHEETS_LOGS_SHEET_NAME")
    spreadsheet_id = _get_env("JARVIS_SHEETS_LOGS_SPREADSHEET_ID")

    raw_server_env = _get_env("JARVIS_SHEETS_LOGS_SERVER_ENABLED")
    server_enabled = False
    if raw_server_env:
        try:
            server_enabled = _parse_bool_cell(raw_server_env)
        except Exception:
            server_enabled = False

    hb_raw_env = _get_env("JARVIS_SHEETS_LOGS_SERVER_HEARTBEAT_SECONDS")
    hb_s = _safe_int(hb_raw_env, default=30) if hb_raw_env else 30

    # sys_kv overrides (explicit sys_kv disable should win).
    raw_enabled_sys = _get_sys("logs.enabled") or _get_sys("logs.sheet.enabled")
    if raw_enabled_sys:
        try:
            enabled = _parse_bool_cell(raw_enabled_sys)
        except Exception:
            enabled = False

    spreadsheet_id_sys = _get_sys("logs.spreadsheet_id") or _get_sys("logs_ss")
    if spreadsheet_id_sys:
        spreadsheet_id = spreadsheet_id_sys

    raw_server_sys = _get_sys("logs.server.enabled") or _get_sys("logs.server_events.enabled")
    if raw_server_sys:
        try:
            server_enabled = _parse_bool_cell(raw_server_sys)
        except Exception:
            server_enabled = False

    hb_raw_sys = _get_sys("logs.server.heartbeat_seconds") or _get_sys("logs.server_events.heartbeat_seconds")
    if hb_raw_sys:
        hb_s = _safe_int(hb_raw_sys, default=30)

    hb_s = max(5, min(int(hb_s), 3600))
    if not spreadsheet_id:
        try:
            spreadsheet_id = _system_spreadsheet_id()
        except Exception:
            spreadsheet_id = ""
    return {
        "enabled": enabled,
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "server_enabled": server_enabled,
        "server_heartbeat_seconds": hb_s,
    }


def _sheets_logs_ready(cfg: dict[str, Any] | None = None) -> bool:
    if cfg is None:
        cfg = _sheets_logs_cfg()
    if not isinstance(cfg, dict):
        return False
    if not cfg.get("enabled"):
        return False
    spreadsheet_id = str(cfg.get("spreadsheet_id") or "").strip()
    sheet_name = str(cfg.get("sheet_name") or "").strip()
    return bool(spreadsheet_id and sheet_name)


async def _sheets_logs_ensure_header(*, spreadsheet_id: str, sheet_name: str) -> None:
    global _SHEETS_LOGS_LAST_HDR
    now = time.time()
    if _SHEETS_LOGS_LAST_HDR and (now - _SHEETS_LOGS_LAST_HDR) < 60.0:
        return
    _SHEETS_LOGS_LAST_HDR = now
    tool_get = _pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
    tool_update = _pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
    sheet_a1 = _sheet_name_to_a1(sheet_name, default="logs")
    try:
        res_h = await _mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_a1}!A1:H1"})
        parsed_h = _mcp_text_json(res_h)
        vals_h = parsed_h.get("values") if isinstance(parsed_h, dict) else None
        got_header = vals_h[0] if isinstance(vals_h, list) and vals_h and isinstance(vals_h[0], list) else None
        if got_header and any(str(x or "").strip() for x in got_header):
            return
    except Exception:
        pass
    try:
        await _mcp_tools_call(
            tool_update,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_a1}!A1:H1",
                "values": [["type", "text", "ts", "ts_ms", "direction", "session_id", "trace_id", "msg_json"]],
                "value_input_option": "RAW",
            },
        )
    except Exception:
        return


async def _sheets_logs_flush_once() -> int:
    global _SHEETS_LOGS_QUEUE, _SHEETS_LOGS_LOCK
    cfg = _sheets_logs_cfg()
    if not cfg.get("enabled"):
        return 0
    spreadsheet_id = str(cfg.get("spreadsheet_id") or "").strip()
    sheet_name = str(cfg.get("sheet_name") or "").strip()
    if not spreadsheet_id or not sheet_name:
        return 0
    if _SHEETS_LOGS_LOCK is None:
        _SHEETS_LOGS_LOCK = asyncio.Lock()
    async with _SHEETS_LOGS_LOCK:
        batch = _SHEETS_LOGS_QUEUE[:200]
        _SHEETS_LOGS_QUEUE = _SHEETS_LOGS_QUEUE[200:]
    if not batch:
        return 0
    await _sheets_logs_ensure_header(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name)
    rows: list[list[Any]] = []
    for it in batch:
        if not isinstance(it, dict):
            continue
        ts_ms = int(it.get("ts_ms") or 0)
        ts = str(it.get("ts") or "").strip()
        direction = str(it.get("direction") or "").strip()
        session_id = str(it.get("session_id") or "").strip()
        trace_id = str(it.get("trace_id") or "").strip()
        typ = str(it.get("type") or "").strip()
        text = str(it.get("text") or "").strip()
        msg_json = str(it.get("msg_json") or "").strip()
        rows.append([typ, text, ts, ts_ms, direction, session_id, trace_id, msg_json])
    if not rows:
        return 0
    tool_append = _pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
    sheet_a1 = _sheet_name_to_a1(sheet_name, default="logs")
    try:
        await _mcp_tools_call(
            tool_append,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_a1}!A:H",
                "values": rows,
                "value_input_option": "RAW",
                "insert_data_option": "INSERT_ROWS",
            },
        )
        return len(rows)
    except Exception:
        async with _SHEETS_LOGS_LOCK:
            _SHEETS_LOGS_QUEUE = batch + _SHEETS_LOGS_QUEUE
        return 0


async def _sheets_logs_flush_loop() -> None:
    while True:
        try:
            await _sheets_logs_flush_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(2.0)


async def _sheets_logs_enqueue_ws(ws: WebSocket, direction: str, msg: Any) -> None:
    global _SHEETS_LOGS_QUEUE, _SHEETS_LOGS_LOCK
    cfg = _sheets_logs_cfg()
    if not _sheets_logs_ready(cfg):
        return
    if _SHEETS_LOGS_LOCK is None:
        _SHEETS_LOGS_LOCK = asyncio.Lock()
    ts_ms = int(time.time() * 1000)
    ts = datetime.now(tz=timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    trace_id = None
    try:
        trace_id = getattr(ws.state, "trace_id", None)
    except Exception:
        trace_id = None
    msg_type = msg.get("type") if isinstance(msg, dict) else None
    text = ""
    try:
        if isinstance(msg, dict) and msg.get("text") is not None:
            text = str(msg.get("text") or "")
    except Exception:
        text = ""
    try:
        msg_json = json.dumps(msg, ensure_ascii=False)
    except Exception:
        msg_json = str(msg)
    rec = {
        "ts_ms": ts_ms,
        "ts": ts,
        "direction": str(direction),
        "session_id": getattr(ws.state, "session_id", None),
        "trace_id": trace_id,
        "type": msg_type,
        "text": text,
        "msg_json": msg_json,
        "instance_id": INSTANCE_ID,
    }
    async with _SHEETS_LOGS_LOCK:
        _SHEETS_LOGS_QUEUE.append(rec)
        if len(_SHEETS_LOGS_QUEUE) > 5000:
            _SHEETS_LOGS_QUEUE = _SHEETS_LOGS_QUEUE[-5000:]


async def _sheets_logs_enqueue_http(*, typ: str, text: str, msg: Any | None = None) -> None:
    global _SHEETS_LOGS_QUEUE, _SHEETS_LOGS_LOCK
    cfg = _sheets_logs_cfg()
    if not _sheets_logs_ready(cfg):
        return
    if _SHEETS_LOGS_LOCK is None:
        _SHEETS_LOGS_LOCK = asyncio.Lock()
    ts_ms = int(time.time() * 1000)
    ts = datetime.now(tz=timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    msg_json = ""
    try:
        if msg is not None:
            msg_json = json.dumps(msg, ensure_ascii=False)
    except Exception:
        msg_json = str(msg)
    rec = {
        "ts_ms": ts_ms,
        "ts": ts,
        "direction": "http",
        "session_id": "",
        "trace_id": "",
        "type": str(typ or "http"),
        "text": str(text or ""),
        "msg_json": msg_json,
        "instance_id": INSTANCE_ID,
    }
    async with _SHEETS_LOGS_LOCK:
        _SHEETS_LOGS_QUEUE.append(rec)
        if len(_SHEETS_LOGS_QUEUE) > 5000:
            _SHEETS_LOGS_QUEUE = _SHEETS_LOGS_QUEUE[-5000:]


async def _sheets_logs_enqueue_server(*, typ: str, text: str, msg: Any | None = None) -> None:
    global _SHEETS_LOGS_QUEUE, _SHEETS_LOGS_LOCK
    cfg = _sheets_logs_cfg()
    if not _sheets_logs_ready(cfg) or not cfg.get("server_enabled"):
        return
    if _SHEETS_LOGS_LOCK is None:
        _SHEETS_LOGS_LOCK = asyncio.Lock()
    ts_ms = int(time.time() * 1000)
    ts = datetime.now(tz=timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    msg_json = ""
    try:
        if msg is not None:
            msg_json = json.dumps(msg, ensure_ascii=False)
    except Exception:
        msg_json = str(msg)
    rec = {
        "ts_ms": ts_ms,
        "ts": ts,
        "direction": "server",
        "session_id": "",
        "trace_id": "",
        "type": str(typ or "server"),
        "text": str(text or ""),
        "msg_json": msg_json,
        "instance_id": INSTANCE_ID,
    }
    async with _SHEETS_LOGS_LOCK:
        _SHEETS_LOGS_QUEUE.append(rec)
        if len(_SHEETS_LOGS_QUEUE) > 5000:
            _SHEETS_LOGS_QUEUE = _SHEETS_LOGS_QUEUE[-5000:]


async def _sheets_logs_server_loop() -> None:
    last_enabled = False
    while True:
        try:
            cfg = _sheets_logs_cfg()
            enabled = bool(cfg.get("enabled")) and bool(cfg.get("server_enabled"))
            hb_s = int(cfg.get("server_heartbeat_seconds") or 30)
            if enabled and not last_enabled:
                try:
                    await _sheets_logs_enqueue_server(typ="server.start", text="started")
                except Exception:
                    pass
            last_enabled = enabled
            if enabled:
                try:
                    uptime_s = max(0.0, float(time.time() - float(_PROCESS_START_TS)))
                except Exception:
                    uptime_s = 0.0
                await _sheets_logs_enqueue_server(
                    typ="server.heartbeat",
                    text=f"uptime_s={int(uptime_s)}",
                )
            await asyncio.sleep(float(hb_s) if enabled else 5.0)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(5.0)


def _ws_capture_trace_id(ws: WebSocket, msg: Any) -> str | None:
    trace_id: str | None = None
    try:
        if isinstance(msg, dict) and msg.get("trace_id") is not None:
            trace_id = str(msg.get("trace_id") or "").strip() or None
    except Exception:
        trace_id = None
    try:
        ws.state.trace_id = trace_id
    except Exception:
        pass
    return trace_id


def _ws_ensure_trace_id(ws: WebSocket, trace_id: str | None) -> str:
    tid = str(trace_id or "").strip()
    if not tid:
        tid = uuid.uuid4().hex
    try:
        ws.state.trace_id = tid
    except Exception:
        pass
    return tid


def _voice_job_done_enabled(ws: WebSocket) -> bool:
    sys_kv = getattr(ws.state, "sys_kv", None)
    if isinstance(sys_kv, dict):
        raw = str(sys_kv.get("voice.job_done") or "").strip()
        if raw:
            return _parse_bool_cell(raw)
    raw2 = str(os.getenv("JARVIS_VOICE_JOB_DONE") or "").strip()
    if raw2:
        return _parse_bool_cell(raw2)
    return False


def _job_short_id(trace_id: str | None) -> str:
    s = str(trace_id or "").strip()
    if not s:
        return uuid.uuid4().hex[:6]
    s = re.sub(r"[^a-zA-Z0-9]+", "", s)
    if len(s) >= 6:
        return s[:6].lower()
    if s:
        return s.lower()
    return uuid.uuid4().hex[:6]


def _ws_mark_job_error(ws: WebSocket, trace_id: str) -> None:
    if not trace_id:
        return
    try:
        st = getattr(ws.state, "job_error_trace_ids", None)
        if not isinstance(st, set):
            st = set()
            ws.state.job_error_trace_ids = st
        st.add(str(trace_id))
    except Exception:
        return


def _ws_job_had_error(ws: WebSocket, trace_id: str) -> bool:
    if not trace_id:
        return False
    try:
        st = getattr(ws.state, "job_error_trace_ids", None)
        if isinstance(st, set):
            return str(trace_id) in st
    except Exception:
        return False
    return False


async def _ws_voice_job_done(ws: WebSocket, trace_id: str) -> None:
    if not trace_id:
        return
    if not _voice_job_done_enabled(ws):
        return
    if _ws_job_had_error(ws, trace_id):
        return
    try:
        last = getattr(ws.state, "job_done_voice_last_trace_id", None)
        if last and str(last) == str(trace_id):
            return
        ws.state.job_done_voice_last_trace_id = str(trace_id)
    except Exception:
        pass

    sid = _job_short_id(trace_id)
    lang = str(getattr(ws.state, "user_lang", "") or "").strip().lower()
    msg = f"Job {sid} Done"
    if lang == "th":
        msg = f"งาน {sid} เสร็จแล้ว"
    try:
        await _live_say(ws, msg)
    except Exception:
        return


async def _ws_send_json(ws: WebSocket, payload: dict[str, Any], trace_id: str | None = None) -> None:
    if not isinstance(payload, dict):
        return
    tid = trace_id
    if tid is None:
        try:
            tid = getattr(ws.state, "trace_id", None)
        except Exception:
            tid = None
    if tid:
        payload = {**payload, "trace_id": tid}

    try:
        if tid and str(payload.get("type") or "").strip().lower() == "error":
            _ws_mark_job_error(ws, str(tid))
    except Exception:
        pass

    # Client tagging: attach stable client metadata (if provided by the frontend)
    try:
        client_tag = getattr(ws.state, "client_tag", None)
        client_id = getattr(ws.state, "client_id", None)
        if client_tag:
            payload = {**payload, "client_tag": str(client_tag)}
        if client_id:
            payload = {**payload, "client_id": str(client_id)}
    except Exception:
        pass
    try:
        await _ws_record(ws, "out", payload)
    except Exception:
        pass

    try:
        if str(payload.get("type") or "").strip().lower() == "text":
            text0 = str(payload.get("text") or "")
            low = text0.strip().lower()
            if low.startswith("system module status report"):
                asyncio.create_task(
                    _maybe_capture_to_memory(
                        ws,
                        key="runtime.module_status_report.latest",
                        value=text0,
                        source="ws.text.module_status_report",
                    ),
                    name="capture_module_status_report",
                )
    except Exception:
        pass
    await ws.send_json(payload)


async def tools_api_call(tool_name: str, args: dict[str, Any], session_id: str | None = None) -> Any:
    if tool_name.startswith("mcp_"):
        mcp_name = tool_name[len("mcp_") :].strip()
        if not mcp_name:
            raise HTTPException(status_code=400, detail="missing_mcp_tool_name")

        url = MCP_BASE_URL
        forwarded_args = dict(args or {})
        if mcp_name.startswith("browser_") and MCP_PLAYWRIGHT_BASE_URL:
            url = MCP_PLAYWRIGHT_BASE_URL
            forwarded_args = _adapt_playwright_tool_args(mcp_name, forwarded_args)
        return await mcp_client.mcp_tools_call(url, mcp_name, forwarded_args)

    raise HTTPException(status_code=400, detail={"unknown_tool": tool_name})


async def _ws_progress(
    ws: WebSocket,
    message: str,
    *,
    phase: str,
    tool_name: str | None = None,
    step: int | None = None,
    total: int | None = None,
    trace_id: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "type": "progress",
        "phase": str(phase or ""),
        "message": str(message or ""),
    }
    if tool_name:
        payload["tool"] = str(tool_name)
    if step is not None:
        payload["step"] = int(step)
    if total is not None:
        payload["total"] = int(total)
    await _ws_send_json(ws, payload, trace_id=trace_id)

app = FastAPI(title="jarvis-backend", version="0.1.0")


class _UILogAppendRequest(BaseModel):
    entries: list[dict[str, Any]] = Field(default_factory=list)


class MemoAddRequest(BaseModel):
    memo: str
    group: Optional[str] = None
    status: Optional[str] = None
    subject: Optional[str] = None
    v: Optional[str] = None
    result: Optional[str] = None
    active: Optional[bool] = None


class MemoIndexBackfillRequest(BaseModel):
    limit: Optional[int] = 200


class MemoSummarizeRelatedRequest(BaseModel):
    q: Optional[str] = None
    memo_id: Optional[int] = None
    k: Optional[int] = 30
    group: Optional[str] = None
    style: Optional[str] = "timeline"


class MemoRelateRequest(BaseModel):
    q: Optional[str] = None
    memo_id: Optional[int] = None
    k: Optional[int] = 50
    group: Optional[str] = None


class MemoRepairIdsRequest(BaseModel):
    limit: Optional[int] = 500
    dry_run: Optional[bool] = False


class MemoReorderColumnsRequest(BaseModel):
    limit: Optional[int] = 1000
    dry_run: Optional[bool] = False


class SysKvSetRequest(BaseModel):
    key: str
    value: str
    dry_run: Optional[bool] = False


class MemorySetRequest(BaseModel):
    key: str
    value: str
    enabled: Optional[bool] = True
    scope: Optional[str] = "global"
    priority: Optional[int] = 0


@app.post("/logs/ui/append")
@app.post("/jarvis/logs/ui/append")
async def logs_ui_append(req: _UILogAppendRequest) -> dict[str, Any]:
    path = _ui_log_daily_path()
    items = req.entries if isinstance(req.entries, list) else []
    appended = _append_ui_log_entries(items)
    if appended and items:
        for it in items:
            try:
                if not isinstance(it, dict):
                    continue
                await _sheets_logs_enqueue_http(
                    typ=str(it.get("type") or "ui"),
                    text=str(it.get("text") or ""),
                    msg=it,
                )
            except Exception:
                pass
    return {"ok": True, "path": path, "appended": appended}


@app.get("/logs/sheets/status")
@app.get("/jarvis/api/logs/sheets/status")
@app.get("/jarvis/logs/sheets/status")
def logs_sheets_status() -> dict[str, Any]:
    cfg = _sheets_logs_cfg()
    q_len = 0
    try:
        q_len = len(_SHEETS_LOGS_QUEUE)
    except Exception:
        q_len = 0
    env_enabled = str(os.getenv("JARVIS_SHEETS_LOGS_ENABLED") or "")
    env_sheet_name = str(os.getenv("JARVIS_SHEETS_LOGS_SHEET_NAME") or "")
    env_spreadsheet_id = str(os.getenv("JARVIS_SHEETS_LOGS_SPREADSHEET_ID") or "")
    return {
        **cfg,
        "queue_len": q_len,
        "ok": True,
        "env": {
            "JARVIS_SHEETS_LOGS_ENABLED": env_enabled,
            "JARVIS_SHEETS_LOGS_SHEET_NAME": env_sheet_name,
            "JARVIS_SHEETS_LOGS_SPREADSHEET_ID": env_spreadsheet_id,
        },
    }


def _api_token_required_value() -> str:
    try:
        sys_kv = _sys_kv_snapshot()
        if isinstance(sys_kv, dict):
            v = str(sys_kv.get("jarvis.api_token") or "").strip()
            if v:
                return v
    except Exception:
        pass
    return str(os.getenv("JARVIS_API_TOKEN") or "").strip()


def _require_api_token_if_configured(token: str | None) -> None:
    required = _api_token_required_value()
    if not required:
        return
    got = str(token or "").strip()
    if not got or got != required:
        raise HTTPException(status_code=401, detail="unauthorized")


def _system_instruction_from_sys_kv(sys_kv: Any) -> str:
    if not isinstance(sys_kv, dict):
        return ""
    base = str(sys_kv.get("system.instruction") or "").strip()
    extras: list[tuple[int, str, str]] = []
    for k, v in sys_kv.items():
        key = str(k or "").strip()
        if not key.startswith("system.instructions."):
            continue
        suffix = key[len("system.instructions.") :].strip()
        pr = 10**9
        if suffix:
            try:
                pr = int(suffix)
            except Exception:
                pr = 10**9
        txt = str(v or "").strip()
        if txt:
            extras.append((pr, key, txt))
    extras.sort(key=lambda t: (t[0], t[1]))
    parts: list[str] = []
    if base:
        parts.append(base)
    for _, _, txt in extras:
        parts.append(txt)
    return "\n\n".join([p for p in parts if str(p).strip()]).strip()


def _memo_sheet_cfg_from_sys_kv(sys_kv: dict[str, Any] | None) -> tuple[str, str]:
    spreadsheet_id = ""
    sheet_name = ""
    if isinstance(sys_kv, dict):
        spreadsheet_id = str(
            sys_kv.get("memo.spreadsheet_name")
            or sys_kv.get("memo.spreadsheet_id")
            or sys_kv.get("memo_ss")
            or ""
        ).strip()
        sheet_name = str(sys_kv.get("memo.sheet_name") or sys_kv.get("memo_sheet_name") or sys_kv.get("memo_sh") or "").strip()
    if not spreadsheet_id:
        spreadsheet_id = _system_spreadsheet_id()
    return (spreadsheet_id, sheet_name)


async def _sheet_get_header_row(*, spreadsheet_id: str, sheet_a1: str, max_cols: str = "Z") -> list[Any]:
    return await sheets_utils.sheet_get_header_row(
        spreadsheet_id=spreadsheet_id,
        sheet_a1=sheet_a1,
        max_cols=max_cols,
        mcp_tools_call=_mcp_tools_call,
        pick_sheets_tool_name=_pick_sheets_tool_name,
        mcp_text_json=_mcp_text_json,
    )


async def _memo_ensure_header(*, spreadsheet_id: str, sheet_a1: str, force: bool = False) -> None:
    await memo_sheet.ensure_header(
        spreadsheet_id=spreadsheet_id,
        sheet_a1=sheet_a1,
        force=force,
        sheet_get_header_row=_sheet_get_header_row,
        mcp_tools_call=_mcp_tools_call,
        pick_sheets_tool_name=_pick_sheets_tool_name,
    )


@app.post("/memo/header/normalize")
@app.post("/jarvis/memo/header/normalize")
async def memo_header_normalize(x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token")) -> dict[str, Any]:
    _require_api_token_if_configured(x_api_token)
    sys_kv = _sys_kv_snapshot()

    def _resolve(kv: Any) -> tuple[str, str]:
        return _memo_sheet_cfg_from_sys_kv(kv if isinstance(kv, dict) else None)

    spreadsheet_id, sheet_name = _resolve(sys_kv)
    if not spreadsheet_id or not sheet_name:
        try:
            class _DummyWS:
                def __init__(self) -> None:
                    from types import SimpleNamespace

                    self.state = SimpleNamespace()

            await _load_ws_system_kv(_DummyWS())
        except Exception:
            pass
        sys_kv = _sys_kv_snapshot()
        spreadsheet_id, sheet_name = _resolve(sys_kv)

    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="missing_memo_ss")
    if not sheet_name:
        raise HTTPException(status_code=400, detail="missing_memo_sheet_name")
    sheet_a1 = _sheet_name_to_a1(sheet_name, default="memo")
    before = await _sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
    await _memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, force=True)
    after = await _sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
    return {"ok": True, "spreadsheet_id": spreadsheet_id, "sheet": sheet_name, "before": before, "after": after}


@app.post("/memo/repair/ids")
@app.post("/jarvis/memo/repair/ids")
async def memo_repair_ids(
    req: MemoRepairIdsRequest,
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    _require_api_token_if_configured(x_api_token)
    sys_kv = _sys_kv_snapshot()
    spreadsheet_id, sheet_name = _memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="missing_memo_ss")
    if not sheet_name:
        raise HTTPException(status_code=400, detail="missing_memo_sheet_name")
    sheet_a1 = _sheet_name_to_a1(sheet_name, default="memo")

    # Ensure header is canonical so idx mapping is stable.
    try:
        await _memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, force=False)
    except Exception:
        pass
    header = await _sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
    idx = _idx_from_header(header)
    if not idx:
        raise HTTPException(status_code=400, detail="memo_sheet_missing_header")

    j_id = idx.get("id")
    if not isinstance(j_id, int) or j_id < 0:
        raise HTTPException(status_code=400, detail="memo_sheet_missing_id_col")

    tool_get = _pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
    tool_update = _pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")

    # Read a window of rows (A2:J) and repair IDs in-place.
    res = await _mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_a1}!A2:J"})
    parsed = _mcp_text_json(res)
    data = parsed.get("data") if isinstance(parsed, dict) else None
    vals = parsed.get("values") if isinstance(parsed, dict) else None
    if not isinstance(vals, list) and isinstance(data, dict):
        vals = data.get("values")
    rows = vals if isinstance(vals, list) else []
    if not isinstance(rows, list):
        rows = []

    limit = max(1, min(int(req.limit or 500), 5000))
    window = rows[-limit:]

    # First pass: compute max existing id and find duplicates/missing.
    seen: dict[int, int] = {}
    max_id = 0
    parsed_ids: list[int | None] = []
    for r in window:
        if not isinstance(r, list):
            parsed_ids.append(None)
            continue
        raw = ""
        if j_id < len(r):
            raw = str(r[j_id] or "").strip()
        n: int | None = None
        if raw:
            try:
                n = int(float(raw))
            except Exception:
                n = None
        if isinstance(n, int) and n > 0:
            max_id = max(max_id, n)
            seen[n] = seen.get(n, 0) + 1
        parsed_ids.append(n if isinstance(n, int) and n > 0 else None)

    # Second pass: assign new IDs for missing/invalid and for duplicates (keep first occurrence).
    next_id = max_id + 1 if max_id > 0 else 1
    dup_used: set[int] = set()
    fixes: list[dict[str, Any]] = []
    for i, n in enumerate(parsed_ids):
        is_dup = False
        if isinstance(n, int) and n > 0 and seen.get(n, 0) > 1:
            # Keep first occurrence; reassign subsequent ones.
            if n in dup_used:
                is_dup = True
            else:
                dup_used.add(n)
        if n is None or is_dup:
            new_id = next_id
            next_id += 1
            # Compute absolute sheet row number: A2 is first row in rows list.
            abs_row = 2 + (len(rows) - len(window)) + i
            fixes.append({"row": abs_row, "old": n, "new": new_id})

    if not fixes:
        return {"ok": True, "spreadsheet_id": spreadsheet_id, "sheet": sheet_name, "fixed": 0, "dry_run": bool(req.dry_run)}

    if not bool(req.dry_run):
        id_col_letter = "A"
        try:
            id_col_letter = chr(ord("A") + int(j_id)) if int(j_id) < 26 else "A"
        except Exception:
            id_col_letter = "A"
        for f in fixes:
            await _mcp_tools_call(
                tool_update,
                {
                    "spreadsheet_id": spreadsheet_id,
                    "range": f"{sheet_a1}!{id_col_letter}{int(f['row'])}:{id_col_letter}{int(f['row'])}",
                    "values": [[int(f["new"])]] ,
                    "value_input_option": "USER_ENTERED",
                },
            )

    return {
        "ok": True,
        "spreadsheet_id": spreadsheet_id,
        "sheet": sheet_name,
        "fixed": len(fixes),
        "dry_run": bool(req.dry_run),
        "samples": fixes[:20],
    }


@app.post("/memo/columns/reorder")
@app.post("/jarvis/memo/columns/reorder")
async def memo_columns_reorder(
    req: MemoReorderColumnsRequest,
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    _require_api_token_if_configured(x_api_token)
    sys_kv = _sys_kv_snapshot()
    spreadsheet_id, sheet_name = _memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="missing_memo_ss")
    if not sheet_name:
        raise HTTPException(status_code=400, detail="missing_memo_sheet_name")
    sheet_a1 = _sheet_name_to_a1(sheet_name, default="memo")

    desired = [
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

    tool_get = _pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
    tool_update = _pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")

    # Read header + rows in current physical order.
    res = await _mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_a1}!A1:J"})
    parsed = _mcp_text_json(res)
    data = parsed.get("data") if isinstance(parsed, dict) else None
    vals = parsed.get("values") if isinstance(parsed, dict) else None
    if not isinstance(vals, list) and isinstance(data, dict):
        vals = data.get("values")
    rows = vals if isinstance(vals, list) else []
    if not isinstance(rows, list) or not rows:
        rows = []

    got_header = rows[0] if rows and isinstance(rows[0], list) else []
    got_lower = [str(x or "").strip().lower() for x in got_header]
    desired_lower = [x.lower() for x in desired]

    # If header already matches desired, no migration needed.
    if got_lower[: len(desired_lower)] == desired_lower:
        return {"ok": True, "spreadsheet_id": spreadsheet_id, "sheet": sheet_name, "changed": False, "dry_run": bool(req.dry_run)}

    # Build name->index map from current header.
    name_to_j: dict[str, int] = {}
    for j, name in enumerate(got_lower):
        if name and name not in name_to_j:
            name_to_j[name] = int(j)

    missing = [c for c in desired_lower if c not in name_to_j]
    if missing:
        raise HTTPException(status_code=400, detail={"error": "memo_columns_reorder_missing_cols", "missing": missing, "header": got_header})

    # Fetch data rows (A2:J) and transform.
    limit = max(1, min(int(req.limit or 1000), 20000))
    res2 = await _mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_a1}!A2:J"})
    parsed2 = _mcp_text_json(res2)
    data2 = parsed2.get("data") if isinstance(parsed2, dict) else None
    vals2 = parsed2.get("values") if isinstance(parsed2, dict) else None
    if not isinstance(vals2, list) and isinstance(data2, dict):
        vals2 = data2.get("values")
    data_rows = vals2 if isinstance(vals2, list) else []
    if not isinstance(data_rows, list):
        data_rows = []
    window = data_rows[-limit:]

    def _get_cell(r: list[Any], name: str) -> Any:
        j = name_to_j.get(str(name).strip().lower())
        if j is None or j < 0:
            return ""
        return r[j] if j < len(r) else ""

    transformed: list[list[Any]] = []
    for r in window:
        if not isinstance(r, list):
            continue
        transformed.append([_get_cell(r, c) for c in desired])

    if bool(req.dry_run):
        return {
            "ok": True,
            "spreadsheet_id": spreadsheet_id,
            "sheet": sheet_name,
            "changed": True,
            "dry_run": True,
            "before_header": got_header,
            "after_header": desired,
            "rows_to_rewrite": len(transformed),
            "sample_before": window[:2],
            "sample_after": transformed[:2],
        }

    # Write new header.
    await _mcp_tools_call(
        tool_update,
        {
            "spreadsheet_id": spreadsheet_id,
            "range": f"{sheet_a1}!A1:J1",
            "values": [desired],
            "value_input_option": "RAW",
        },
    )

    # Rewrite window rows back into sheet in-place.
    start_row = 2 + max(0, len(data_rows) - len(window))
    batch_size = 200
    for i in range(0, len(transformed), batch_size):
        chunk = transformed[i : i + batch_size]
        r0 = start_row + i
        r1 = r0 + len(chunk) - 1
        await _mcp_tools_call(
            tool_update,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_a1}!A{int(r0)}:J{int(r1)}",
                "values": chunk,
                "value_input_option": "USER_ENTERED",
            },
        )

    # Ensure backend canonical header logic matches the new order.
    try:
        await _memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, force=False)
    except Exception:
        pass

    return {"ok": True, "spreadsheet_id": spreadsheet_id, "sheet": sheet_name, "changed": True, "dry_run": False, "rows_rewritten": len(transformed)}


@app.post("/memo/add")
@app.post("/jarvis/memo/add")
async def memo_add(
    req: MemoAddRequest,
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
    x_session_id: Optional[str] = Header(default=None, alias="X-Session-Id"),
) -> dict[str, Any]:
    _require_api_token_if_configured(x_api_token)
    sys_kv = _sys_kv_snapshot()

    # If the caller provides a live session id, route through the memo tool path.
    # This keeps behavior consistent with voice/text triggers and returns a stable memo id.
    if str(x_session_id or "").strip():
        sid = str(x_session_id or "").strip()
        args: dict[str, Any] = {"memo": str(req.memo or "").strip()}
        if req.group is not None:
            args["group"] = str(req.group or "").strip()
        if req.subject is not None:
            args["subject"] = str(req.subject or "").strip()
        if req.status is not None:
            args["status"] = str(req.status or "").strip()
        if req.result is not None:
            args["result"] = str(req.result or "").strip()
        if req.active is not None:
            args["active"] = bool(req.active)
        res = await _handle_mcp_tool_call(sid, "memo_add", args)
        if isinstance(res, dict):
            return res
        return {"ok": True, "result": res}

    def _is_enabled(kv: Any) -> bool:
        try:
            raw_enabled = str(kv.get("memo.enabled") or "").strip() if isinstance(kv, dict) else ""
            return _parse_bool_cell(raw_enabled) if raw_enabled else False
        except Exception:
            return False

    enabled = _is_enabled(sys_kv)
    if not enabled:
        try:
            class _DummyWS:
                def __init__(self) -> None:
                    from types import SimpleNamespace

                    self.state = SimpleNamespace()

            await _load_ws_system_kv(_DummyWS())
        except Exception:
            pass
        sys_kv = _sys_kv_snapshot()
        enabled = _is_enabled(sys_kv)
    if not enabled:
        raise HTTPException(status_code=400, detail="memo_disabled")

    spreadsheet_id, sheet_name = _memo_sheet_cfg_from_sys_kv(sys_kv)
    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="missing_memo_ss")
    if not sheet_name:
        raise HTTPException(status_code=400, detail="missing_memo_sheet_name")

    sheet_a1 = _sheet_name_to_a1(sheet_name, default="memo")

    # Always ensure canonical header before indexing/appending. This prevents legacy/manual headers
    # from silently causing incorrect column mapping.
    try:
        await _memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, force=False)
    except Exception:
        pass

    header = await _sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
    idx = _idx_from_header(header)
    if not idx:
        ensure_err: Exception | None = None
        try:
            await _memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1)
        except Exception as e:
            ensure_err = e
        header_after = await _sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
        idx = _idx_from_header(header_after)
    if not idx:
        def _trim_list(x: Any, max_n: int = 30) -> list[Any]:
            if not isinstance(x, list):
                return []
            out = x[:max_n]
            return out

        ensure_txt = ""
        try:
            if ensure_err is not None:
                s = str(ensure_err).strip()
                if len(s) > 240:
                    s = s[:240] + "..."
                ensure_txt = f"{type(ensure_err).__name__}: {s}"
        except Exception:
            ensure_txt = ""

        detail: Any = {
            "error": "memo_sheet_missing_header",
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "sheet_a1": sheet_a1,
            "header_before": _trim_list(header),
            "header_after": _trim_list(locals().get("header_after")),
            "ensure_header_failed": ensure_txt,
        }
        raise HTTPException(status_code=400, detail=detail)

    now_dt = datetime.now(tz=timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    status = str(req.status or "").strip() or "new"

    def _col_letter(col_idx0: int) -> str:
        n = int(col_idx0) + 1
        if n <= 0:
            return "A"
        out = ""
        while n > 0:
            n, r = divmod(n - 1, 26)
            out = chr(ord("A") + r) + out
        return out or "A"

    async def _next_memo_id() -> int:
        try:
            id_col = "A"
            try:
                j0 = idx.get("id") if isinstance(idx, dict) else None
                if isinstance(j0, int) and j0 >= 0:
                    id_col = _col_letter(j0)
            except Exception:
                id_col = "A"
            tool_get = _pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
            res_get = await _mcp_tools_call(
                tool_get,
                {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_a1}!{id_col}2:{id_col}", "major_dimension": "COLUMNS"},
            )
            parsed_get = _mcp_text_json(res_get)
            data = parsed_get.get("data") if isinstance(parsed_get, dict) else None
            vals = parsed_get.get("values") if isinstance(parsed_get, dict) else None
            if not isinstance(vals, list) and isinstance(data, dict):
                vals = data.get("values")
            col = vals[0] if isinstance(vals, list) and vals and isinstance(vals[0], list) else []
            max_id = 0
            for v in col:
                s2 = str(v or "").strip()
                if not s2:
                    continue
                try:
                    n2 = int(float(s2))
                except Exception:
                    continue
                if n2 > max_id:
                    max_id = n2
            if max_id > 0:
                return max_id + 1

            # Header was normalized but existing rows may not have ids yet.
            # Fall back to a safe row-count-based next id.
            try:
                anchor_col = "A"
                j_memo = idx.get("memo") if isinstance(idx, dict) else None
                j_dt = idx.get("date_time") if isinstance(idx, dict) else None
                if isinstance(j_memo, int) and j_memo >= 0:
                    anchor_col = _col_letter(j_memo)
                elif isinstance(j_dt, int) and j_dt >= 0:
                    anchor_col = _col_letter(j_dt)
                res_rows = await _mcp_tools_call(
                    tool_get,
                    {
                        "spreadsheet_id": spreadsheet_id,
                        "range": f"{sheet_a1}!{anchor_col}2:{anchor_col}",
                        "major_dimension": "COLUMNS",
                    },
                )
                parsed_rows = _mcp_text_json(res_rows)
                data2 = parsed_rows.get("data") if isinstance(parsed_rows, dict) else None
                vals2 = parsed_rows.get("values") if isinstance(parsed_rows, dict) else None
                if not isinstance(vals2, list) and isinstance(data2, dict):
                    vals2 = data2.get("values")
                col2 = vals2[0] if isinstance(vals2, list) and vals2 and isinstance(vals2[0], list) else []
                return len(col2) + 1
            except Exception:
                return 1
        except Exception:
            return 1

    def _set(row: list[Any], col: str, value: Any) -> None:
        j = idx.get(str(col or "").strip().lower())
        if j is None:
            return
        while len(row) <= j:
            row.append("")
        row[j] = value

    memo_id = await _next_memo_id()
    row: list[Any] = []
    _set(row, "id", memo_id)
    _set(row, "active", True if req.active is None else bool(req.active))
    _set(row, "group", str(req.group or "").strip())
    _set(row, "subject", str(req.subject or "").strip())
    _set(row, "memo", str(req.memo or "").strip())
    _set(row, "status", status)
    _set(row, "result", str(req.result or "").strip())
    _set(row, "date_time", now_dt)
    _set(row, "_created", now_dt)
    _set(row, "_updated", now_dt)

    tool_append = _pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
    try:
        res = await _mcp_tools_call(
            tool_append,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_a1}!A:Z",
                "values": [row],
                "value_input_option": "USER_ENTERED",
                "insert_data_option": "INSERT_ROWS",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"memo_append_failed: {type(e).__name__}: {e}")

    parsed = _mcp_text_json(res)

    # Best-effort semantic index in Weaviate (must never fail the memo append).
    try:
        if _weaviate_enabled():
            await _weaviate_upsert_memo_item(
                spreadsheet_id=spreadsheet_id,
                sheet_name=sheet_name,
                memo_id=int(memo_id),
                active=True if req.active is None else bool(req.active),
                group=str(req.group or "").strip(),
                status=status,
                subject=str(req.subject or "").strip(),
                memo=str(req.memo or "").strip(),
                result=str(req.result or "").strip(),
                date_time=now_dt,
                created_at=float(int(time.time())),
                updated_at=float(int(time.time())),
            )
    except Exception:
        pass

    try:
        memo_preview = str(req.memo or "").strip()
        if len(memo_preview) > 120:
            memo_preview = memo_preview[:120] + "..."
        await _sheets_logs_enqueue_http(
            typ="memo.add",
            text=memo_preview,
            msg={
                "group": str(req.group or "").strip(),
                "subject": str(req.subject or "").strip(),
                "status": str(req.status or "").strip(),
                "sheet": sheet_name,
            },
        )
    except Exception:
        pass
    return {"ok": True, "id": memo_id, "appended": 1, "sheet": sheet_name, "spreadsheet_id": spreadsheet_id, "raw": parsed}


@app.post("/memo/index/backfill")
@app.post("/jarvis/memo/index/backfill")
async def memo_index_backfill(
    req: MemoIndexBackfillRequest,
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    _require_api_token_if_configured(x_api_token)
    if not _weaviate_enabled():
        raise HTTPException(status_code=400, detail="weaviate_not_configured")

    sys_kv = _sys_kv_snapshot()
    spreadsheet_id, sheet_name = _memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
    if not spreadsheet_id or not sheet_name:
        raise HTTPException(status_code=400, detail="missing_memo_cfg")
    sheet_a1 = _sheet_name_to_a1(sheet_name, default="memo")

    limit = max(1, min(int(req.limit or 200), 2000))
    header = await _sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
    idx = _idx_from_header(header)
    if not idx:
        await _memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1)
        header = await _sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
        idx = _idx_from_header(header)
    if not idx:
        raise HTTPException(status_code=400, detail="memo_sheet_missing_header")

    tool_get = _pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
    res = await _mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_a1}!A2:J"})
    parsed = _mcp_text_json(res)
    data = parsed.get("data") if isinstance(parsed, dict) else None
    vals = parsed.get("values") if isinstance(parsed, dict) else None
    if not isinstance(vals, list) and isinstance(data, dict):
        vals = data.get("values")
    rows = vals if isinstance(vals, list) else []
    if not isinstance(rows, list):
        rows = []

    def _cell(row: list[Any], col: str) -> str:
        j = idx.get(str(col or "").strip().lower())
        if j is None or j < 0 or j >= len(row):
            return ""
        return str(row[j] or "")

    indexed = 0
    skipped = 0
    errors = 0
    error_samples: list[str] = []
    for r in rows[-limit:]:
        if not isinstance(r, list):
            continue
        try:
            mid_raw = str(_cell(r, "id") or "").strip()
            try:
                mid = int(float(mid_raw)) if mid_raw else 0
            except Exception:
                mid = 0
            if mid <= 0:
                skipped += 1
                continue
            await _weaviate_upsert_memo_item(
                spreadsheet_id=spreadsheet_id,
                sheet_name=sheet_name,
                memo_id=mid,
                active=str(_cell(r, "active") or "").strip().lower() not in {"false", "0", "no"},
                group=_cell(r, "group"),
                status=_cell(r, "status"),
                subject=_cell(r, "subject"),
                memo=_cell(r, "memo"),
                result=_cell(r, "result"),
                date_time=_cell(r, "date_time"),
            )
            indexed += 1
        except Exception as e:
            errors += 1
            if len(error_samples) < 8:
                try:
                    error_samples.append(f"{type(e).__name__}: {e}")
                except Exception:
                    error_samples.append("index_error")

    return {
        "ok": True,
        "spreadsheet_id": spreadsheet_id,
        "sheet": sheet_name,
        "indexed": indexed,
        "skipped": skipped,
        "errors": errors,
        "error_samples": error_samples,
    }


@app.get("/memo/related")
@app.get("/jarvis/memo/related")
async def memo_related(
    q: Optional[str] = None,
    k: int = 30,
    group: Optional[str] = None,
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    _require_api_token_if_configured(x_api_token)
    if not _weaviate_enabled():
        raise HTTPException(status_code=400, detail="weaviate_not_configured")
    qq = str(q or "").strip()
    items = await _weaviate_query_related_memos(q=qq, k=int(k), group=str(group or "").strip() or None)
    return {"ok": True, "q": qq, "k": int(k), "group": str(group or "").strip() or None, "items": items}


@app.post("/memo/summarize_related")
@app.post("/jarvis/memo/summarize_related")
async def memo_summarize_related(
    req: MemoSummarizeRelatedRequest,
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    _require_api_token_if_configured(x_api_token)
    if not _weaviate_enabled():
        raise HTTPException(status_code=400, detail="weaviate_not_configured")
    q = str(req.q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="missing_q")
    k = max(1, min(int(req.k or 30), 200))
    group = str(req.group or "").strip() or None
    items = await _weaviate_query_related_memos(q=q, k=k, group=group)

    style = str(req.style or "timeline").strip().lower() or "timeline"
    system_instruction = (
        "You summarize memo entries for an operator. "
        "Return concise markdown with: Summary, Key points, Open questions, Next actions."
    )
    prompt = {
        "style": style,
        "query": q,
        "memos": [
            {
                "id": it.get("memo_id"),
                "group": it.get("group"),
                "subject": it.get("subject"),
                "status": it.get("status"),
                "date_time": it.get("date_time"),
                "memo": it.get("memo"),
                "result": it.get("result"),
                "distance": (it.get("_additional") or {}).get("distance") if isinstance(it.get("_additional"), dict) else None,
            }
            for it in items
            if isinstance(it, dict)
        ],
    }
    used_ids = [int(float(it.get("memo_id"))) for it in items if isinstance(it, dict) and it.get("memo_id") is not None]
    try:
        txt = await _gemini_summarize_text(system_instruction=system_instruction, prompt=json.dumps(prompt, ensure_ascii=False))
        return {"ok": True, "q": q, "k": k, "group": group, "style": style, "used_memo_ids": used_ids, "summary_markdown": txt}
    except HTTPException as e:
        # Don't hard-fail the endpoint if Gemini quota/billing blocks generation.
        return {
            "ok": True,
            "q": q,
            "k": k,
            "group": group,
            "style": style,
            "used_memo_ids": used_ids,
            "summary_markdown": "",
            "summary_error": getattr(e, "detail", str(e)),
        }


@app.post("/memo/relate")
@app.post("/jarvis/memo/relate")
async def memo_relate(
    req: MemoRelateRequest,
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    _require_api_token_if_configured(x_api_token)
    if not _weaviate_enabled():
        raise HTTPException(status_code=400, detail="weaviate_not_configured")
    q = str(req.q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="missing_q")
    k = max(1, min(int(req.k or 50), 200))
    group = str(req.group or "").strip() or None
    items = await _weaviate_query_related_memos(q=q, k=k, group=group)

    system_instruction = (
        "You are an operations analyst. "
        "Given a list of memo entries, suggest clusters and relations. "
        "Return ONLY valid JSON with keys: clusters, links. "
        "clusters: list of {cluster_id,label,memo_ids,rationale}. "
        "links: list of {from_id,to_id,relation,confidence,why}."
    )
    payload = {
        "query": q,
        "memos": [
            {
                "id": it.get("memo_id"),
                "group": it.get("group"),
                "subject": it.get("subject"),
                "status": it.get("status"),
                "date_time": it.get("date_time"),
                "memo": it.get("memo"),
                "result": it.get("result"),
            }
            for it in items
            if isinstance(it, dict)
        ],
    }
    try:
        txt = await _gemini_summarize_text(system_instruction=system_instruction, prompt=json.dumps(payload, ensure_ascii=False))
        parsed: Any = None
        try:
            parsed = json.loads(txt)
        except Exception:
            parsed = {"raw": txt}
        return {"ok": True, "q": q, "k": k, "group": group, "result": parsed, "items": items}
    except HTTPException as e:
        return {"ok": True, "q": q, "k": k, "group": group, "result": {"error": getattr(e, "detail", str(e))}, "items": items}

@app.post("/jarvis/sys_kv/set")
async def sys_kv_set(req: SysKvSetRequest, x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token")) -> dict[str, Any]:
    _require_api_token_if_configured(x_api_token)

    sys_kv = _sys_kv_snapshot()
    enabled_raw = str(sys_kv.get("sys_kv.write.enabled") or "").strip() if isinstance(sys_kv, dict) else ""
    if not enabled_raw:
        try:
            fresh = await _load_sys_kv_from_sheet()
            if isinstance(fresh, dict) and fresh:
                sys_kv = fresh
                enabled_raw = str(fresh.get("sys_kv.write.enabled") or "").strip()
                try:
                    _set_cached_sys_kv_only(dict(fresh))
                except Exception:
                    pass
        except Exception:
            pass
    if not enabled_raw:
        raise HTTPException(
            status_code=400,
            detail={"error": "sys_kv_write_disabled", "detail": "Missing sys sheet key sys_kv.write.enabled (default disabled)"},
        )
    try:
        if not _parse_bool_cell(enabled_raw):
            raise HTTPException(
                status_code=400,
                detail={"error": "sys_kv_write_disabled", "detail": "Enable via sys sheet key sys_kv.write.enabled=true"},
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail={"error": "sys_kv_write_disabled", "detail": "Invalid sys_kv.write.enabled"})

    k = str(req.key or "").strip()
    v = str(req.value or "").strip()
    if not k:
        raise HTTPException(status_code=400, detail={"error": "missing_key"})
    dry_run = bool(req.dry_run is True)
    result = await _sys_kv_upsert_sheet(key=k, value=v, dry_run=dry_run)
    if not isinstance(result, dict) or not result.get("ok"):
        raise HTTPException(status_code=500, detail={"error": "sys_kv_set_failed", "detail": result})
    try:
        fresh = dict(sys_kv) if isinstance(sys_kv, dict) else {}
        fresh[k] = v
        _set_cached_sys_kv_only(fresh)
    except Exception:
        pass
    return {"ok": True, "key": k, "value": v, "dry_run": dry_run, "sys_kv_set": result}


@app.post("/sys_kv/bootstrap/google_gates")
@app.post("/jarvis/sys_kv/bootstrap/google_gates")
async def sys_kv_bootstrap_google_gates(
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    _require_api_token_if_configured(x_api_token)

    keys: list[tuple[str, str]] = [
        ("google.sheets.enabled", "true"),
        ("google.calendar.enabled", "false"),
        ("google.tasks.enabled", "false"),
        ("gmail.enabled", "false"),
    ]

    upserts: list[dict[str, Any]] = []
    for k, v in keys:
        try:
            upserts.append(await _sys_kv_upsert_sheet(key=k, value=v, dry_run=False))
        except Exception as e:
            upserts.append({"ok": False, "key": k, "error": f"{type(e).__name__}: {e}"})

    checkbox_result: Any = None
    try:
        spreadsheet_id = _system_spreadsheet_id()
        sys_sheet = _system_sheet_name()
        if spreadsheet_id and sys_sheet:
            tool_get = _pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
            res = await _mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sys_sheet}!A:Z"})
            parsed = _mcp_text_json(res)
            values = parsed.get("values") if isinstance(parsed, dict) else None
            if not isinstance(values, list) or not values:
                data = parsed.get("data") if isinstance(parsed, dict) else None
                if isinstance(data, dict):
                    values = data.get("values")

            tool_meta = _pick_sheets_tool_name("google_sheets_get_spreadsheet", "google_sheets_get_spreadsheet")
            meta_res = await _mcp_tools_call(tool_meta, {"spreadsheet_id": spreadsheet_id})
            meta_parsed = _mcp_text_json(meta_res)
            meta_data = meta_parsed.get("data") if isinstance(meta_parsed, dict) else None
            if not isinstance(meta_data, dict):
                meta_data = meta_parsed

            sheet_id: Optional[int] = None
            sheets = meta_data.get("sheets") if isinstance(meta_data, dict) else None
            if isinstance(sheets, list):
                for s in sheets:
                    props = s.get("properties") if isinstance(s, dict) else None
                    title = str(props.get("title") or "") if isinstance(props, dict) else ""
                    if title.strip() == sys_sheet:
                        try:
                            sheet_id = int(props.get("sheetId"))
                        except Exception:
                            sheet_id = None
                        break

            if isinstance(values, list) and sheet_id is not None:
                header = values[0] if values and isinstance(values[0], list) else []
                header_lower = [str(c or "").strip().lower() for c in header] if isinstance(header, list) else []
                key_col = None
                val_col = None
                for j, name in enumerate(header_lower):
                    if name == "key" and key_col is None:
                        key_col = int(j)
                    if name == "value" and val_col is None:
                        val_col = int(j)
                if key_col is None:
                    key_col = 0
                if val_col is None:
                    val_col = 1

                targets: list[dict[str, int]] = []
                desired_keys = {k for k, _ in keys}
                for i, row in enumerate(values, start=1):
                    if i == 1:
                        continue
                    if not isinstance(row, list) or len(row) <= key_col:
                        continue
                    rk = str(row[key_col] or "").strip()
                    if rk in desired_keys:
                        targets.append({"row": i - 1, "col": int(val_col)})

                if targets:
                    tool_bu = await _resolve_mcp_tool_name("google_sheets_batch_update", fallback="google_sheets_batch_update")
                    requests: list[dict[str, Any]] = []
                    for t in targets:
                        r0 = int(t["row"])
                        c0 = int(t["col"])
                        requests.append(
                            {
                                "setDataValidation": {
                                    "range": {
                                        "sheetId": int(sheet_id),
                                        "startRowIndex": r0,
                                        "endRowIndex": r0 + 1,
                                        "startColumnIndex": c0,
                                        "endColumnIndex": c0 + 1,
                                    },
                                    "rule": {
                                        "condition": {"type": "BOOLEAN"},
                                        "showCustomUi": True,
                                    },
                                }
                            }
                        )
                    checkbox_result = await _mcp_tools_call(tool_bu, {"spreadsheet_id": spreadsheet_id, "requests": requests})
    except Exception as e:
        checkbox_result = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    return {"ok": True, "upserts": upserts, "checkbox": _mcp_text_json(checkbox_result) if checkbox_result is not None else None}


@app.post("/memory/set")
@app.post("/jarvis/memory/set")
async def memory_set(req: MemorySetRequest, x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token")) -> dict[str, Any]:
    _require_api_token_if_configured(x_api_token)

    sys_kv = _sys_kv_snapshot()
    if not isinstance(sys_kv, dict) or "memory.write.enabled" not in sys_kv:
        try:
            class _DummyWS:
                def __init__(self) -> None:
                    from types import SimpleNamespace

                    self.state = SimpleNamespace()

            await _load_ws_system_kv(_DummyWS())
        except Exception:
            pass
        sys_kv = _sys_kv_snapshot()
        if not isinstance(sys_kv, dict) or "memory.write.enabled" not in sys_kv:
            raise HTTPException(status_code=400, detail={"error": "missing_sys_kv_key", "key": "memory.write.enabled"})
    if not _sys_kv_bool(sys_kv, "memory.write.enabled", default=False):
        raise HTTPException(status_code=400, detail={"error": "memory_write_disabled"})

    k = str(req.key or "").strip()
    v = str(req.value or "").strip()
    if not k:
        raise HTTPException(status_code=400, detail={"error": "missing_key"})

    scope = str(req.scope or "global").strip() or "global"
    priority = _safe_int(req.priority, default=0)
    enabled = bool(req.enabled is True)

    class _DummyWS2:
        def __init__(self) -> None:
            from types import SimpleNamespace

            self.state = SimpleNamespace()

    ws = _DummyWS2()
    try:
        cached = _get_cached_sheet_memory()
        if isinstance(cached, dict):
            _apply_cached_sheet_memory_to_ws(ws, cached)
    except Exception:
        pass

    try:
        await _load_ws_sheet_memory(ws)
    except Exception:
        pass

    result = await _memory_sheet_upsert(
        ws,
        key=k,
        value=v,
        scope=scope,
        priority=int(priority),
        enabled=enabled,
        source="http.memory_set",
    )
    if not isinstance(result, dict) or not result.get("ok"):
        raise HTTPException(status_code=500, detail={"error": "memory_set_failed", "detail": result})

    try:
        _clear_sheet_caches()
    except Exception:
        pass

    return {"ok": True, "key": k, "value": v, "scope": scope, "priority": int(priority), "enabled": enabled, "memory_set": result}


@app.get("/logs/ui/today")
@app.get("/jarvis/logs/ui/today")
def logs_ui_today(max_bytes: int = 200000, max_lines: Optional[int] = None) -> dict[str, Any]:
    path = _ui_log_daily_path()
    sys_kv = _sys_kv_snapshot()
    if max_lines is None:
        try:
            raw = str(sys_kv.get("logs.ui.max_lines") or "").strip() if isinstance(sys_kv, dict) else ""
            if raw:
                max_lines = _safe_int(raw, default=100)
        except Exception:
            max_lines = None
    if max_lines is None:
        max_lines = 100
    return {
        "ok": True,
        "date": _today_ymd(),
        "path": path,
        "text": _read_text_file_tail_lines(path, max_lines=int(max_lines), max_bytes=max(1000, int(max_bytes))),
    }


@app.get("/logs/ws/today")
@app.get("/jarvis/logs/ws/today")
def logs_ws_today(max_bytes: int = 200000, max_lines: Optional[int] = None) -> dict[str, Any]:
    path = _ws_record_daily_path()
    sys_kv = _sys_kv_snapshot()
    if max_lines is None:
        try:
            raw = str(sys_kv.get("logs.ws.max_lines") or "").strip() if isinstance(sys_kv, dict) else ""
            if raw:
                max_lines = _safe_int(raw, default=100)
        except Exception:
            max_lines = None
    if max_lines is None:
        max_lines = 100
    return {
        "ok": True,
        "date": _today_ymd(),
        "path": path,
        "text": _read_text_file_tail_lines(path, max_lines=int(max_lines), max_bytes=max(1000, int(max_bytes))),
    }


WEB_FETCHER_BASE_URL = str(os.getenv("WEB_FETCHER_BASE_URL") or "http://web-fetcher:8028").strip().rstrip("/")

MCP_BASE_URL = str(os.getenv("MCP_BASE_URL") or "http://mcp-bundle:3050").strip() or "http://mcp-bundle:3050"
MCP_PLAYWRIGHT_BASE_URL = str(os.getenv("MCP_PLAYWRIGHT_BASE_URL") or "").strip()
AIM_MCP_BASE_URL = str(os.getenv("AIM_MCP_BASE_URL") or "").strip().rstrip("/")

WEAVIATE_URL = str(os.getenv("WEAVIATE_URL") or "").strip().rstrip("/")
GEMINI_EMBEDDING_MODEL = str(os.getenv("GEMINI_EMBEDDING_MODEL") or "text-embedding-004").strip() or "text-embedding-004"

JARVIS_TOOL_ALLOWLIST = [
    t.strip()
    for t in str(os.getenv("JARVIS_TOOL_ALLOWLIST") or "").split(",")
    if t.strip()
]
JARVIS_EMBED_CACHE_MAX = max(0, int(os.getenv("JARVIS_EMBED_CACHE_MAX") or "512"))

IMAGEN_MODEL_DEFAULT = str(os.getenv("JARVIS_IMAGEN_MODEL") or "imagen-4.0-generate-001").strip() or "imagen-4.0-generate-001"
IMAGEN_ALLOWED_MODELS = [
    m.strip()
    for m in str(
        os.getenv("JARVIS_IMAGEN_ALLOWED_MODELS")
        or "imagen-4.0-generate-001,imagen-4.0-ultra-generate-001,imagen-4.0-fast-generate-001"
    ).split(",")
    if m.strip()
]
IMAGEN_ASSETS_DIR = str(os.getenv("JARVIS_IMAGEN_ASSETS_DIR") or "/app/imagen_assets").strip() or "/app/imagen_assets"

IMAGE_MODEL_DEFAULT = str(os.getenv("JARVIS_IMAGE_MODEL") or "gemini-3.1-flash-image-preview").strip() or "gemini-3.1-flash-image-preview"
IMAGE_ALLOWED_MODELS = [
    m.strip()
    for m in str(os.getenv("JARVIS_IMAGE_ALLOWED_MODELS") or "gemini-3.1-flash-image-preview").split(",")
    if m.strip()
]


SESSION_DB_PATH = os.getenv("JARVIS_SESSION_DB", "/app/jarvis_sessions.sqlite")

CARS_DATA_DIR = str(os.getenv("JARVIS_CARS_DATA_DIR") or "/app/assistance_data/cars").strip() or "/app/assistance_data/cars"
CARS_ORIGINALS_DIR = os.path.join(CARS_DATA_DIR, "originals")
CARS_PLATES_DIR = os.path.join(CARS_DATA_DIR, "plates")
CARS_CROPS_DIR = os.path.join(CARS_DATA_DIR, "cars")

AGENTS_DIR = str(os.getenv("JARVIS_AGENTS_DIR") or "/app/agents").strip() or "/app/agents"

DEFAULT_USER_ID = os.getenv("DEFAULT_USER_ID", "default")
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Bangkok")

MORNING_BRIEF_HOUR = int(str(os.getenv("JARVIS_MORNING_BRIEF_HOUR") or "8").strip() or "8")
MORNING_BRIEF_MINUTE = int(str(os.getenv("JARVIS_MORNING_BRIEF_MINUTE") or "0").strip() or "0")

AGENT_CONTINUE_WINDOW_SECONDS = int(str(os.getenv("JARVIS_AGENT_CONTINUE_WINDOW_SECONDS") or "120").strip() or "120")

_ws_by_user: dict[str, set[WebSocket]] = {}

# Map sticky session_id -> last active websocket for that session.
# This is used so Gemini tool calls can reach back into the correct session state.
_SESSION_WS: dict[str, WebSocket] = {}



def _portainer_cfg(sys_kv: Any) -> dict[str, str]:
    def _get(k: str) -> str:
        if isinstance(sys_kv, dict):
            v = str(sys_kv.get(k) or "").strip()
            if v:
                return v
        return ""

    url = _get("portainer.url") or str(os.getenv("PORTAINER_URL") or "").strip()
    api_key = _get("portainer.token") or str(os.getenv("PORTAINER_TOKEN") or "").strip()
    endpoint_id = _get("portainer.endpoint_id") or str(os.getenv("PORTAINER_ENDPOINT_ID") or "").strip()
    stack_name = _get("portainer.stack_name") or str(os.getenv("PORTAINER_STACK_NAME") or "").strip()
    return {"url": url, "api_key": api_key, "endpoint_id": endpoint_id, "stack_name": stack_name}


async def _portainer_get_json(*, base_url: str, api_key: str, path: str) -> Any:
    url = str(base_url or "").rstrip("/") + str(path or "")
    if not api_key:
        raise HTTPException(status_code=500, detail="missing_portainer_token")
    headers = {"X-API-Key": api_key}
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(url, headers=headers)
        if res.status_code >= 400:
            raise HTTPException(status_code=res.status_code, detail={"portainer_http_error": res.text})
        try:
            return res.json()
        except Exception:
            raise HTTPException(status_code=502, detail="portainer_invalid_json")


def _iso_utc_from_unix_ts(ts: Any) -> str:
    try:
        v = int(ts)
        if v <= 0:
            return ""
        return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
    except Exception:
        return ""


async def _portainer_get_image_meta(*, sys_kv: Any, image_id: str) -> dict[str, Any]:
    cfg = _portainer_cfg(sys_kv)
    base_url = cfg.get("url") or ""
    api_key = cfg.get("api_key") or ""
    endpoint_id = cfg.get("endpoint_id") or ""
    if not base_url or not api_key or not endpoint_id:
        return {}
    image_id_norm = str(image_id or "").strip()
    if not image_id_norm:
        return {}
    try:
        return await _portainer_get_json(
            base_url=base_url,
            api_key=api_key,
            path=f"/api/endpoints/{endpoint_id}/docker/images/{image_id_norm}/json",
        )
    except Exception:
        return {}


def _infer_health_from_docker_status(status: str) -> str:
    s = str(status or "").lower()
    if "unhealthy" in s:
        return "unhealthy"
    if "healthy" in s:
        return "healthy"
    if "starting" in s:
        return "starting"
    return ""


def _infer_state_from_fields(state: Any, status: Any) -> str:
    s = str(state or "").strip().lower()
    if s:
        return s
    st = str(status or "").strip().lower()
    if st.startswith("up"):
        return "running"
    if st.startswith("exited"):
        return "exited"
    return ""


async def _portainer_list_stack_containers(*, sys_kv: Any) -> list[dict[str, Any]]:
    cfg = _portainer_cfg(sys_kv)
    base_url = cfg.get("url") or ""
    api_key = cfg.get("api_key") or ""
    endpoint_id = cfg.get("endpoint_id") or ""
    stack_name = cfg.get("stack_name") or ""

    if not base_url:
        raise HTTPException(status_code=500, detail={"missing_sys_kv_key": "portainer.url"})
    if not endpoint_id:
        raise HTTPException(status_code=500, detail={"missing_sys_kv_key": "portainer.endpoint_id"})
    if not stack_name:
        raise HTTPException(status_code=500, detail={"missing_sys_kv_key": "portainer.stack_name"})

    items = await _portainer_get_json(
        base_url=base_url,
        api_key=api_key,
        path=f"/api/endpoints/{endpoint_id}/docker/containers/json?all=1",
    )
    if not isinstance(items, list):
        return []

    out: list[dict[str, Any]] = []
    image_meta_cache: dict[str, dict[str, Any]] = {}
    for c in items:
        if not isinstance(c, dict):
            continue
        labels = c.get("Labels") if isinstance(c.get("Labels"), dict) else {}
        proj = str(labels.get("com.docker.compose.project") or "").strip()
        stack_ns = str(labels.get("com.docker.stack.namespace") or "").strip()
        if proj != stack_name and stack_ns != stack_name:
            continue

        svc = str(labels.get("com.docker.compose.service") or "").strip()
        names = c.get("Names") if isinstance(c.get("Names"), list) else []
        name0 = ""
        if names:
            try:
                name0 = str(names[0] or "").lstrip("/").strip()
            except Exception:
                name0 = ""
        display = svc or name0 or str(c.get("Id") or "")[:12]
        status = str(c.get("Status") or "")
        state = _infer_state_from_fields(c.get("State"), status)
        health = _infer_health_from_docker_status(status)

        image_tag = str(c.get("Image") or "").strip()
        image_id = str(c.get("ImageID") or "").strip()
        created_ts = c.get("Created")
        created_at = _iso_utc_from_unix_ts(created_ts)

        image_repo_digests: list[str] = []
        image_created_at = ""
        if image_id:
            meta = image_meta_cache.get(image_id)
            if meta is None:
                meta = await _portainer_get_image_meta(sys_kv=sys_kv, image_id=image_id)
                image_meta_cache[image_id] = meta if isinstance(meta, dict) else {}
                meta = image_meta_cache[image_id]
            if isinstance(meta, dict):
                rd = meta.get("RepoDigests")
                if isinstance(rd, list):
                    for it in rd:
                        s = str(it or "").strip()
                        if s:
                            image_repo_digests.append(s)
                image_created_at = str(meta.get("Created") or "").strip()

        image_repo_digest = ""
        if image_repo_digests:
            try:
                image_repo_digest = str(image_repo_digests[0] or "").strip()
            except Exception:
                image_repo_digest = ""

        out.append(
            {
                "name": display,
                "service": svc,
                "status": state or ("running" if status.lower().startswith("up") else ""),
                "health": health,
                "detail": status.strip(),
                "image": image_tag,
                "image_id": image_id,
                "created_at": created_at,
                "image_repo_digest": image_repo_digest,
                "image_repo_digests": image_repo_digests,
                "image_created_at": image_created_at,
            }
        )

    out.sort(key=lambda it: str(it.get("name") or ""))
    return out

# Reload System can be triggered by voice/STT and sometimes repeats quickly.
# Guard against overlapping runs (global) and repeated triggers (per-WS).
_reload_system_lock: asyncio.Lock = asyncio.Lock()
RELOAD_SYSTEM_DEBOUNCE_SECONDS = float(str(os.getenv("JARVIS_RELOAD_SYSTEM_DEBOUNCE_SECONDS") or "5").strip() or "5")

# Suppress duplicate initial status lines on rapid reconnect/double-connect.
_initial_sheet_status_last_sent: dict[str, float] = {}
_initial_sheet_status_lock: asyncio.Lock = asyncio.Lock()
INITIAL_SHEET_STATUS_DEDUPE_SECONDS = float(
    str(os.getenv("JARVIS_INITIAL_SHEET_STATUS_DEDUPE_SECONDS") or "5").strip() or "5"
)

_agent_defs: dict[str, dict[str, Any]] = {}

_agent_triggers: dict[str, list[str]] = {}

_weaviate_schema_ready: bool = False


class ImagenGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    model: Optional[str] = None
    aspect_ratio: Optional[str] = None
    image_size: Optional[str] = None
    number_of_images: int = 1
    person_generation: Optional[str] = None
    return_data_url: bool = True


class ImagenGenerateResponse(BaseModel):
    asset_id: str
    model: str
    mime_type: str
    sha256: str
    data_url: Optional[str] = None


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    model: Optional[str] = None
    aspect_ratio: Optional[str] = None
    image_size: Optional[str] = None
    return_data_url: bool = True


class ImageGenerateResponse(BaseModel):
    asset_id: str
    model: str
    mime_type: str
    sha256: str
    data_url: Optional[str] = None


class GemDemoRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    gem: Optional[str] = None
    model: Optional[str] = None


class GemDemoResponse(BaseModel):
    ok: bool = True
    gem: str
    model: str
    text: str


class SequentialSuggestRequest(BaseModel):
    task: dict[str, Any] = Field(default_factory=dict)
    completed_tasks: Optional[list[dict[str, Any]]] = None


class SequentialSuggestResponse(BaseModel):
    ok: bool = True
    next_step_text: Optional[str] = None
    next_step_index: Optional[int] = None
    template: Optional[list[str]] = None


class SequentialApplyRequest(BaseModel):
    notes: str = Field(default="")
    step_index: int = Field(ge=0)


class SequentialApplyResponse(BaseModel):
    ok: bool = True
    changed: bool
    notes: str


class SequentialApplyByTextRequest(BaseModel):
    notes: str = Field(default="")
    step_text: str = Field(default="")


class SequentialApplyByTextResponse(BaseModel):
    ok: bool = True
    changed: bool
    notes: str
    matched_step_index: Optional[int] = None


class SequentialApplyAllRequest(BaseModel):
    notes: str = Field(default="")


class SequentialApplyAllResponse(BaseModel):
    ok: bool = True
    changed: bool
    changed_count: int
    notes: str


class SequentialApplyAndSuggestRequest(BaseModel):
    mode: Literal["suggest", "index", "text", "all"] = Field(default="suggest")
    notes: str = Field(default="")
    step_index: Optional[int] = Field(default=None, ge=0)
    step_text: str = Field(default="")
    step_index_hint: Optional[int] = Field(default=None, ge=0)
    completed_tasks: Optional[list[dict[str, Any]]] = None


class SequentialApplyAndSuggestResponse(BaseModel):
    ok: bool = True
    mode: str
    notes: str
    changed: bool
    changed_count: Optional[int] = None
    matched_step_index: Optional[int] = None
    next_step_text: Optional[str] = None
    next_step_index: Optional[int] = None
    template: Optional[list[str]] = None


class GoogleTasksSequentialItem(BaseModel):
    task_id: str
    title: str
    status: str
    notes: str = ""
    next_step_text: Optional[str] = None
    next_step_index: Optional[int] = None


class GoogleTasksSequentialSummaryResponse(BaseModel):
    ok: bool = True
    tasklist_id: str
    tasklist_title: str
    tasks: list[GoogleTasksSequentialItem]
    template: Optional[list[str]] = None
    debug: Optional[dict[str, Any]] = None


class GoogleTasksCreateTaskRequest(BaseModel):
    tasklist_id: Optional[str] = None
    tasklist_title: Optional[str] = None
    title: str
    notes: str = ""
    due: Optional[str] = None
    confirm: bool = False


class GoogleTasksUpdateTaskRequest(BaseModel):
    tasklist_id: Optional[str] = None
    tasklist_title: Optional[str] = None
    task_id: str
    title: Optional[str] = None
    notes: Optional[str] = None
    due: Optional[str] = None
    status: Optional[str] = None
    confirm: bool = False


class GoogleTasksCompleteTaskRequest(BaseModel):
    tasklist_id: Optional[str] = None
    tasklist_title: Optional[str] = None
    task_id: str
    confirm: bool = False


class GoogleTasksDeleteTaskRequest(BaseModel):
    tasklist_id: Optional[str] = None
    tasklist_title: Optional[str] = None
    task_id: str
    confirm: bool = False


class GoogleTasksWriteResponse(BaseModel):
    ok: bool = True
    result: dict[str, Any]


class GoogleTasksUndoItem(BaseModel):
    undo_id: str
    created_at: int
    action: str
    tasklist_id: Optional[str] = None
    task_id: Optional[str] = None


class GoogleTasksUndoListResponse(BaseModel):
    ok: bool = True
    items: list[GoogleTasksUndoItem]


class GoogleTasksUndoLastRequest(BaseModel):
    n: int = 1
    confirm: bool = False


class GoogleTasksUndoResponse(BaseModel):
    ok: bool = True
    undone: int
    results: list[dict[str, Any]]


class GoogleCalendarUndoItem(BaseModel):
    undo_id: str
    created_at: int
    action: str
    event_id: Optional[str] = None


class GoogleCalendarUndoListResponse(BaseModel):
    ok: bool = True
    items: list[GoogleCalendarUndoItem]


class GoogleCalendarUndoLastRequest(BaseModel):
    n: int = 1
    confirm: bool = False


class GoogleCalendarUndoResponse(BaseModel):
    ok: bool = True
    undone: int
    results: list[dict[str, Any]]


def _classify_image_generation_error(message: str) -> Optional[dict[str, Any]]:
    msg = str(message or "").strip()
    low = msg.lower()
    if not low:
        return None

    if "only available on paid plans" in low or "upgrade your account" in low:
        return {
            "image_generation_unavailable": True,
            "reason": "paid_plan_required",
            "message": msg,
        }

    if "resource_exhausted" in low or "quota exceeded" in low or "exceeded your current quota" in low:
        return {
            "image_generation_unavailable": True,
            "reason": "quota_exhausted",
            "message": msg,
        }

    return None


def _looks_like_reminder_details_query(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    s = " ".join(raw.lower().split())
    if s in ("รายละเอียดแจ้งเตือน", "รายละเอียดการแจ้งเตือน", "ดูรายละเอียดแจ้งเตือน"):
        return True
    if s.startswith("รายละเอียด") and ("แจ้งเตือน" in s or "เตือน" in s):
        return True
    if "รายละเอียด" in s and ("แจ้งเตือน" in s or "เตือน" in s):
        return True
    if s in ("reminder details", "show reminder details", "reminder detail"):
        return True
    if "reminder" in s and "detail" in s:
        return True
    return False


async def _handle_reminder_details_query(ws: WebSocket, text: str) -> bool:
    if not _looks_like_reminder_details_query(text):
        return False

    rid = str(getattr(ws.state, "last_selected_reminder_id", "") or "").strip()
    if not rid:
        rid = str(getattr(ws.state, "last_reminder_id", "") or "").strip()
    if not rid:
        msg = "ยังไม่พบรายการแจ้งเตือนล่าสุด" if _text_is_thai(text) else "I couldn't find a recent reminder."
        try:
            await _ws_send_json(ws, {"type": "text", "text": msg})
        except Exception:
            pass
        return True

    local = _get_local_reminder_by_id(rid) or {}
    if not local:
        msg = "ไม่พบรายการแจ้งเตือนนี้แล้ว" if _text_is_thai(text) else "That reminder wasn't found."
        try:
            await _ws_send_json(ws, {"type": "text", "text": msg})
        except Exception:
            pass
        return True

    try:
        await _ws_send_json(ws, {"type": "reminder_detail", "reminder": local, "instance_id": INSTANCE_ID})
    except Exception:
        pass

    title = str(local.get("title") or "Reminder").strip() or "Reminder"
    due_at = local.get("due_at")
    notify_at = local.get("notify_at")
    tz_name = str(local.get("timezone") or DEFAULT_TIMEZONE)
    status = str(local.get("status") or "pending")

    local_time_str: Optional[str] = None
    if due_at is not None:
        try:
            tz = ZoneInfo(tz_name)
            dt = datetime.fromtimestamp(int(due_at), tz=timezone.utc).astimezone(tz)
            local_time_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            local_time_str = None

    if _text_is_thai(text):
        when_line = f"เวลา: {local_time_str}" if local_time_str else "เวลา: ยังไม่ตั้งเวลา"
        msg = "\n".join(
            [
                f"รายละเอียดแจ้งเตือน: {title}",
                when_line,
                f"สถานะ: {status}",
            ]
        )
    else:
        when_line = f"Time: {local_time_str}" if local_time_str else "Time: not set"
        msg = "\n".join(
            [
                f"Reminder details: {title}",
                when_line,
                f"Status: {status}",
            ]
        )
    try:
        await _ws_send_json(ws, {"type": "text", "text": msg})
    except Exception:
        pass
    return True


async def _handle_pending_reminder_modify(ws: WebSocket, text: str) -> bool:
    pending = getattr(ws.state, "pending_reminder_modify", None)
    if not isinstance(pending, dict):
        return False
    rid = str(pending.get("reminder_id") or "").strip()
    if not rid:
        try:
            ws.state.pending_reminder_modify = None
        except Exception:
            pass
        return False

    raw = str(text or "").strip()
    s = " ".join(raw.split())
    if not s:
        return False

    # If user repeats the command, let the explicit handler take it.
    if s.startswith("เปลี่ยนเวลา") or s.startswith("เปลี่ยนเป็น") or s.startswith("เปลี่ยน เป็น"):
        return False

    try:
        ws.state.pending_reminder_modify = None
    except Exception:
        pass

    try:
        ws.state.last_reminder_id = rid
    except Exception:
        pass

    # Treat the message as the new time.
    return await _handle_last_reminder_modify(ws, f"เปลี่ยนเป็น {s}")


async def _handle_pending_reminder_set_time(ws: WebSocket, text: str) -> bool:
    pending = getattr(ws.state, "pending_reminder_set_time", None)
    if not isinstance(pending, dict):
        return False
    pending_title = str(pending.get("title") or "").strip()
    pending_source_text = str(pending.get("source_text") or "").strip()

    raw = str(text or "").strip()
    s = " ".join(raw.split())
    if not s:
        return False

    # If user sends another command, do not consume it here.
    if s.startswith("เปลี่ยนเวลา") or s.startswith("เปลี่ยนเป็น") or s.startswith("เปลี่ยน เป็น"):
        return False

    tz = _get_user_timezone(DEFAULT_USER_ID)
    now = datetime.now(tz=timezone.utc)
    due_at_utc, local_iso = _parse_time_from_text(s, now, tz)
    if due_at_utc is None:
        msg = "ฉันอ่านเวลาไม่ออก ลองใหม่ เช่น วันนี้ 17:00 หรือ พรุ่งนี้ 09:00"
        try:
            await _ws_send_json(ws, {"type": "text", "text": msg})
        except Exception:
            pass
        try:
            await _live_say(ws, msg)
        except Exception:
            pass
        return True

    try:
        ws.state.pending_reminder_set_time = None
    except Exception:
        pass

    title = pending_title or "Reminder"
    source_text = pending_source_text or s
    try:
        cal = await _google_calendar_create_reminder_event(title=title, due_at_utc=due_at_utc, tz=tz, source_text=source_text)
    except Exception as e:
        msg = f"สร้างการแจ้งเตือนไม่สำเร็จ: {e}"
        try:
            await _ws_send_json(ws, {"type": "text", "text": msg})
        except Exception:
            pass
        try:
            await _live_say(ws, msg)
        except Exception:
            pass
        return True

    await _ws_send_json(
        ws,
        {
            "type": "reminder_setup",
            "title": title,
            "reminder_id": None,
            "result": {"ok": True, "calendar": cal, "local_time": local_iso, "timezone": tz.key},
            "instance_id": INSTANCE_ID,
        },
    )
    msg = f"โอเค สร้างการแจ้งเตือนในปฏิทินแล้ว: {title} เป็น {local_iso or s}"
    try:
        await _ws_send_json(ws, {"type": "text", "text": msg})
    except Exception:
        pass
    try:
        await _live_say(ws, msg)
    except Exception:
        pass
    return True


def _imagen_allowed_model(model: Optional[str]) -> str:
    m = (str(model or "").strip() or IMAGEN_MODEL_DEFAULT).strip()
    if m not in IMAGEN_ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail={"imagen_model_not_allowed": m, "allowed": IMAGEN_ALLOWED_MODELS})
    return m


def _image_allowed_model(model: Optional[str]) -> str:
    m = (str(model or "").strip() or IMAGE_MODEL_DEFAULT).strip()
    if m not in IMAGE_ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail={"image_model_not_allowed": m, "allowed": IMAGE_ALLOWED_MODELS})
    return m


def _extract_inline_image(res: Any) -> tuple[bytes, str]:
    candidates = getattr(res, "candidates", None) or []
    cand0 = candidates[0] if isinstance(candidates, list) and candidates else None
    content = getattr(cand0, "content", None) if cand0 is not None else None
    parts = getattr(content, "parts", None) if content is not None else None
    for part in parts or []:
        inline_data = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
        if not inline_data:
            continue
        mime_type = getattr(inline_data, "mime_type", None) or getattr(inline_data, "mimeType", None) or "image/png"
        data = getattr(inline_data, "data", None)
        if isinstance(data, (bytes, bytearray)):
            return (bytes(data), str(mime_type))
        if isinstance(data, str) and data:
            try:
                return (base64.b64decode(data), str(mime_type))
            except Exception:
                return (data.encode("utf-8"), str(mime_type))
        try:
            as_bytes = bytes(data)
            if as_bytes:
                return (as_bytes, str(mime_type))
        except Exception:
            pass
    raise HTTPException(status_code=502, detail="imagen_no_inline_image")


def _extract_generated_image(res: Any) -> tuple[bytes, str]:
    generated = getattr(res, "generated_images", None) or getattr(res, "generatedImages", None) or []
    if isinstance(generated, list) and generated:
        gi0 = generated[0]
        img = getattr(gi0, "image", None) or gi0
        mime_type = getattr(img, "mime_type", None) or getattr(img, "mimeType", None) or "image/png"
        data = (
            getattr(img, "image_bytes", None)
            or getattr(img, "imageBytes", None)
            or getattr(img, "bytes", None)
            or getattr(img, "data", None)
        )
        if isinstance(data, (bytes, bytearray)):
            return (bytes(data), str(mime_type))
        if isinstance(data, str) and data:
            try:
                return (base64.b64decode(data), str(mime_type))
            except Exception:
                return (data.encode("utf-8"), str(mime_type))
        try:
            as_bytes = bytes(data)
            if as_bytes:
                return (as_bytes, str(mime_type))
        except Exception:
            pass
    raise HTTPException(status_code=502, detail="imagen_no_generated_images")


def _ensure_imagen_assets_dir() -> None:
    os.makedirs(IMAGEN_ASSETS_DIR, exist_ok=True)


def _ensure_cars_data_dirs() -> None:
    os.makedirs(CARS_DATA_DIR, exist_ok=True)
    os.makedirs(CARS_ORIGINALS_DIR, exist_ok=True)
    os.makedirs(CARS_PLATES_DIR, exist_ok=True)
    os.makedirs(CARS_CROPS_DIR, exist_ok=True)


def _normalize_th_plate(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    s = s.replace(" ", "").replace("-", "").replace(".", "")
    s = re.sub(r"[\\/]+", "_", s)
    s = s.strip("_")
    return s


def _guess_image_ext(mime_type: str) -> str:
    mt = str(mime_type or "").lower().strip()
    if "png" in mt:
        return ".png"
    if "webp" in mt:
        return ".webp"
    return ".jpg"


def _write_json_atomic(path: str, obj: Any) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _load_json_if_exists(path: str) -> Optional[dict[str, Any]]:
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _clip_box(box: dict[str, Any], w: int, h: int) -> Optional[tuple[int, int, int, int]]:
    try:
        x1 = int(float(box.get("x1")))
        y1 = int(float(box.get("y1")))
        x2 = int(float(box.get("x2")))
        y2 = int(float(box.get("y2")))
    except Exception:
        return None
    x1 = max(0, min(w - 1, x1))
    y1 = max(0, min(h - 1, y1))
    x2 = max(0, min(w, x2))
    y2 = max(0, min(h, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _expand_box(x1: int, y1: int, x2: int, y2: int, w: int, h: int, pad: float) -> tuple[int, int, int, int]:
    dx = int((x2 - x1) * pad)
    dy = int((y2 - y1) * pad)
    nx1 = max(0, x1 - dx)
    ny1 = max(0, y1 - dy)
    nx2 = min(w, x2 + dx)
    ny2 = min(h, y2 + dy)
    return (nx1, ny1, nx2, ny2)


async def _detect_th_plates_via_gemini(image_bytes: bytes, mime_type: str) -> dict[str, Any]:
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return {"ok": False, "error": "missing_api_key"}

    model = _image_allowed_model(os.getenv("JARVIS_IMAGE_MODEL") or IMAGE_MODEL_DEFAULT)
    client = genai.Client(api_key=api_key)

    prompt = (
        "You are given a single exterior photo that may contain multiple cars. "
        "Detect Thailand license plates that are clearly readable. Ignore cars without a visible plate. "
        "Return ONLY valid JSON in this exact schema:\n"
        "{\n"
        "  \"plates\": [\n"
        "    {\n"
        "      \"plate\": \"<string>\",\n"
        "      \"confidence\": <number 0..1>,\n"
        "      \"bbox_plate\": {\"x1\":<int>,\"y1\":<int>,\"x2\":<int>,\"y2\":<int>}\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "Coordinates must be pixel coordinates in the original image, with (0,0) at top-left."
    )

    try:
        contents = [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": str(mime_type or "image/jpeg"), "data": image_bytes}},
                ],
            }
        ]
        res = await client.aio.models.generate_content(model=model, contents=contents)
        txt = getattr(res, "text", None)
        if not txt:
            try:
                txt = str(res)
            except Exception:
                txt = ""
        txt = str(txt or "").strip()
        data = json.loads(txt)
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid_response"}
        plates = data.get("plates")
        if not isinstance(plates, list):
            plates = []
        return {"ok": True, "plates": plates}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _handle_cars_ingest_image(ws: WebSocket, msg: dict[str, Any]) -> None:
    _ensure_cars_data_dirs()

    data_b64 = str(msg.get("data") or "")
    mime_type = str(msg.get("mimeType") or msg.get("mime_type") or "image/jpeg")
    request_id = str(msg.get("request_id") or uuid.uuid4().hex)
    if not data_b64:
        await ws.send_json({"type": "cars_ingest_result", "request_id": request_id, "ok": False, "error": "missing_data"})
        return

    try:
        image_bytes = base64.b64decode(data_b64)
    except Exception:
        await ws.send_json({"type": "cars_ingest_result", "request_id": request_id, "ok": False, "error": "invalid_base64"})
        return

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    ext = _guess_image_ext(mime_type)
    upload_id = uuid.uuid4().hex[:8]
    original_name = f"{ts}_upload_{upload_id}{ext}"
    original_path = os.path.join(CARS_ORIGINALS_DIR, original_name)
    with open(original_path, "wb") as f:
        f.write(image_bytes)

    detected = await _detect_th_plates_via_gemini(image_bytes=image_bytes, mime_type=mime_type)
    plates_in: list[dict[str, Any]] = []
    if bool(detected.get("ok")):
        raw_plates = detected.get("plates")
        if isinstance(raw_plates, list):
            plates_in = [p for p in raw_plates if isinstance(p, dict)]

    results: list[dict[str, Any]] = []
    crops_written = 0
    try:
        img = Image.open(BytesIO(image_bytes))
        img.load()
    except Exception:
        img = None

    for idx, p in enumerate(plates_in, start=1):
        raw_plate = str(p.get("plate") or "")
        plate = _normalize_th_plate(raw_plate)
        if not plate:
            continue

        conf = p.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else None
        except Exception:
            conf_f = None

        bbox = p.get("bbox_plate")
        plate_crop_path: Optional[str] = None
        car_crop_path: Optional[str] = None

        if img is not None and isinstance(bbox, dict):
            w, h = img.size
            clipped = _clip_box(bbox, w=w, h=h)
            if clipped is not None:
                x1, y1, x2, y2 = clipped
                plate_crop = img.crop((x1, y1, x2, y2))
                plate_crop_name = f"{plate}_{ts}_{idx:02d}{ext}"
                plate_crop_path = os.path.join(CARS_PLATES_DIR, plate_crop_name)
                try:
                    plate_crop.save(plate_crop_path)
                    crops_written += 1
                except Exception:
                    plate_crop_path = None

                cx1, cy1, cx2, cy2 = _expand_box(x1, y1, x2, y2, w=w, h=h, pad=2.5)
                car_crop = img.crop((cx1, cy1, cx2, cy2))
                car_crop_name = f"{plate}_{ts}_{idx:02d}{ext}"
                car_crop_path = os.path.join(CARS_CROPS_DIR, car_crop_name)
                try:
                    car_crop.save(car_crop_path)
                    crops_written += 1
                except Exception:
                    car_crop_path = None

        json_path = os.path.join(CARS_DATA_DIR, f"{plate}.json")
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        existing = _load_json_if_exists(json_path)
        if existing is None:
            record: dict[str, Any] = {
                "plate": plate,
                "plate_normalized": plate,
                "country": "TH",
                "created_at": now_iso,
                "updated_at": now_iso,
                "attributes": {"make": None, "model": None, "color": None, "body_type": None},
                "observations": [],
            }
        else:
            record = existing
            record["updated_at"] = now_iso

        obs: dict[str, Any] = {
            "timestamp": now_iso,
            "source_image": str(original_path),
            "plate_crop": str(plate_crop_path) if plate_crop_path else None,
            "car_crop": str(car_crop_path) if car_crop_path else None,
            "confidence": {"plate": conf_f},
        }
        observations = record.get("observations")
        if not isinstance(observations, list):
            observations = []
        observations.append(obs)
        record["observations"] = observations

        _write_json_atomic(json_path, record)
        results.append(
            {
                "plate": plate,
                "json_path": json_path,
                "plate_crop": plate_crop_path,
                "car_crop": car_crop_path,
                "confidence": conf_f,
            }
        )

    await ws.send_json(
        {
            "type": "cars_ingest_result",
            "request_id": request_id,
            "ok": True,
            "original_path": original_path,
            "detector": detected,
            "items": results,
            "crops_written": crops_written,
            "instance_id": INSTANCE_ID,
        }
    )


def _asset_paths(asset_id: str) -> tuple[str, str]:
    safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(asset_id))
    blob_path = os.path.join(IMAGEN_ASSETS_DIR, f"{safe_id}.bin")
    meta_path = os.path.join(IMAGEN_ASSETS_DIR, f"{safe_id}.json")
    return blob_path, meta_path


@app.post("/imagen/generate", response_model=ImagenGenerateResponse)
async def imagen_generate(req: ImagenGenerateRequest) -> ImagenGenerateResponse:
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="missing_api_key")
    model = _imagen_allowed_model(req.model)

    _ensure_imagen_assets_dir()
    client = genai.Client(api_key=api_key)
    is_imagen = model.startswith("imagen-")
    try:
        if is_imagen:
            cfg = types.GenerateImagesConfig(
                number_of_images=max(1, min(int(req.number_of_images or 1), 4)),
                aspect_ratio=str(req.aspect_ratio) if req.aspect_ratio else None,
                image_size=str(req.image_size) if req.image_size else None,
                person_generation=str(req.person_generation) if req.person_generation else None,
            )
            res = await client.aio.models.generate_images(model=model, prompt=req.prompt, config=cfg)
            img_bytes, mime_type = _extract_generated_image(res)
        else:
            cfg2: dict[str, Any] = {"imageConfig": {}}
            if req.aspect_ratio:
                cfg2["imageConfig"]["aspectRatio"] = str(req.aspect_ratio)
            if req.image_size:
                cfg2["imageConfig"]["imageSize"] = str(req.image_size)
            if not cfg2["imageConfig"]:
                cfg2.pop("imageConfig", None)
            res = await client.aio.models.generate_content(model=model, contents=req.prompt, config=cfg2 or None)
            img_bytes, mime_type = _extract_inline_image(res)
    except Exception as e:
        classified = _classify_image_generation_error(str(e))
        if classified is not None:
            raise HTTPException(status_code=503, detail=classified)
        raise HTTPException(status_code=502, detail={"imagen_generate_failed": str(e)})
    import hashlib

    digest = hashlib.sha256(img_bytes).hexdigest()
    asset_id = f"img_{uuid.uuid4().hex[:24]}"
    blob_path, meta_path = _asset_paths(asset_id)
    with open(blob_path, "wb") as f:
        f.write(img_bytes)
    meta = {
        "asset_id": asset_id,
        "model": model,
        "mime_type": mime_type,
        "sha256": digest,
        "prompt": req.prompt,
        "aspect_ratio": req.aspect_ratio,
        "image_size": req.image_size,
        "number_of_images": int(req.number_of_images or 1),
        "person_generation": req.person_generation,
        "created_at": int(time.time()),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    data_url = None
    if req.return_data_url:
        data_url = f"data:{mime_type};base64,{base64.b64encode(img_bytes).decode('ascii')}"
    return ImagenGenerateResponse(asset_id=asset_id, model=model, mime_type=mime_type, sha256=digest, data_url=data_url)


@app.post("/image/generate", response_model=ImageGenerateResponse)
async def image_generate(req: ImageGenerateRequest) -> ImageGenerateResponse:
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="missing_api_key")
    model = _image_allowed_model(req.model)

    _ensure_imagen_assets_dir()
    client = genai.Client(api_key=api_key)
    try:
        cfg2: dict[str, Any] = {"imageConfig": {}}
        if req.aspect_ratio:
            cfg2["imageConfig"]["aspectRatio"] = str(req.aspect_ratio)
        if req.image_size:
            cfg2["imageConfig"]["imageSize"] = str(req.image_size)
        if not cfg2["imageConfig"]:
            cfg2.pop("imageConfig", None)
        res = await client.aio.models.generate_content(model=model, contents=req.prompt, config=cfg2 or None)
        img_bytes, mime_type = _extract_inline_image(res)
    except Exception as e:
        raise HTTPException(status_code=502, detail={"image_generate_failed": str(e)})
    import hashlib

    digest = hashlib.sha256(img_bytes).hexdigest()
    asset_id = f"gimg_{uuid.uuid4().hex[:24]}"
    blob_path, meta_path = _asset_paths(asset_id)
    with open(blob_path, "wb") as f:
        f.write(img_bytes)
    meta = {
        "asset_id": asset_id,
        "model": model,
        "mime_type": mime_type,
        "sha256": digest,
        "prompt": req.prompt,
        "aspect_ratio": req.aspect_ratio,
        "image_size": req.image_size,
        "created_at": int(time.time()),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    data_url = None
    if req.return_data_url:
        data_url = f"data:{mime_type};base64,{base64.b64encode(img_bytes).decode('ascii')}"
    return ImageGenerateResponse(asset_id=asset_id, model=model, mime_type=mime_type, sha256=digest, data_url=data_url)


@app.get("/imagen/assets/{asset_id}/blob")
async def imagen_asset_blob(asset_id: str) -> Response:
    blob_path, _ = _asset_paths(asset_id)
    if not os.path.exists(blob_path):
        raise HTTPException(status_code=404, detail="asset_not_found")
    data = Path(blob_path).read_bytes()
    _, meta_path = _asset_paths(asset_id)
    mime_type = "application/octet-stream"
    try:
        if os.path.exists(meta_path):
            meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
            if isinstance(meta, dict) and meta.get("mime_type"):
                mime_type = str(meta.get("mime_type"))
    except Exception:
        pass
    return Response(content=data, media_type=mime_type)


@app.get("/image/assets/{asset_id}/blob")
async def image_asset_blob(asset_id: str) -> Response:
    return await imagen_asset_blob(asset_id)


@app.get("/imagen/assets/{asset_id}")
async def imagen_asset_meta(asset_id: str) -> dict[str, Any]:
    _, meta_path = _asset_paths(asset_id)
    if not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail="asset_not_found")
    try:
        meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail={"asset_meta_read_failed": str(e)})
    if not isinstance(meta, dict):
        raise HTTPException(status_code=500, detail="asset_meta_invalid")
    return meta


@app.get("/image/assets/{asset_id}")
async def image_asset_meta(asset_id: str) -> dict[str, Any]:
    return await imagen_asset_meta(asset_id)


def _init_session_db() -> None:
    db_session.init_session_db(SESSION_DB_PATH)
    os.makedirs(os.path.dirname(SESSION_DB_PATH) or ".", exist_ok=True)
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_status (
              user_id TEXT NOT NULL,
              agent_id TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              updated_at INTEGER NOT NULL,
              PRIMARY KEY(user_id, agent_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_status_user_updated ON agent_status(user_id, updated_at)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_cache (
              cache_key TEXT PRIMARY KEY,
              payload_json TEXT NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_cache_updated ON news_cache(updated_at)")
        conn.commit()


def _get_news_cache(cache_key: str) -> Optional[dict[str, Any]]:
    _init_session_db()
    k = str(cache_key or "").strip()
    if not k:
        return None
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT payload_json, updated_at FROM news_cache WHERE cache_key = ? LIMIT 1",
            (k,),
        )
        row = cur.fetchone()
    if not row:
        return None
    payload_json, updated_at = row
    try:
        payload = json.loads(payload_json)
    except Exception:
        payload = payload_json
    if isinstance(payload, dict):
        payload.setdefault("updated_at", updated_at)
    return {"cache_key": k, "payload": payload, "updated_at": updated_at}


def _set_news_cache(cache_key: str, payload: Any) -> dict[str, Any]:
    _init_session_db()
    k = str(cache_key or "").strip()
    if not k:
        raise HTTPException(status_code=400, detail="missing_cache_key")
    now_ts = int(time.time())
    payload_json = json.dumps(payload, ensure_ascii=False)
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO news_cache(cache_key, payload_json, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (k, payload_json, now_ts),
        )
        conn.commit()
    return {"ok": True, "cache_key": k, "updated_at": now_ts}


def _weaviate_enabled() -> bool:
    return bool(WEAVIATE_URL)


def _weaviate_object_uuid(external_key: str) -> str:
    # Deterministic UUID for idempotent upserts.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"jarvis::{external_key}"))


def _memo_weaviate_external_key(*, spreadsheet_id: str, sheet_name: str, memo_id: int) -> str:
    ss = str(spreadsheet_id or "").strip()
    sh = str(sheet_name or "").strip()
    mid = int(memo_id or 0)
    return f"memo::{ss}::{sh}::{mid}".strip()


def _memo_embed_text(*, subject: str, memo: str, result: str) -> str:
    s_subject = str(subject or "").strip() or "(no subject)"
    s_memo = str(memo or "").strip()
    s_result = str(result or "").strip()
    parts = [s_subject, s_memo]
    if s_result:
        parts.append(s_result)
    return "\n".join([p for p in parts if p]).strip()


_weaviate_memo_schema_ready: bool = False


async def _weaviate_ensure_memo_schema() -> None:
    global _weaviate_memo_schema_ready
    if _weaviate_memo_schema_ready:
        return
    if not _weaviate_enabled():
        return

    schema = {
        "class": "JarvisMemoItem",
        "description": "Jarvis memo sheet items indexed for semantic retrieval.",
        "vectorizer": "none",
        "properties": [
            {"name": "external_key", "dataType": ["text"]},
            {"name": "spreadsheet_id", "dataType": ["text"]},
            {"name": "sheet_name", "dataType": ["text"]},
            {"name": "memo_id", "dataType": ["number"]},
            {"name": "active", "dataType": ["boolean"]},
            {"name": "group", "dataType": ["text"]},
            {"name": "status", "dataType": ["text"]},
            {"name": "subject", "dataType": ["text"]},
            {"name": "memo", "dataType": ["text"]},
            {"name": "result", "dataType": ["text"]},
            {"name": "date_time", "dataType": ["text"]},
            {"name": "created_at", "dataType": ["number"]},
            {"name": "updated_at", "dataType": ["number"]},
        ],
    }

    try:
        await _weaviate_request("GET", "/v1/schema/JarvisMemoItem")
        _weaviate_memo_schema_ready = True
        return
    except Exception:
        pass

    await _weaviate_request("POST", "/v1/schema", schema)
    _weaviate_memo_schema_ready = True


async def _weaviate_upsert_memo_item(
    *,
    spreadsheet_id: str,
    sheet_name: str,
    memo_id: int,
    active: bool,
    group: str,
    status: str,
    subject: str,
    memo: str,
    result: str,
    date_time: str,
    created_at: float | None = None,
    updated_at: float | None = None,
) -> dict[str, Any]:
    await _weaviate_ensure_memo_schema()
    external_key = _memo_weaviate_external_key(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name, memo_id=int(memo_id))
    obj_id = _weaviate_object_uuid(external_key)
    text = _memo_embed_text(subject=subject, memo=memo, result=result)

    vec: list[float]
    try:
        vec = await _gemini_embed_text_cached(text)
    except Exception:
        vec = _pseudo_embed_vector(text, dim=64)

    props: dict[str, Any] = {
        "external_key": external_key,
        "spreadsheet_id": str(spreadsheet_id or "").strip(),
        "sheet_name": str(sheet_name or "").strip(),
        "memo_id": float(int(memo_id)),
        "active": bool(active),
        "group": str(group or "").strip(),
        "status": str(status or "").strip(),
        "subject": str(subject or "").strip(),
        "memo": str(memo or "").strip(),
        "result": str(result or "").strip(),
        "date_time": str(date_time or "").strip(),
    }
    if created_at is not None:
        props["created_at"] = float(created_at)
    if updated_at is not None:
        props["updated_at"] = float(updated_at)

    payload: dict[str, Any] = {
        "class": "JarvisMemoItem",
        "id": obj_id,
        "properties": props,
        "vector": vec,
    }

    # Weaviate's PUT /v1/objects/{id} is update-by-id and can fail if the object doesn't exist.
    # Use POST create first (idempotent enough with deterministic UUID), then fall back to PUT replace.
    try:
        await _weaviate_request("POST", "/v1/objects", payload)
    except HTTPException as e:
        # If already exists or create fails, attempt replace/update.
        try:
            await _weaviate_request("PUT", f"/v1/objects/{obj_id}", payload)
        except Exception:
            raise e

    return {"ok": True, "id": obj_id, "external_key": external_key}


async def _weaviate_query_related_memos(*, q: str, k: int, group: str | None = None) -> list[dict[str, Any]]:
    await _weaviate_ensure_memo_schema()
    qq = str(q or "").strip()
    if not qq:
        raise HTTPException(status_code=400, detail="missing_q")
    lim = max(1, min(int(k or 30), 200))
    vec: list[float]
    try:
        vec = await _gemini_embed_text_cached(qq)
    except Exception:
        vec = _pseudo_embed_vector(qq, dim=64)

    where_group = "" if not str(group or "").strip() else f'where: {{ path: ["group"], operator: Equal, valueText: "{str(group).strip()}" }}'
    query = {
        "query": f"""
        {{
          Get {{
            JarvisMemoItem(
              nearVector: {{ vector: {json.dumps(vec)} }}
              limit: {int(lim)}
              {where_group}
            ) {{
              memo_id
              active
              group
              status
              subject
              memo
              result
              date_time
              spreadsheet_id
              sheet_name
              external_key
              _additional {{ distance }}
            }}
          }}
        }}
        """
    }
    res = await _weaviate_request("POST", "/v1/graphql", query)
    items = (
        res.get("data", {})
        .get("Get", {})
        .get("JarvisMemoItem", [])
        if isinstance(res, dict)
        else []
    )
    out: list[dict[str, Any]] = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                out.append(it)
    return out


async def _gemini_summarize_text(*, system_instruction: str, prompt: str, model: str | None = None) -> str:
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="missing_api_key")
    m = _normalize_model_name(str(model or os.getenv("GEMINI_TEXT_MODEL") or "gemini-2.0-flash").strip() or "gemini-2.0-flash")
    try:
        client = genai.Client(api_key=api_key)
        cfg = {"system_instruction": str(system_instruction or "").strip()}
        res = await client.aio.models.generate_content(model=m, contents=str(prompt), config=cfg)
        txt = getattr(res, "text", None)
        if txt is None:
            txt = str(res)
        return str(txt or "").strip()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"gemini_generate_failed": f"{type(e).__name__}: {e}", "model": m})


async def _gemini_embed_text(text: str) -> list[float]:
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Missing required env var: API_KEY (or GEMINI_API_KEY)")
    client = genai.Client(api_key=api_key)
    # Embedding API surface and model availability can vary by google-genai version and API key.
    # Keep the calling convention stable (contents=...) and try a few model candidates.
    model_candidates = [
        str(GEMINI_EMBEDDING_MODEL or "").strip(),
        "text-embedding-004",
        "embedding-001",
    ]
    seen: set[str] = set()
    model_candidates = [m for m in model_candidates if m and not (m in seen or seen.add(m))]

    last_err: Exception | None = None
    for m in model_candidates:
        try:
            res = await client.aio.models.embed_content(model=m, contents=text)
            emb = getattr(res, "embedding", None)
            values = getattr(emb, "values", None)
            if isinstance(values, list) and values:
                return [float(x) for x in values]
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(f"gemini_embedding_failed: {last_err}" if last_err is not None else "gemini_embedding_failed")


def _pseudo_embed_vector(text: str, dim: int = 64) -> list[float]:
    # Deterministic, local-only fallback to keep Weaviate writes working when embedding providers are unavailable.
    # Not semantically meaningful like real embeddings, but stable for storage and basic similarity behavior.
    d = max(8, int(dim or 64))
    digest = hashlib.sha256(str(text or "").encode("utf-8")).digest()
    out: list[float] = []
    for i in range(d):
        b = digest[i % len(digest)]
        out.append((float(int(b)) / 255.0) * 2.0 - 1.0)
    return out


_embed_cache: dict[str, list[float]] = {}
_embed_cache_order: list[str] = []
_embed_cache_lock: asyncio.Lock = asyncio.Lock()


async def _gemini_embed_text_cached(text: str) -> list[float]:
    t = str(text or "").strip()
    if not t:
        return []

    max_items = int(JARVIS_EMBED_CACHE_MAX or 0)
    if max_items <= 0:
        return await _gemini_embed_text(t)

    async with _embed_cache_lock:
        cached = _embed_cache.get(t)
        if isinstance(cached, list) and cached:
            try:
                _embed_cache_order.remove(t)
            except Exception:
                pass
            _embed_cache_order.append(t)
            return cached

    vec = await _gemini_embed_text(t)

    async with _embed_cache_lock:
        _embed_cache[t] = vec
        try:
            _embed_cache_order.remove(t)
        except Exception:
            pass
        _embed_cache_order.append(t)

        # Simple LRU eviction.
        while len(_embed_cache_order) > max_items:
            oldest = _embed_cache_order.pop(0)
            try:
                _embed_cache.pop(oldest, None)
            except Exception:
                pass

    return vec


async def _weaviate_request(method: str, path: str, payload: Any = None) -> Any:
    if not _weaviate_enabled():
        raise HTTPException(status_code=500, detail="weaviate_not_configured")
    url = f"{WEAVIATE_URL}{path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.request(method, url, json=payload)
        if res.status_code >= 400:
            detail: Any
            try:
                detail = res.json()
            except Exception:
                detail = res.text
            # Preserve original status code so callers can handle 404 vs 500 etc.
            raise HTTPException(status_code=int(res.status_code), detail={"weaviate_error": detail})
        if not res.text:
            return None
        try:
            return res.json()
        except Exception:
            return res.text


def _adapt_playwright_tool_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = str(tool_name or "").strip()
    out = dict(args or {})

    if tool == "browser_take_screenshot":
        if "full_page" in out and "fullPage" not in out:
            out["fullPage"] = out.pop("full_page")
        if "fullpage" in out and "fullPage" not in out:
            out["fullPage"] = out.pop("fullpage")

    if tool == "browser_wait_for":
        if "text_gone" in out and "textGone" not in out:
            out["textGone"] = out.pop("text_gone")

        state = out.pop("state", None)
        timeout_ms = out.pop("timeout_ms", None)
        timeout_ms2 = out.pop("timeoutMs", None)
        time_ms = out.pop("time_ms", None)
        time_s = out.get("time")

        if time_s is None and time_ms is not None:
            try:
                out["time"] = float(time_ms) / 1000.0
            except Exception:
                pass

        if out.get("time") is None and (timeout_ms is not None or timeout_ms2 is not None):
            try:
                ms = timeout_ms if timeout_ms is not None else timeout_ms2
                out["time"] = float(ms) / 1000.0
            except Exception:
                pass

        if out.get("time") is None and out.get("text") is None and out.get("textGone") is None and state is not None:
            s = str(state).strip().lower()
            if s in {"networkidle", "network_idle", "idle"}:
                out["time"] = 1

    if tool == "browser_click":
        if "double_click" in out and "doubleClick" not in out:
            out["doubleClick"] = out.pop("double_click")

    if tool == "browser_snapshot":
        if "selector" in out:
            out.pop("selector", None)

    return out


async def _deep_research_worker_post(path: str, payload: Any) -> Any:
    if not DEEP_RESEARCH_WORKER_BASE_URL:
        raise HTTPException(status_code=500, detail="deep_research_worker_not_configured")
    url = f"{DEEP_RESEARCH_WORKER_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(url, json=payload)
        if res.status_code >= 400:
            detail: Any
            try:
                detail = res.json()
            except Exception:
                detail = res.text
            raise HTTPException(status_code=res.status_code, detail=detail)
        return res.json()


async def _deep_research_worker_get(path: str) -> Any:
    if not DEEP_RESEARCH_WORKER_BASE_URL:
        raise HTTPException(status_code=500, detail="deep_research_worker_not_configured")
    url = f"{DEEP_RESEARCH_WORKER_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.get(url)
        if res.status_code >= 400:
            detail: Any
            try:
                detail = res.json()
            except Exception:
                detail = res.text
            raise HTTPException(status_code=res.status_code, detail=detail)
        return res.json()


async def _weaviate_ensure_schema() -> None:
    global _weaviate_schema_ready
    if _weaviate_schema_ready:
        return
    if not _weaviate_enabled():
        return

    schema = {
        "class": "JarvisMemoryItem",
        "description": "Jarvis authoritative memory items (reminders, todos, notes, agent status).",
        "vectorizer": "none",
        "properties": [
            {"name": "external_key", "dataType": ["text"]},
            {"name": "kind", "dataType": ["text"]},
            {"name": "title", "dataType": ["text"]},
            {"name": "body", "dataType": ["text"]},
            {"name": "status", "dataType": ["text"]},
            {"name": "due_at", "dataType": ["number"]},
            {"name": "notify_at", "dataType": ["number"]},
            {"name": "timezone", "dataType": ["text"]},
            {"name": "source", "dataType": ["text"]},
            {"name": "created_at", "dataType": ["number"]},
            {"name": "updated_at", "dataType": ["number"]},
        ],
    }

    try:
        existing_schema = await _weaviate_request("GET", "/v1/schema/JarvisMemoryItem")
        try:
            props = existing_schema.get("properties") if isinstance(existing_schema, dict) else None
            prop_names = {str(p.get("name")) for p in props} if isinstance(props, list) else set()
            if "hide_until" not in prop_names:
                await _weaviate_request(
                    "POST",
                    "/v1/schema/JarvisMemoryItem/properties",
                    {"name": "hide_until", "dataType": ["number"]},
                )
        except Exception:
            pass
        _weaviate_schema_ready = True
        return
    except Exception:
        pass

    await _weaviate_request("POST", "/v1/schema", schema)
    _weaviate_schema_ready = True


async def _weaviate_query_upcoming_reminders(*, start_ts: int, end_ts: int, limit: int) -> list[dict[str, Any]]:
    await _weaviate_ensure_schema()
    lim = max(1, min(int(limit or 50), 500))
    query = {
        "query": """
        {
          Get {
            JarvisMemoryItem(
              where: {
                operator: And
                operands: [
                  { path: [\"kind\"], operator: Equal, valueText: \"reminder\" }
                  { path: [\"status\"], operator: Equal, valueText: \"pending\" }
                  { path: [\"notify_at\"], operator: GreaterThanEqual, valueNumber: %START% }
                  { path: [\"notify_at\"], operator: LessThanEqual, valueNumber: %END% }
                ]
              }
              limit: %LIMIT%
            ) {
              external_key
              title
              body
              status
              due_at
              notify_at
              hide_until
              timezone
              updated_at
            }
          }
        }
        """
        .replace("%START%", str(float(int(start_ts))))
        .replace("%END%", str(float(int(end_ts))))
        .replace("%LIMIT%", str(int(lim)))
    }
    res = await _weaviate_request("POST", "/v1/graphql", query)
    items = (
        res.get("data", {})
        .get("Get", {})
        .get("JarvisMemoryItem", [])
        if isinstance(res, dict)
        else []
    )
    out: list[dict[str, Any]] = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                out.append(it)
    return out


async def _weaviate_query_reminders(*, status: str, limit: int) -> list[dict[str, Any]]:
    await _weaviate_ensure_schema()
    lim = max(1, min(int(limit or 50), 500))
    status_norm = str(status or "all").strip().lower() or "all"
    if status_norm not in ("all", "pending", "fired", "done"):
        raise HTTPException(status_code=400, detail="invalid_status")

    where_status = "" if status_norm == "all" else f'{{ path: ["status"], operator: Equal, valueText: "{status_norm}" }}'
    operands = "\n".join(
        [
            '{ path: ["kind"], operator: Equal, valueText: "reminder" }',
            where_status,
        ]
    ).strip()
    # Remove any empty lines if status is all.
    operands = "\n".join([l for l in operands.splitlines() if l.strip()])

    query = {
        "query": f"""
        {{
          Get {{
            JarvisMemoryItem(
              where: {{
                operator: And
                operands: [
{operands}
                ]
              }}
              limit: {int(lim)}
              sort: [{{ path: [\"updated_at\"], order: desc }}]
            ) {{
              external_key
              title
              body
              status
              due_at
              notify_at
              hide_until
              timezone
              created_at
              updated_at
              source
            }}
          }}
        }}
        """
    }

    res = await _weaviate_request("POST", "/v1/graphql", query)
    items = (
        res.get("data", {})
        .get("Get", {})
        .get("JarvisMemoryItem", [])
        if isinstance(res, dict)
        else []
    )
    out: list[dict[str, Any]] = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                out.append(it)
    return out


def _local_reminder_id_from_external_key(external_key: str) -> str:
    s = str(external_key or "").strip()
    # Prefer decoding when possible to avoid generating new local ids for existing reminders.
    if s.startswith("reminder::"):
        tail = s[len("reminder::") :].strip()
        if tail:
            return tail
    # Stable local PK so restart sync can still upsert deterministically.
    u = uuid.uuid5(uuid.NAMESPACE_URL, f"jarvis_local::{s}")
    return f"r_{u.hex[:18]}"


def _upsert_local_reminder_from_memory_item(user_id: str, item: dict[str, Any]) -> Optional[str]:
    external_key = str(item.get("external_key") or "").strip()
    if not external_key:
        return None
    reminder_id = _local_reminder_id_from_external_key(external_key)
    title = str(item.get("title") or "Reminder").strip() or "Reminder"
    tz_name = str(item.get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    schedule_type = "memory"
    source_text = str(item.get("body") or "").strip()

    due_at = item.get("due_at")
    notify_at = item.get("notify_at")
    try:
        due_at_ts = int(float(due_at)) if due_at is not None else None
    except Exception:
        due_at_ts = None
    try:
        notify_at_ts = int(float(notify_at)) if notify_at is not None else None
    except Exception:
        notify_at_ts = None

    if notify_at_ts is None:
        return None

    dedupe_key = _reminder_dedupe_key(title, due_at_ts, schedule_type)

    _init_session_db()
    now_ts = int(time.time())
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO reminders(
              reminder_id, user_id, title, dedupe_key, due_at, timezone, schedule_type, notify_at, status,
              source_text, aim_entity_name, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(reminder_id) DO UPDATE SET
              title=excluded.title,
              dedupe_key=excluded.dedupe_key,
              due_at=excluded.due_at,
              timezone=excluded.timezone,
              schedule_type=excluded.schedule_type,
              notify_at=excluded.notify_at,
              status=excluded.status,
              source_text=excluded.source_text,
              updated_at=excluded.updated_at
            """,
            (
                reminder_id,
                user_id,
                title,
                dedupe_key,
                due_at_ts,
                tz_name,
                schedule_type,
                notify_at_ts,
                "pending",
                source_text,
                external_key,
                now_ts,
                now_ts,
            ),
        )
        conn.commit()
    return reminder_id


def _parse_agent_md(md_text: str) -> Optional[dict[str, Any]]:
    text = str(md_text or "")
    if not text.strip().startswith("---"):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    meta: dict[str, Any] = {}
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            key = str(k).strip()
            val = str(v).strip()
            if key:
                meta[key] = val
        i += 1

    if i >= len(lines) or lines[i].strip() != "---":
        return None

    body = "\n".join(lines[i + 1 :]).strip()
    if body:
        meta["body"] = body
    return meta


def _load_agent_defs() -> dict[str, dict[str, Any]]:
    defs: dict[str, dict[str, Any]] = {}
    root = Path(AGENTS_DIR)
    if not root.exists() or not root.is_dir():
        return defs

    for p in sorted(root.rglob("*.md")):
        try:
            md = p.read_text(encoding="utf-8")
        except Exception:
            continue
        parsed = _parse_agent_md(md)
        if not isinstance(parsed, dict):
            continue
        agent_id = str(parsed.get("id") or "").strip()
        if not agent_id:
            continue
        parsed["path"] = str(p)
        defs[agent_id] = parsed
    return defs


def _agents_snapshot() -> dict[str, dict[str, Any]]:
    global _agent_defs
    if not _agent_defs:
        _agent_defs = _load_agent_defs()
    return dict(_agent_defs)


def _agent_triggers_snapshot() -> dict[str, list[str]]:
    global _agent_triggers
    if _agent_triggers:
        return dict(_agent_triggers)

    agents = _agents_snapshot()
    out: dict[str, list[str]] = {}
    for agent_id, meta in agents.items():
        raw = meta.get("trigger_phrases")
        if raw is None:
            continue
        phrases: list[str] = []
        if isinstance(raw, str):
            # Support simple comma-separated values (frontmatter is parsed as strings).
            for part in raw.split(","):
                p = part.strip()
                if p:
                    phrases.append(p)
        if phrases:
            out[agent_id] = phrases
    _agent_triggers = out
    return dict(_agent_triggers)


def _upsert_agent_status(user_id: str, agent_id: str, payload: Any) -> None:
    _init_session_db()
    now_ts = int(time.time())
    payload_json = json.dumps(payload, ensure_ascii=False)
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO agent_status(user_id, agent_id, payload_json, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(user_id, agent_id) DO UPDATE SET
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (user_id, agent_id, payload_json, now_ts),
        )
        conn.commit()


def _get_agent_statuses(user_id: str) -> list[dict[str, Any]]:
    _init_session_db()
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT agent_id, payload_json, updated_at FROM agent_status WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for agent_id, payload_json, updated_at in rows:
        try:
            payload = json.loads(payload_json)
        except Exception:
            payload = payload_json
        out.append({"agent_id": agent_id, "payload": payload, "updated_at": updated_at})
    return out


async def _render_daily_brief(user_id: str) -> dict[str, Any]:
    def _now_ts() -> int:
        return int(time.time())

    def _datetime_now_iso(tz: Any) -> str:
        return datetime.now(tz=tz).isoformat()

    def _datetime_from_ts_iso_utc(ts: int) -> str:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()

    return await daily_brief.render_daily_brief(
        user_id,
        agents_snapshot=_agents_snapshot,
        get_agent_statuses=_get_agent_statuses,
        weaviate_enabled=_weaviate_enabled,
        weaviate_query_upcoming_reminders=_weaviate_query_upcoming_reminders,
        list_upcoming_pending_reminders=lambda **_: [],
        get_user_timezone=_get_user_timezone,
        now_ts=_now_ts,
        datetime_now_iso=_datetime_now_iso,
        datetime_from_ts_iso_utc=_datetime_from_ts_iso_utc,
    )


def _extract_reminder_setup_title(text: str) -> str:
    s = str(text or "").strip()
    m = re.search(r"\breminder\s+setup\b\s*[:\-]?\s*(.*)$", s, flags=re.IGNORECASE)
    tail = ""
    if m:
        tail = str(m.group(1) or "").strip()
    else:
        # Also support the shorter colon form.
        m2 = re.search(r"\breminder\b\s*[:\-]\s*(.*)$", s, flags=re.IGNORECASE)
        if m2:
            tail = str(m2.group(1) or "").strip()

    if not tail:
        # Thai variants (keep loose spacing). Examples:
        # - สร้างแจ้งเตือนใหม่ พรุ่งนี้ 9 โมงเช้า ...
        # - แจ้งเตือน: พรุ่งนี้ ...
        # - ตั้งเตือน: ...
        m_th = re.search(r"^(?:สร้าง\s*)?แจ้งเตือน(?:\s*ใหม่)?\s*[:\-]?\s*(.*)$", s)
        if m_th:
            tail = str(m_th.group(1) or "").strip()
        else:
            m_th2 = re.search(r"^ตั้ง\s*เตือน\s*[:\-]?\s*(.*)$", s)
            if m_th2:
                tail = str(m_th2.group(1) or "").strip()

    if not tail:
        return "Reminder"

    # Keep titles short and stable.
    return tail[:120]


def _strip_time_phrases_from_title(title: str) -> str:
    t = " ".join(str(title or "").strip().split())
    if not t:
        return "Reminder"

    # Remove common time/date fragments that often leak into the title.
    # Keep this conservative: only strip known patterns.
    patterns = [
        # Thai day words
        r"\b(?:วันนี้|พรุ่งนี้|มะรืน|เมื่อวาน|คืนนี้|เช้านี้|พรุ่งนี้เช้า)\b",
        # Thai time words
        r"\b\d{1,2}\s*โมง(?:\s*(?:เช้า|เย็น|ค่ำ|กลางคืน))?\b",
        r"\b\d{1,2}\s*ทุ่ม\b",
        r"\bเที่ยง(?:คืน|วัน)?\b",
        r"\bบ่าย\s*\d{1,2}\b",
        # Numeric time
        r"\b\d{1,2}:\d{2}\b",
        r"\b\d{1,2}\s*(?:am|pm)\b",
        # English day words
        r"\b(?:today|tomorrow|tonight|this\s+morning|this\s+evening)\b",
    ]
    out = t
    for p in patterns:
        out = re.sub(p, " ", out, flags=re.IGNORECASE)

    # Clean up separators that frequently surround the time.
    out = re.sub(r"\s*[-–—|•]+\s*", " ", out)
    out = re.sub(r"\(\s*\)", "", out)
    out = " ".join(out.strip().split())
    if not out:
        return "Reminder"
    if len(out) > 120:
        out = out[:120].rstrip()
    return out


def _text_is_thai(text: str) -> bool:
    s = str(text or "")
    for ch in s:
        if "\u0e00" <= ch <= "\u0e7f":
            return True
    return False


def _lang_from_ws(ws: WebSocket) -> str:
    try:
        accept = str(getattr(ws, "headers", {}).get("accept-language") or "")
    except Exception:
        accept = ""
    low = accept.lower()
    if "th" in low:
        return "th"
    return "en"


def _short_greeting_for_now(*, lang: str, now_local: datetime) -> str:
    t = now_local.strftime("%H:%M")
    if str(lang or "").lower().startswith("th"):
        dnames = ["จ.", "อ.", "พ.", "พฤ.", "ศ.", "ส.", "อา."]
        mnames = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
        dow = dnames[int(now_local.weekday())]
        mon = mnames[int(now_local.month) - 1]
        return f"{dow} {now_local.day} {mon} {t}"
    return now_local.strftime("%a, %b %d %H:%M")


async def _emit_live_connect_greeting(ws: WebSocket) -> None:
    tz = _get_user_timezone(DEFAULT_USER_ID)
    now_local = datetime.now(tz=timezone.utc).astimezone(tz)
    lang = str(getattr(ws.state, "user_lang", "") or "").strip() or _lang_from_ws(ws)
    msg = _short_greeting_for_now(lang=lang, now_local=now_local)
    try:
        await _ws_send_json(ws, {"type": "text", "text": msg})
    except Exception:
        pass


def _short_datetime_line(lang: str, now_local: datetime) -> str:
    if str(lang or "").strip().lower().startswith("th"):
        return now_local.strftime("%Y-%m-%d %H:%M")
    return now_local.strftime("%Y-%m-%d %H:%M")


def _memory_load_status_line(ws: WebSocket, lang: str) -> str:
    sheet = str(getattr(ws.state, "memory_sheet_name", "") or "").strip() or "memory"
    items = getattr(ws.state, "memory_items", None)
    n = len(items) if isinstance(items, list) else 0
    cached_items = _SHEET_MEMORY_CACHE.get("memory_items") if isinstance(_SHEET_MEMORY_CACHE, dict) else None
    cached_n = len(cached_items) if isinstance(cached_items, list) else 0
    mem_created = int(_SHEET_MEMORY_CACHE.get("created_at") or 0) if isinstance(_SHEET_MEMORY_CACHE, dict) else 0
    mem_updated = int(_SHEET_MEMORY_CACHE.get("updated_at") or 0) if isinstance(_SHEET_MEMORY_CACHE, dict) else 0
    ksheet = str(getattr(ws.state, "knowledge_sheet_name", "") or "").strip() or "knowledge"
    kitems = getattr(ws.state, "knowledge_items", None)
    kn = len(kitems) if isinstance(kitems, list) else 0
    cached_kitems = _SHEET_KNOWLEDGE_CACHE.get("knowledge_items") if isinstance(_SHEET_KNOWLEDGE_CACHE, dict) else None
    cached_kn = len(cached_kitems) if isinstance(cached_kitems, list) else 0
    know_created = int(_SHEET_KNOWLEDGE_CACHE.get("created_at") or 0) if isinstance(_SHEET_KNOWLEDGE_CACHE, dict) else 0
    know_updated = int(_SHEET_KNOWLEDGE_CACHE.get("updated_at") or 0) if isinstance(_SHEET_KNOWLEDGE_CACHE, dict) else 0

    def _fmt_ts(ts: int) -> str:
        if ts <= 0:
            return "0"
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            return str(ts)

    mem_meta = f" memory_created={_fmt_ts(mem_created)} memory_updated={_fmt_ts(mem_updated)}"
    know_meta = f" knowledge_created={_fmt_ts(know_created)} knowledge_updated={_fmt_ts(know_updated)}"
    if str(lang or "").lower().startswith("th"):
        return (
            f"โหลด memory '{sheet}' in-cache={cached_n} in-ws={n}{mem_meta} | "
            f"knowledge '{ksheet}' in-cache={cached_kn} in-ws={kn}{know_meta}"
        )
    return (
        f"Loaded memory '{sheet}' in-cache={cached_n} in-ws={n}{mem_meta} | "
        f"knowledge '{ksheet}' in-cache={cached_kn} in-ws={kn}{know_meta}"
    )


def _startup_prewarm_status_line(lang: str) -> str:
    st = _STARTUP_PREWARM_STATUS if isinstance(_STARTUP_PREWARM_STATUS, dict) else {}
    ok = bool(st.get("ok"))
    mem_n = int(st.get("memory_n") or 0)
    know_n = int(st.get("knowledge_n") or 0)
    err = str(st.get("error") or "").strip()
    ts = int(st.get("ts") or 0)
    running = bool(st.get("running"))
    if str(lang or "").lower().startswith("th"):
        if running:
            return "พรีวอร์มตอนเริ่มระบบ: running"
        if ts <= 0 and (not ok) and (not err):
            return "พรีวอร์มตอนเริ่มระบบ: pending"
        if ok:
            return f"พรีวอร์มตอนเริ่มระบบ: ok | memory={mem_n} knowledge={know_n}"
        if err:
            return f"พรีวอร์มตอนเริ่มระบบ: error | {err}"
        return "พรีวอร์มตอนเริ่มระบบ: pending"
    if running:
        return "Startup prewarm: running"
    if ts <= 0 and (not ok) and (not err):
        return "Startup prewarm: pending"
    if ok:
        return f"Startup prewarm: ok | memory={mem_n} knowledge={know_n}"
    if err:
        return f"Startup prewarm: error | {err}"
    return "Startup prewarm: pending"


async def _startup_prewarm_sheets() -> None:
    # Prewarm caches (system KV only) even when no UI is connected.
    async with _STARTUP_PREWARM_LOCK:
        _STARTUP_PREWARM_STATUS["ts"] = int(time.time())
        _STARTUP_PREWARM_STATUS["running"] = True
        _STARTUP_PREWARM_STATUS["ok"] = False
        _STARTUP_PREWARM_STATUS["error"] = ""
        _STARTUP_PREWARM_STATUS["memory_n"] = 0
        _STARTUP_PREWARM_STATUS["knowledge_n"] = 0

        class _DummyWS:
            def __init__(self) -> None:
                from types import SimpleNamespace

                self.state = SimpleNamespace()

        ws = _DummyWS()
        last_err: Exception | None = None
        backoff_s = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 15.0]
        for i, delay in enumerate(backoff_s):
            if delay > 0:
                try:
                    await asyncio.sleep(delay)
                except Exception:
                    pass
            try:
                ws = _DummyWS()
                await _load_ws_system_kv(ws)
                _STARTUP_PREWARM_STATUS["memory_n"] = 0
                _STARTUP_PREWARM_STATUS["knowledge_n"] = 0
                _STARTUP_PREWARM_STATUS["ok"] = True
                _STARTUP_PREWARM_STATUS["error"] = ""
                _STARTUP_PREWARM_STATUS["running"] = False
                logger.info(
                    "startup_prewarm_ok_retry attempt=%s/%s memory=%s knowledge=%s",
                    i + 1,
                    len(backoff_s),
                    _STARTUP_PREWARM_STATUS["memory_n"],
                    _STARTUP_PREWARM_STATUS["knowledge_n"],
                )
                return
            except Exception as e2:
                last_err = e2
                try:
                    logger.warning(
                        "startup_prewarm_retry_failed attempt=%s/%s delay_s=%s error=%s",
                        i + 1,
                        len(backoff_s),
                        delay,
                        str(e2),
                    )
                except Exception:
                    pass

        _STARTUP_PREWARM_STATUS["error"] = str(last_err)
        _STARTUP_PREWARM_STATUS["running"] = False
        logger.warning("startup_prewarm_failed error=%s", str(last_err))


def _parse_reminder_helper_command(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    s = " ".join(raw.lower().split())
    if not s:
        return {"action": "", "args": {}}

    def after(prefix: str) -> str:
        if s.startswith(prefix + ":"):
            return raw.split(":", 1)[1].strip()
        if s.startswith(prefix + " "):
            return raw[len(prefix) :].strip()
        return ""

    # English
    if s.startswith("reminder add"):
        return {"action": "add", "args": {"text": after("reminder add")}}
    if s.startswith("reminder done"):
        return {"action": "done", "args": {"reminder_id": after("reminder done")}}
    if s.startswith("reminder later"):
        tail = after("reminder later")
        parts = tail.split()
        rid = parts[0].strip() if parts else ""
        days = None
        if len(parts) >= 2:
            try:
                days = int(parts[1])
            except Exception:
                days = None
        return {"action": "later", "args": {"reminder_id": rid, "days": days}}
    if s.startswith("reminder reschedule"):
        tail = after("reminder reschedule")
        parts = tail.split(" ", 1)
        rid = parts[0].strip() if parts else ""
        when = parts[1].strip() if len(parts) > 1 else ""
        return {"action": "reschedule", "args": {"reminder_id": rid, "when": when}}
    if s.startswith("reminder delete"):
        return {"action": "delete", "args": {"reminder_id": after("reminder delete")}}
    if s.startswith("reminder list"):
        tail = after("reminder list")
        tail_s = " ".join(tail.lower().split())
        status = "pending" if "pending" in tail_s else "all" if tail_s else "pending"
        include_hidden = "include_hidden" in tail_s or "hidden" in tail_s
        day = ""
        if "today" in tail_s:
            day = "today"
        elif "yesterday" in tail_s:
            day = "yesterday"
        return {"action": "list", "args": {"status": status, "include_hidden": include_hidden, "day": day}}

    if s.startswith("list reminder") or s.startswith("list reminders"):
        tail = after("list reminder")
        if not tail:
            tail = after("list reminders")
        tail_s = " ".join(tail.lower().split())
        status = "pending" if "pending" in tail_s else "all" if tail_s else "pending"
        include_hidden = "include_hidden" in tail_s or "hidden" in tail_s
        day = ""
        if "today" in tail_s:
            day = "today"
        elif "yesterday" in tail_s:
            day = "yesterday"
        return {"action": "list", "args": {"status": status, "include_hidden": include_hidden, "day": day}}
    if s == "all reminders" or s == "show all reminders":
        return {"action": "list", "args": {"status": "all", "include_hidden": False, "day": "today"}}
    if s.startswith("list all reminders") or s.startswith("show all reminders"):
        tail = raw.split(" ", 3)[3].strip() if len(raw.split()) >= 4 else ""
        tail_s = " ".join(tail.lower().split())
        include_hidden = "include_hidden" in tail_s or "hidden" in tail_s
        day = "today"
        if "today" in tail_s:
            day = "today"
        elif "yesterday" in tail_s:
            day = "yesterday"
        return {"action": "list", "args": {"status": "all", "include_hidden": include_hidden, "day": day}}

    # Thai aliases
    if s.startswith("เตือน เพิ่ม"):
        return {"action": "add", "args": {"text": after("เตือน เพิ่ม")}}
    if s.startswith("เตือน เสร็จ"):
        return {"action": "done", "args": {"reminder_id": after("เตือน เสร็จ")}}
    if s.startswith("เตือน ลบ"):
        return {"action": "delete", "args": {"reminder_id": after("เตือน ลบ")}}
    if s.startswith("เตือน เลื่อน"):
        tail = after("เตือน เลื่อน")
        parts = tail.split(" ", 1)
        rid = parts[0].strip() if parts else ""
        when = parts[1].strip() if len(parts) > 1 else ""
        return {"action": "reschedule", "args": {"reminder_id": rid, "when": when}}

    if (
        s == "แสดงการแจ้งเตือน"
        or s == "รายการแจ้งเตือน"
        or s == "แสดงรายการแจ้งเตือน"
        or s == "แสดงรายการนัดหมาย"
        or s == "รายการนัดหมาย"
        or s == "แสดงการนัดหมาย"
    ):
        return {"action": "list", "args": {"status": "pending", "include_hidden": False}}
    if (
        s.startswith("แสดงการแจ้งเตือน ")
        or s.startswith("รายการแจ้งเตือน ")
        or s.startswith("แสดงรายการแจ้งเตือน ")
        or s.startswith("แสดงรายการนัดหมาย ")
        or s.startswith("รายการนัดหมาย ")
        or s.startswith("แสดงการนัดหมาย ")
    ):
        tail = raw.split(" ", 1)[1].strip() if " " in raw else ""
        tail_s = " ".join(tail.lower().split())
        status = "all" if ("ทั้งหมด" in tail_s or "all" in tail_s) else "pending"
        include_hidden = "ซ่อน" in tail_s or "hidden" in tail_s
        day = ""
        if "วันนี้" in tail_s or "today" in tail_s:
            day = "today"
        elif "เมื่อวาน" in tail_s or "yesterday" in tail_s:
            day = "yesterday"
        return {"action": "list", "args": {"status": status, "include_hidden": include_hidden, "day": day}}
    if s.startswith("เตือน รายการ"):
        tail = after("เตือน รายการ")
        tail_s = " ".join(tail.lower().split())
        status = "pending" if "pending" in tail_s else "all" if tail_s else "pending"
        include_hidden = "include_hidden" in tail_s or "hidden" in tail_s
        return {"action": "list", "args": {"status": status, "include_hidden": include_hidden}}

    return {"action": "", "args": {}}


async def _improve_reminder_title(*, raw_title: str, source_text: str) -> str:
    title = str(raw_title or "").strip() or "Reminder"
    src = str(source_text or "").strip()
    if not src or not title:
        return title[:120]

    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return title[:120]

    prompt = (
        "Rewrite the reminder title to be clear, concise, and actionable. "
        "Preserve the user's language (Thai stays Thai). "
        "Keep it under 80 characters. Output ONLY the title.\n\n"
        f"User text: {src}\n"
        f"Current title: {title}\n"
    )

    try:
        client = genai.Client(api_key=api_key)

        async def _run(model_name: str) -> str:
            res = await client.aio.models.generate_content(model=model_name, contents=prompt)
            txt = getattr(res, "text", None)
            if txt is None:
                try:
                    txt = str(res)
                except Exception:
                    txt = ""
            cleaned = " ".join(str(txt or "").strip().split())
            if not cleaned:
                return title
            if len(cleaned) > 120:
                cleaned = cleaned[:120].rstrip()
            return cleaned

        last_err: Exception | None = None
        for model_name in REMINDER_TITLE_MODELS:
            try:
                improved = await asyncio.wait_for(_run(model_name), timeout=2.5)
                return str(improved or title).strip()[:120] or "Reminder"
            except Exception as e:
                last_err = e
                msg = str(e)
                lower = msg.lower()
                retryable = any(
                    k in lower
                    for k in [
                        "resource_exhausted",
                        "quota",
                        "rate",
                        "429",
                        "not found",
                        "model",
                        "permission",
                        "403",
                        "404",
                        "unavailable",
                        "503",
                        "500",
                        "timeout",
                    ]
                )
                if retryable:
                    continue
                raise

        if last_err is not None:
            logger.warning("reminder_title_rewrite_failed: %s", last_err)
        return title[:120]
    except Exception:
        return title[:120]


async def _handle_reminder_setup_trigger(ws: WebSocket, text: str, *, speak: bool = True) -> bool:
    title = _extract_reminder_setup_title(text)
    title = await _improve_reminder_title(raw_title=title, source_text=text)
    title = _strip_time_phrases_from_title(title)
    tz = _get_user_timezone(DEFAULT_USER_ID)
    now = datetime.now(tz=timezone.utc)
    due_at_utc, local_iso = _parse_time_from_text(text, now, tz)
    if due_at_utc is not None:
        cal = await _google_calendar_create_reminder_event(title=title, due_at_utc=due_at_utc, tz=tz, source_text=text)
        await _ws_send_json(
            ws,
            {
                "type": "planning_item_created",
                "kind": "calendar_event",
                "title": title,
                "result": {"ok": True, "calendar": cal, "local_time": local_iso, "timezone": tz.key},
                "instance_id": INSTANCE_ID,
            },
        )
        if speak:
            try:
                await _live_say(ws, f"สร้างอีเวนต์ในปฏิทินแล้ว: {title}" if _text_is_thai(text) else f"Created a calendar event: {title}.")
            except Exception:
                pass
        return True

    # No explicit time: create a Google Task instead.
    meta = MCP_TOOL_MAP.get("google_tasks_create_task") if isinstance(MCP_TOOL_MAP, dict) else None
    mcp_name = str(meta.get("mcp_name") or "").strip() if isinstance(meta, dict) else ""
    if not mcp_name:
        raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")

    payload: dict[str, Any] = {
        "title": title,
        "notes": str(text or "").strip(),
    }
    res = await _mcp_tools_call(mcp_name, payload)
    parsed = _mcp_text_json(res)
    await _ws_send_json(
        ws,
        {
            "type": "planning_item_created",
            "kind": "task",
            "title": title,
            "result": parsed if isinstance(parsed, dict) else {"raw": parsed},
            "instance_id": INSTANCE_ID,
        },
    )
    if speak:
        try:
            await _live_say(ws, f"สร้างงานแล้ว: {title}" if _text_is_thai(text) else f"Created a task: {title}.")
        except Exception:
            pass
    return True


async def _handle_github_watch_voice(ws: WebSocket, text: str) -> bool:
    s = " ".join(str(text or "").strip().split())
    if not s:
        return False

    sys_kv = _sys_kv_snapshot()
    cfg = _voice_command_config_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else {})
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return False

    gh_cfg = cfg.get("github_watch") if isinstance(cfg.get("github_watch"), dict) else {}
    if not isinstance(gh_cfg, dict) or not gh_cfg.get("enabled"):
        return False

    phrases = gh_cfg.get("phrases") if isinstance(gh_cfg.get("phrases"), list) else []
    if not phrases:
        return False

    s_lower = s.lower()
    matched = False
    for p in phrases:
        pl = str(p or "").strip().lower()
        if pl and pl in s_lower:
            matched = True
            break
    if not matched:
        return False

    # Debounce repeated STT triggers (per websocket).
    try:
        now_ts = time.time()
        debounce_ms = _safe_int(gh_cfg.get("debounce_ms"), default=_safe_int(cfg.get("debounce_ms"), default=10000))
        debounce_s = max(0.0, float(debounce_ms) / 1000.0)
        last_ts = float(getattr(ws.state, "github_watch_last_ts", 0.0) or 0.0)
        if last_ts and debounce_s > 0 and (now_ts - last_ts) < debounce_s:
            return True
        ws.state.github_watch_last_ts = now_ts
    except Exception:
        pass

    owner = str(gh_cfg.get("owner") or "tonezzz").strip() or "tonezzz"
    repo = str(gh_cfg.get("repo") or "chaba").strip() or "chaba"
    branch = str(gh_cfg.get("branch") or "").strip() or None
    event = str(gh_cfg.get("event") or "").strip() or None

    try:
        poll_seconds = float(gh_cfg.get("poll_seconds") or 15.0)
    except Exception:
        poll_seconds = 15.0
    poll_seconds = max(2.0, min(120.0, poll_seconds))

    try:
        timeout_seconds = float(gh_cfg.get("timeout_seconds") or 3600.0)
    except Exception:
        timeout_seconds = 3600.0
    timeout_seconds = max(30.0, min(7200.0, timeout_seconds))

    lang = str(getattr(ws.state, "user_lang", "") or "").strip() or "en"

    async def _run_once() -> None:
        try:
            if lang == "th":
                await _live_say(ws, "กำลังดู GitHub Actions อยู่ครับ")
            else:
                await _live_say(ws, "Watching GitHub Actions.")

            res = await github_actions_watch(
                owner=owner,
                repo=repo,
                branch=branch,
                event=event,
                poll_seconds=poll_seconds,
                timeout_seconds=timeout_seconds,
            )

            run = res.get("run") if isinstance(res, dict) else None
            completed = bool(res.get("completed")) if isinstance(res, dict) else False
            run_id = str((run or {}).get("id") or "").strip() if isinstance(run, dict) else ""
            conclusion = str((run or {}).get("conclusion") or "").strip().lower() if isinstance(run, dict) else ""
            url = str((run or {}).get("html_url") or "").strip() if isinstance(run, dict) else ""

            if not completed:
                if lang == "th":
                    await _live_say(ws, "ยังไม่จบภายในเวลาที่กำหนด")
                else:
                    await _live_say(ws, "The workflow did not finish before the timeout.")
                return

            if conclusion == "success":
                msg = "บิลด์สำเร็จ" if lang == "th" else "Build succeeded."
            elif conclusion:
                failed_job = ""
                failed_step = ""
                try:
                    if run_id:
                        jobs = await _github_api_get(f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs")
                        items = jobs.get("jobs") if isinstance(jobs, dict) else None
                        if isinstance(items, list):
                            for job in items:
                                if not isinstance(job, dict):
                                    continue
                                if str(job.get("conclusion") or "").strip().lower() != "failure":
                                    continue
                                failed_job = str(job.get("name") or job.get("id") or "").strip()
                                steps = job.get("steps") if isinstance(job.get("steps"), list) else []
                                for st in steps:
                                    if not isinstance(st, dict):
                                        continue
                                    if str(st.get("conclusion") or "").strip().lower() != "failure":
                                        continue
                                    failed_step = str(st.get("name") or "").strip()
                                    break
                                break
                except Exception:
                    failed_job = ""
                    failed_step = ""

                if run_id and failed_job:
                    try:
                        _append_ui_log_entries(
                            [
                                {
                                    "type": "github_actions",
                                    "kind": "run_failed_debug",
                                    "ts": int(time.time()),
                                    "owner": owner,
                                    "repo": repo,
                                    "branch": branch,
                                    "event": event,
                                    "run_id": run_id,
                                    "conclusion": conclusion,
                                    "job": failed_job,
                                    "step": failed_step,
                                    "url": url,
                                }
                            ]
                        )
                    except Exception:
                        pass

                msg = (f"บิลด์จบแล้ว: {conclusion}" if lang == "th" else f"Build finished: {conclusion}.")
                if failed_job:
                    if lang == "th":
                        msg = msg + f" (job: {failed_job}" + (f", step: {failed_step}" if failed_step else "") + ")"
                    else:
                        msg = msg + f" (job: {failed_job}" + (f", step: {failed_step}" if failed_step else "") + ")"
            else:
                msg = "บิลด์จบแล้ว" if lang == "th" else "Build finished."

            if url:
                msg = msg + " " + url
            await _live_say(ws, msg)
        except Exception as e:
            short = str(e).strip()
            if lang == "th":
                await _live_say(ws, f"ดู GitHub Actions ไม่ได้: {short}")
            else:
                await _live_say(ws, f"GitHub Actions watch failed: {short}")

    # Cancel any in-flight watch task for this websocket.
    try:
        prev = getattr(ws.state, "github_watch_task", None)
        if isinstance(prev, asyncio.Task) and not prev.done():
            prev.cancel()
    except Exception:
        pass

    try:
        ws.state.github_watch_task = asyncio.create_task(_run_once())
    except Exception:
        await _run_once()
    return True


async def _handle_pending_reminder_confirm_or_cancel(ws: WebSocket, text: str, *, speak: bool = True) -> bool:
    pending = getattr(ws.state, "pending_reminder_setup", None)
    if not isinstance(pending, dict):
        return False

    s = " ".join(str(text or "").strip().split())
    lower = s.lower()

    is_thai = _text_is_thai(s) or _text_is_thai(str(pending.get("source_text") or ""))

    thai_confirm = s.startswith("ยืนยัน") or s.startswith("ยืนยันเตือน") or s.startswith("เตือน ยืนยัน")
    thai_cancel = s.startswith("ยกเลิก") or s.startswith("ยกเลิกเตือน") or s.startswith("เตือน ยกเลิก")
    eng_confirm = lower.startswith("reminder confirm")
    eng_cancel = lower.startswith("reminder cancel")

    if not (eng_confirm or eng_cancel or thai_confirm or thai_cancel):
        return False

    if eng_cancel or thai_cancel:
        ws.state.pending_reminder_setup = None
        await _ws_send_json(ws, {"type": "reminder_setup_cancelled", "instance_id": INSTANCE_ID})
        if speak:
            try:
                await _live_say(ws, "โอเค ฉันยกเลิกแบบร่างการแจ้งเตือนแล้ว" if is_thai else "Okay. I cancelled that reminder draft.")
            except Exception:
                pass
        return True

    when = ""
    if eng_confirm:
        m = re.search(r"^reminder\s+confirm\s*[:\-]?\s*(.*)$", s, flags=re.IGNORECASE)
        if m:
            when = str(m.group(1) or "").strip()
    elif thai_confirm:
        m = re.search(r"^ยืนยัน(?:เตือน)?\s*[:\-]?\s*(.*)$", s)
        if m:
            when = str(m.group(1) or "").strip()
        else:
            m2 = re.search(r"^เตือน\s+ยืนยัน\s*[:\-]?\s*(.*)$", s)
            if m2:
                when = str(m2.group(1) or "").strip()

    title = str(pending.get("title") or "Reminder").strip() or "Reminder"
    source_text = str(pending.get("source_text") or "").strip()
    tz_name = str(pending.get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz=timezone.utc)

    due_at_utc: Optional[datetime] = None
    local_iso: Optional[str] = None
    if when:
        due_at_utc, local_iso = _parse_time_from_text(when, now, tz)

    if due_at_utc is None:
        ws.state.pending_reminder_setup = None
        ws.state.pending_reminder_set_time = {
            "title": title,
            "source_text": source_text or s,
            "timezone": tz.key,
            "created_at": int(time.time()),
        }
        await ws.send_json(
            {
                "type": "reminder_setup",
                "title": title,
                "reminder_id": None,
                "result": {
                    "ok": True,
                    "needs_time": True,
                    "hint": "บอกเวลาได้เลย (เช่น วันนี้ 17:00 หรือ พรุ่งนี้ 09:00)" if is_thai else "Set a time (e.g. today 17:00 or tomorrow 09:00).",
                },
                "instance_id": INSTANCE_ID,
            }
        )
        if speak:
            try:
                await _live_say(
                    ws,
                    (
                        f"ยืนยันแล้ว ฉันสร้างการแจ้งเตือน: {title} แล้ว บอกเวลาได้เลย"
                        if is_thai
                        else f"Confirmed. I created the reminder: {title}. Please tell me what time."
                    ),
                )
            except Exception:
                pass
        return True

    cal = await _google_calendar_create_reminder_event(title=title, due_at_utc=due_at_utc, tz=tz, source_text=source_text or s)
    ws.state.pending_reminder_setup = None
    await _ws_send_json(
        ws,
        {
            "type": "reminder_setup",
            "title": title,
            "reminder_id": None,
            "result": {"ok": True, "calendar": cal, "local_time": local_iso, "timezone": tz.key},
            "instance_id": INSTANCE_ID,
        },
    )
    if speak:
        try:
            await _live_say(ws, f"ยืนยันแล้ว ฉันสร้างการแจ้งเตือน: {title} แล้ว" if is_thai else f"Confirmed. I created the reminder: {title}.")
        except Exception:
            pass
    return True


async def _startup_resync_from_weaviate() -> None:
    if not _weaviate_enabled():
        return
    try:
        now_ts = int(time.time())
        # Keep local scheduler warm for the next 7 days.
        items = await _weaviate_query_upcoming_reminders(
            start_ts=now_ts,
            end_ts=now_ts + 7 * 24 * 3600,
            limit=500,
        )
        for it in items:
            _upsert_local_reminder_from_memory_item(DEFAULT_USER_ID, it)
    except Exception as e:
        logger.warning("weaviate_startup_resync_failed error=%s", e)


def _parse_news_follow_command(text: str) -> dict[str, str]:
    raw = str(text or "").strip()
    s = " ".join(raw.lower().split())
    if not s:
        return {"action": "", "arg": ""}

    # English focus commands
    if s == "focus list" or s == "list focus":
        return {"action": "focus_list", "arg": ""}
    if s.startswith("focus add:") or s.startswith("focus add "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 2)[2].strip() if len(raw.split()) >= 3 else ""
        return {"action": "focus_add", "arg": arg}
    if s.startswith("focus remove:") or s.startswith("focus remove "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 2)[2].strip() if len(raw.split()) >= 3 else ""
        return {"action": "focus_remove", "arg": arg}

    if s.startswith("โฟกัสข่าว เพิ่ม:") or s.startswith("โฟกัสข่าว เพิ่ม "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 2)[2].strip() if len(raw.split()) >= 3 else ""
        return {"action": "focus_add", "arg": arg}
    if s.startswith("เพิ่มโฟกัสข่าว:") or s.startswith("เพิ่มโฟกัสข่าว "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip() if len(raw.split()) >= 2 else ""
        return {"action": "focus_add", "arg": arg}

    if s.startswith("โฟกัสข่าว ลบ:") or s.startswith("โฟกัสข่าว ลบ "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 2)[2].strip() if len(raw.split()) >= 3 else ""
        return {"action": "focus_remove", "arg": arg}
    if s.startswith("ลบโฟกัสข่าว:") or s.startswith("ลบโฟกัสข่าว "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip() if len(raw.split()) >= 2 else ""
        return {"action": "focus_remove", "arg": arg}

    if s == "โฟกัสข่าว" or s == "รายการโฟกัสข่าว":
        return {"action": "focus_list", "arg": ""}

    if s.startswith("รายงานข่าว:") or s.startswith("รายงานข่าว "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip() if len(raw.split()) >= 2 else ""
        return {"action": "report", "arg": arg}

    if s.startswith("report:") or s.startswith("report "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip() if len(raw.split()) >= 2 else ""
        return {"action": "report", "arg": arg}

    if "รีเฟรช" in s or "refresh" in s:
        if "ติดตามข่าว" in s or "follow_news" in s or "follow news" in s or "track news" in s:
            return {"action": "refresh", "arg": ""}

    if "ติดตามข่าว" in s or "สรุปข่าวติดตาม" in s or "follow_news" in s or "follow news" in s or "news follow" in s or "track news" in s:
        return {"action": "list", "arg": ""}

    return {"action": "", "arg": ""}


def _news_follow_cache_key_focus(user_id: str) -> str:
    return f"news-follow::{user_id}::focus"


def _news_follow_cache_key_summaries(user_id: str) -> str:
    return f"news-follow::{user_id}::summaries"


def _extract_note_text(text: str) -> Optional[str]:
    raw = str(text or "").strip()
    if not raw:
        return None
    s = " ".join(raw.split())
    lower = s.lower()

    eng_triggers = ("make a note",)
    thai_triggers = ("สร้างบันทึก", "จดบันทึก")
    # Speech-to-text frequently inserts spaces between Thai words, e.g. "จด บันทึก".
    # Also accept common Thai "note" variants.
    thai_note_patterns = (
        r"^(?:ช่วย\s*)?(?:จด\s*บันทึก|สร้าง\s*บันทึก)\s*[:\-]?\s*(.*)$",
        r"^(?:ช่วย\s*)?(?:จด\s*โน้ต|สร้าง\s*โน้ต)\s*[:\-]?\s*(.*)$",
        r"^(?:ช่วย\s*)?สร้าง\s*เป็น\s*โน้ต\s*[:\-]?\s*(.*)$",
    )

    for trig in eng_triggers:
        if lower.startswith(trig):
            rest = s[len(trig) :].strip()
            if rest.startswith(":") or rest.startswith("-"):
                rest = rest[1:].strip()
            return rest or None

    for pat in thai_note_patterns:
        m = re.search(pat, s)
        if m:
            rest = str(m.group(1) or "").strip()
            return rest or None

    for trig in thai_triggers:
        if s.startswith(trig):
            rest = s[len(trig) :].strip()
            if rest.startswith(":") or rest.startswith("-"):
                rest = rest[1:].strip()
            return rest or None

    for trig in eng_triggers:
        idx = lower.find(trig)
        if idx >= 0:
            rest = s[idx + len(trig) :].strip()
            if rest.startswith(":") or rest.startswith("-"):
                rest = rest[1:].strip()
            return rest or None

    for trig in thai_triggers:
        idx = s.find(trig)
        if idx >= 0:
            rest = s[idx + len(trig) :].strip()
            if rest.startswith(":") or rest.startswith("-"):
                rest = rest[1:].strip()
            return rest or None

    return None


def _is_note_trigger(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    s = " ".join(raw.split())
    lower = s.lower()

    if lower.startswith("make a note") or "make a note" in lower:
        return True

    # Keep in sync with _extract_note_text.
    thai_note_patterns = (
        r"^(?:ช่วย\s*)?(?:จด\s*บันทึก|สร้าง\s*บันทึก)\s*(?:[:\-]\s*)?(.*)$",
        r"^(?:ช่วย\s*)?(?:จด\s*โน้ต|สร้าง\s*โน้ต)\s*(?:[:\-]\s*)?(.*)$",
        r"^(?:ช่วย\s*)?สร้าง\s*เป็น\s*โน้ต\s*(?:[:\-]\s*)?(.*)$",
    )
    for pat in thai_note_patterns:
        if re.search(pat, s):
            return True

    thai_triggers = ("สร้างบันทึก", "จดบันทึก")
    for trig in thai_triggers:
        if trig in s:
            return True
    return False


def _notes_policy_text_from_sys_kv(sys_kv: Any) -> str:
    if not isinstance(sys_kv, dict):
        return ""
    enabled_raw = str(sys_kv.get("policy.notes_ssot") or "").strip()
    if enabled_raw and not _parse_bool_cell(enabled_raw):
        return ""
    # If key is missing, keep disabled by default.
    if not enabled_raw:
        return ""
    txt = str(sys_kv.get("policy.notes_ssot_text") or "").strip()
    return txt


def _is_notes_check_trigger(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    s = " ".join(raw.split()).strip()
    sl = s.lower()
    # English.
    if sl in {"notes", "notes latest", "notes list", "check notes", "check note"}:
        return True
    if sl.startswith("notes ") or sl.startswith("check notes"):
        return True
    # Thai.
    if s in {"บันทึก", "โน้ต", "เช็คบันทึก", "ดูบันทึก", "บันทึกล่าสุด", "โน้ตล่าสุด"}:
        return True
    if s.startswith("บันทึก ") or s.startswith("โน้ต ") or s.startswith("ดูบันทึก"):
        return True
    return False


async def _handle_notes_check(ws: WebSocket, text: str) -> bool:
    if not _is_notes_check_trigger(text):
        return False

    sys_kv = getattr(ws.state, "sys_kv", None)
    spreadsheet_id = ""
    if isinstance(sys_kv, dict):
        spreadsheet_id = str(sys_kv.get("notes_ss") or "").strip()
    if not spreadsheet_id:
        spreadsheet_id = _system_spreadsheet_id()

    if not spreadsheet_id:
        await _ws_send_json(
            ws,
            {
                "type": "text",
                "text": "missing_notes_ss" if not _text_is_thai(text) else "ไม่พบสเปรดชีตบันทึก (missing_notes_ss)",
                "instance_id": INSTANCE_ID,
            },
        )
        return True

    sheet_name = ""
    if isinstance(sys_kv, dict):
        sheet_name = str(sys_kv.get("notes.sheet_name") or sys_kv.get("notes_sh") or "").strip()
    if not sheet_name:
        await _ws_send_json(
            ws,
            {
                "type": "text",
                "text": "missing_notes_sheet_name" if not _text_is_thai(text) else "ไม่พบชื่อชีตบันทึก (missing_notes_sheet_name)",
                "instance_id": INSTANCE_ID,
            },
        )
        return True

    try:
        rows = await _load_sheet_table(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name, max_rows=250, max_cols="S")
    except Exception as e:
        await _ws_send_json(
            ws,
            {
                "type": "text",
                "text": ("notes_read_failed" if not _text_is_thai(text) else "อ่านบันทึกไม่สำเร็จ") + f": {str(e)[:160]}",
                "instance_id": INSTANCE_ID,
            },
        )
        return True

    if not rows or not isinstance(rows[0], list):
        await _ws_send_json(
            ws,
            {
                "type": "text",
                "text": "notes_empty" if not _text_is_thai(text) else "ยังไม่มีบันทึก",
                "instance_id": INSTANCE_ID,
            },
        )
        return True

    header = rows[0]
    idx = _idx_from_header(header)
    col_dt = idx.get("date_time")
    col_subject = idx.get("subject")
    col_notes = idx.get("notes")
    col_status = idx.get("status")
    col_assignee = idx.get("assignee")
    col_result = idx.get("result")

    items: list[dict[str, Any]] = []
    for i, r in enumerate(rows[1:], start=2):
        if not isinstance(r, list) or not r:
            continue
        dt = str(r[col_dt] if col_dt is not None and col_dt < len(r) else "").strip()
        subject = str(r[col_subject] if col_subject is not None and col_subject < len(r) else "").strip()
        notes = str(r[col_notes] if col_notes is not None and col_notes < len(r) else "").strip()
        status = str(r[col_status] if col_status is not None and col_status < len(r) else "").strip().lower()
        assignee = str(r[col_assignee] if col_assignee is not None and col_assignee < len(r) else "").strip().lower()
        result = str(r[col_result] if col_result is not None and col_result < len(r) else "").strip()
        if not (dt or subject or notes or status or result):
            continue
        items.append(
            {
                "row": i,
                "date_time": dt,
                "subject": subject,
                "notes": notes,
                "status": status,
                "assignee": assignee,
                "result": result,
            }
        )

    def _sort_key(it: dict[str, Any]) -> tuple[int, int]:
        # Prefer sortable ISO dt, but fall back to row order.
        dt = str(it.get("date_time") or "").strip()
        # Descending.
        return (0 if dt else 1, -int(it.get("row") or 0))

    # Latest notes (best-effort): keep last 10 by sheet order.
    latest = sorted(items, key=lambda it: int(it.get("row") or 0), reverse=True)[:10]
    open_jobs = [
        it
        for it in items
        if str(it.get("status") or "").lower() in {"new", "doing"}
    ]
    open_jobs = sorted(open_jobs, key=lambda it: int(it.get("row") or 0))[:10]

    next_line = ""
    if open_jobs:
        top = open_jobs[0]
        body = str(top.get("notes") or "").strip() or str(top.get("subject") or "").strip()
        if body:
            next_line = ("Next: " if not _text_is_thai(text) else "ถัดไป: ") + body
    elif latest:
        top = latest[0]
        body = str(top.get("notes") or "").strip() or str(top.get("result") or "").strip()
        if body:
            next_line = ("Next: " if not _text_is_thai(text) else "ถัดไป: ") + body

    lines: list[str] = []
    if not _text_is_thai(text):
        lines.append(f"Notes SSOT: {sheet_name}")
        if open_jobs:
            lines.append("Open:")
            for it in open_jobs[:5]:
                body = str(it.get("notes") or "").strip() or str(it.get("subject") or "").strip()
                if not body:
                    continue
                lines.append(f"- ({it.get('status')}) {body}")
        if latest:
            lines.append("Latest:")
            for it in latest[:5]:
                body = str(it.get("notes") or "").strip() or str(it.get("result") or "").strip()
                if not body:
                    continue
                lines.append(f"- {body}")
    else:
        lines.append(f"บันทึก (SSoT): {sheet_name}")
        if open_jobs:
            lines.append("งานค้าง:")
            for it in open_jobs[:5]:
                body = str(it.get("notes") or "").strip() or str(it.get("subject") or "").strip()
                if not body:
                    continue
                lines.append(f"- ({it.get('status')}) {body}")
        if latest:
            lines.append("ล่าสุด:")
            for it in latest[:5]:
                body = str(it.get("notes") or "").strip() or str(it.get("result") or "").strip()
                if not body:
                    continue
                lines.append(f"- {body}")

    if next_line:
        lines.append("")
        lines.append(next_line)

    await _ws_send_json(ws, {"type": "text", "text": "\n".join(lines).strip(), "instance_id": INSTANCE_ID})
    return True


async def _handle_notes_next(ws: WebSocket, text: str) -> bool:
    # Compact variant of notes check: emit only the single next step line.
    sys_kv = getattr(ws.state, "sys_kv", None)
    spreadsheet_id = ""
    if isinstance(sys_kv, dict):
        spreadsheet_id = str(sys_kv.get("notes_ss") or "").strip()
    if not spreadsheet_id:
        spreadsheet_id = _system_spreadsheet_id()
    if not spreadsheet_id:
        await _ws_send_json(
            ws,
            {
                "type": "text",
                "text": "missing_notes_ss" if not _text_is_thai(text) else "ไม่พบสเปรดชีตบันทึก (missing_notes_ss)",
                "instance_id": INSTANCE_ID,
            },
        )
        return True

    sheet_name = ""
    if isinstance(sys_kv, dict):
        sheet_name = str(sys_kv.get("notes.sheet_name") or sys_kv.get("notes_sh") or "").strip()
    if not sheet_name:
        await _ws_send_json(
            ws,
            {
                "type": "text",
                "text": "missing_notes_sheet_name" if not _text_is_thai(text) else "ไม่พบชื่อชีตบันทึก (missing_notes_sheet_name)",
                "instance_id": INSTANCE_ID,
            },
        )
        return True

    try:
        rows = await _load_sheet_table(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name, max_rows=250, max_cols="S")
    except Exception as e:
        await _ws_send_json(
            ws,
            {
                "type": "text",
                "text": ("notes_read_failed" if not _text_is_thai(text) else "อ่านบันทึกไม่สำเร็จ") + f": {str(e)[:160]}",
                "instance_id": INSTANCE_ID,
            },
        )
        return True

    if not rows or not isinstance(rows[0], list):
        await _ws_send_json(
            ws,
            {
                "type": "text",
                "text": "notes_empty" if not _text_is_thai(text) else "ยังไม่มีบันทึก",
                "instance_id": INSTANCE_ID,
            },
        )
        return True

    header = rows[0]
    idx = _idx_from_header(header)
    col_subject = idx.get("subject")
    col_notes = idx.get("notes")
    col_status = idx.get("status")
    col_result = idx.get("result")

    items: list[dict[str, Any]] = []
    for i, r in enumerate(rows[1:], start=2):
        if not isinstance(r, list) or not r:
            continue
        subject = str(r[col_subject] if col_subject is not None and col_subject < len(r) else "").strip()
        notes = str(r[col_notes] if col_notes is not None and col_notes < len(r) else "").strip()
        status = str(r[col_status] if col_status is not None and col_status < len(r) else "").strip().lower()
        result = str(r[col_result] if col_result is not None and col_result < len(r) else "").strip()
        if not (subject or notes or status or result):
            continue
        items.append({"row": i, "subject": subject, "notes": notes, "status": status, "result": result})

    open_jobs = [it for it in items if str(it.get("status") or "").lower() in {"new", "doing"}]
    open_jobs = sorted(open_jobs, key=lambda it: int(it.get("row") or 0))[:10]
    latest = sorted(items, key=lambda it: int(it.get("row") or 0), reverse=True)[:10]

    next_line = ""
    if open_jobs:
        top = open_jobs[0]
        body = str(top.get("notes") or "").strip() or str(top.get("subject") or "").strip()
        if body:
            next_line = ("Next: " if not _text_is_thai(text) else "ถัดไป: ") + body
    elif latest:
        top = latest[0]
        body = str(top.get("notes") or "").strip() or str(top.get("result") or "").strip()
        if body:
            next_line = ("Next: " if not _text_is_thai(text) else "ถัดไป: ") + body

    await _ws_send_json(
        ws,
        {
            "type": "text",
            "text": next_line or ("Next: (none)" if not _text_is_thai(text) else "ถัดไป: (ไม่มี)"),
            "instance_id": INSTANCE_ID,
        },
    )
    return True


async def _handle_system_reload_mode(ws: WebSocket, mode: str, trace_id: str | None = None) -> None:
    m = str(mode or "").strip().lower() or "full"
    if m in {"full", "all"}:
        await _handle_reload_system(ws, "Reload System")
        return

    if m in {"sys", "system"}:
        if _reload_system_lock.locked():
            await _ws_send_json(ws, {"type": "text", "text": "Reload: already running", "instance_id": INSTANCE_ID}, trace_id=trace_id)
            try:
                await _maybe_capture_to_memory(ws, key="runtime.system.reload.latest", value="Reload: already running", source="system.reload")
            except Exception:
                pass
            return
        async with _reload_system_lock:
            try:
                await _ws_send_json(ws, {"type": "text", "text": "Reload sys: start", "instance_id": INSTANCE_ID}, trace_id=trace_id)
                try:
                    await _maybe_capture_to_memory(ws, key="runtime.system.reload.latest", value="Reload sys: start", source="system.reload")
                except Exception:
                    pass
            except Exception:
                pass
            try:
                await _load_ws_system_kv(ws)
                await _ws_send_json(ws, {"type": "text", "text": "Reload sys: ok", "instance_id": INSTANCE_ID}, trace_id=trace_id)
                try:
                    await _maybe_capture_to_memory(ws, key="runtime.system.reload.latest", value="Reload sys: ok", source="system.reload")
                except Exception:
                    pass
            except Exception as e:
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "reload_failed",
                        "message": "Reload sys failed",
                        "detail": str(e),
                        "instance_id": INSTANCE_ID,
                    },
                    trace_id=trace_id,
                )
                try:
                    await _maybe_capture_to_memory(ws, key="runtime.system.reload.latest", value=f"Reload sys failed: {str(e)}", source="system.reload")
                except Exception:
                    pass
            return

    # Note: today memory+knowledge are loaded together by _load_ws_sheet_memory.
    if m in {"memory", "knowledge"}:
        if _reload_system_lock.locked():
            await _ws_send_json(ws, {"type": "text", "text": "Reload: already running", "instance_id": INSTANCE_ID}, trace_id=trace_id)
            try:
                await _maybe_capture_to_memory(ws, key="runtime.system.reload.latest", value="Reload: already running", source="system.reload")
            except Exception:
                pass
            return
        async with _reload_system_lock:
            try:
                await _ws_send_json(ws, {"type": "text", "text": f"Reload {m}: start", "instance_id": INSTANCE_ID}, trace_id=trace_id)
                try:
                    await _maybe_capture_to_memory(ws, key="runtime.system.reload.latest", value=f"Reload {m}: start", source="system.reload")
                except Exception:
                    pass
            except Exception:
                pass
            try:
                _clear_sheet_caches()
            except Exception:
                pass
            try:
                await _load_ws_sheet_memory(ws)
                lang = str(getattr(ws.state, "user_lang", "") or "").strip() or "en"
                await _ws_send_json(ws, {"type": "text", "text": _memory_load_status_line(ws, lang), "instance_id": INSTANCE_ID}, trace_id=trace_id)
                await _ws_send_json(ws, {"type": "text", "text": f"Reload {m}: ok", "instance_id": INSTANCE_ID}, trace_id=trace_id)
                try:
                    await _maybe_capture_to_memory(ws, key="runtime.system.reload.latest", value=f"Reload {m}: ok", source="system.reload")
                except Exception:
                    pass
            except Exception as e:
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "reload_failed",
                        "message": f"Reload {m} failed",
                        "detail": str(e),
                        "instance_id": INSTANCE_ID,
                    },
                    trace_id=trace_id,
                )
                try:
                    await _maybe_capture_to_memory(ws, key="runtime.system.reload.latest", value=f"Reload {m} failed: {str(e)}", source="system.reload")
                except Exception:
                    pass
            return

    if m in {"gems", "gem"}:
        try:
            await _ws_send_json(ws, {"type": "text", "text": "Reload gems: start", "instance_id": INSTANCE_ID}, trace_id=trace_id)
            try:
                await _maybe_capture_to_memory(ws, key="runtime.system.reload.latest", value="Reload gems: start", source="system.reload")
            except Exception:
                pass
        except Exception:
            pass
        try:
            sys_kv = getattr(ws.state, "sys_kv", None)
            payload = await _load_sheet_gems(sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
            try:
                _set_cached_sheet_gems(payload)
            except Exception:
                pass
            await _ws_send_json(ws, {"type": "text", "text": "Reload gems: ok", "instance_id": INSTANCE_ID}, trace_id=trace_id)
            try:
                await _maybe_capture_to_memory(ws, key="runtime.system.reload.latest", value="Reload gems: ok", source="system.reload")
            except Exception:
                pass
        except Exception as e:
            await _ws_send_json(
                ws,
                {"type": "error", "kind": "reload_gems_failed", "message": "Reload gems failed", "detail": str(e), "instance_id": INSTANCE_ID},
                trace_id=trace_id,
            )
            try:
                await _maybe_capture_to_memory(ws, key="runtime.system.reload.latest", value=f"Reload gems failed: {str(e)}", source="system.reload")
            except Exception:
                pass
        return

    await _ws_send_json(
        ws,
        {"type": "error", "kind": "invalid_reload_mode", "message": f"invalid_reload_mode: {m}", "instance_id": INSTANCE_ID},
        trace_id=trace_id,
    )


async def _sys_kv_upsert_sheet(*, key: str, value: str, dry_run: bool = False) -> dict[str, Any]:
    k = str(key or "").strip()
    v = str(value or "").strip()
    if not k:
        return {"ok": False, "error": "missing_key"}

    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

    def _norm_k(s: Any) -> str:
        try:
            ss = str(s or "").strip()
            # Normalize common copy/paste oddities.
            ss = re.sub(r"[\u00A0\u200B-\u200D\uFEFF]+", "", ss)
            ss = " ".join(ss.split())
            return ss
        except Exception:
            try:
                return str(s or "").strip()
            except Exception:
                return ""

    spreadsheet_id = _system_spreadsheet_id()
    if not spreadsheet_id:
        return {"ok": False, "error": "missing_spreadsheet"}
    sys_sheet = _system_sheet_name()

    tool_get = _pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
    # Try to be header-aware to avoid overwriting unrelated columns (e.g. created_at/updated_at).
    # If we can't detect headers, we fall back to KV5 A:E behavior.
    res = await _mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sys_sheet}!A:Z"})
    parsed = _mcp_text_json(res)
    if not isinstance(parsed, dict):
        return {"ok": False, "error": "values_get_invalid_response"}
    values = parsed.get("values")
    if not isinstance(values, list) or not values:
        # If sheet is empty, just append.
        values = []

    def _col_letter(n: int) -> str:
        s = ""
        x = int(n)
        while x > 0:
            x, r = divmod(x - 1, 26)
            s = chr(ord("A") + r) + s
        return s

    def _ensure_len(row_in: list[Any], n: int) -> list[Any]:
        out = list(row_in)
        while len(out) < n:
            out.append("")
        return out

    header: list[str] = []
    idx: dict[str, int] = {}
    if values and isinstance(values[0], list):
        header = [str(c or "").strip().lower() for c in values[0]]
        for i, col in enumerate(header):
            if col:
                idx[col] = i

    def _get_col(name: str) -> Optional[int]:
        j = idx.get(name)
        if j is None:
            return None
        try:
            return int(j)
        except Exception:
            return None

    key_col = _get_col("key")
    val_col = _get_col("value")
    enabled_col = _get_col("enabled")
    scope_col = _get_col("scope")
    priority_col = _get_col("priority")
    created_at_col = _get_col("created_at")
    updated_at_col = _get_col("updated_at")

    header_mode = key_col is not None and val_col is not None

    # Sys sheet may or may not include a header row. We only skip row 1 if it looks like a header.
    start_row = 1
    try:
        if header_mode:
            start_row = 2
        elif values and isinstance(values[0], list) and values[0]:
            h0 = _norm_k(values[0][0]).lower()
            h1 = _norm_k(values[0][1]).lower() if len(values[0]) > 1 else ""
            h2 = _norm_k(values[0][2]).lower() if len(values[0]) > 2 else ""
            if h0 in {"key", "k"} and (not h1 or h1 in {"value", "v"}) and (not h2 or h2 in {"enabled", "enable"}):
                start_row = 2
    except Exception:
        start_row = 1

    row_idx: Optional[int] = None
    nk = _norm_k(k)
    for i, r in enumerate(values, start=1):
        if i < start_row:
            continue
        if not isinstance(r, list) or not r:
            continue
        if header_mode:
            rr = _ensure_len(r, max(1, len(header)))
            if _norm_k(rr[key_col]) == nk:
                row_idx = i
                break
        elif _norm_k(r[0]) == nk:
            row_idx = i
            break

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "spreadsheet_id": spreadsheet_id,
            "sheet": sys_sheet,
            "action": "update" if row_idx else "append",
            "row": row_idx,
            "key": k,
            "value": v,
        }

    if header_mode:
        col_count = max(1, len(header))
        base_row: list[Any] = []
        if row_idx and isinstance(values, list) and row_idx - 1 < len(values) and isinstance(values[row_idx - 1], list):
            base_row = _ensure_len(values[row_idx - 1], col_count)
        out_row = _ensure_len(base_row, col_count)

        out_row[key_col] = k
        out_row[val_col] = v
        if enabled_col is not None:
            out_row[enabled_col] = "true"
        if scope_col is not None:
            prev_scope = str(out_row[scope_col] or "").strip()
            out_row[scope_col] = prev_scope if prev_scope else "global"
        if priority_col is not None:
            prev_pr = str(out_row[priority_col] or "").strip()
            out_row[priority_col] = prev_pr if prev_pr else "0"

        if created_at_col is not None:
            prev = str(out_row[created_at_col] or "").strip()
            if not prev:
                out_row[created_at_col] = now_iso
        if updated_at_col is not None:
            out_row[updated_at_col] = now_iso

        last_col = _col_letter(col_count)
        if row_idx:
            tool_upd2 = _pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
            rng2 = f"{sys_sheet}!A{row_idx}:{last_col}{row_idx}"
            res_hu = await _mcp_tools_call(
                tool_upd2,
                {
                    "spreadsheet_id": spreadsheet_id,
                    "range": rng2,
                    "values": [out_row],
                    "value_input_option": "RAW",
                },
            )
            parsed_hu = _mcp_text_json(res_hu)
            return {
                "ok": True,
                "spreadsheet_id": spreadsheet_id,
                "sheet": sys_sheet,
                "action": "update",
                "row": row_idx,
                "range": rng2,
                "response": parsed_hu if isinstance(parsed_hu, dict) else {"raw": parsed_hu},
            }

        tool_app2 = _pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
        res_ha = await _mcp_tools_call(
            tool_app2,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sys_sheet}!A:{last_col}",
                "values": [out_row],
                "value_input_option": "RAW",
            },
        )
        parsed_ha = _mcp_text_json(res_ha)
        return {
            "ok": True,
            "spreadsheet_id": spreadsheet_id,
            "sheet": sys_sheet,
            "action": "append",
            "key": k,
            "value": v,
            "response": parsed_ha if isinstance(parsed_ha, dict) else {"raw": parsed_ha},
        }

    if row_idx:
        tool_upd = _pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
        rng = f"{sys_sheet}!A{row_idx}:E{row_idx}"

        existing: list[Any] = []
        try:
            existing = values[row_idx - 1] if isinstance(values, list) and row_idx - 1 < len(values) else []
        except Exception:
            existing = []

        # Preserve scope/priority if present.
        scope = str(existing[3]).strip() if len(existing) > 3 and str(existing[3]).strip() else "global"
        priority = str(existing[4]).strip() if len(existing) > 4 and str(existing[4]).strip() else "0"

        res2 = await _mcp_tools_call(
            tool_upd,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": rng,
                "values": [[k, v, "true", scope, priority]],
                "value_input_option": "RAW",
            },
        )
        parsed2 = _mcp_text_json(res2)
        return {
            "ok": True,
            "spreadsheet_id": spreadsheet_id,
            "sheet": sys_sheet,
            "action": "update",
            "row": row_idx,
            "range": rng,
            "response": parsed2 if isinstance(parsed2, dict) else {"raw": parsed2},
        }

    tool_app = _pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
    res3 = await _mcp_tools_call(
        tool_app,
        {
            "spreadsheet_id": spreadsheet_id,
            "range": f"{sys_sheet}!A:E",
            "values": [[k, v, "true", "global", "0"]],
            "value_input_option": "RAW",
        },
    )
    parsed3 = _mcp_text_json(res3)
    return {
        "ok": True,
        "spreadsheet_id": spreadsheet_id,
        "sheet": sys_sheet,
        "action": "append",
        "key": k,
        "value": v,
        "response": parsed3 if isinstance(parsed3, dict) else {"raw": parsed3},
    }


async def _handle_local_tools_message(ws: WebSocket, msg: dict[str, Any], trace_id: str | None = None) -> bool:
    tid = _ws_ensure_trace_id(ws, trace_id)
    msg_type = str(msg.get("type") or "").strip().lower()
    if msg_type == "system":
        action = str(msg.get("action") or "").strip().lower()
        if action == "reload":
            mode = str(msg.get("mode") or "full")
            await _handle_system_reload_mode(ws, mode, trace_id=tid)
            await _ws_voice_job_done(ws, tid)
            return True
        if action in {"module_status_report", "module_status", "modules_status", "status_report"}:
            sys_kv = getattr(ws.state, "sys_kv", None)
            try:
                items = await _portainer_list_stack_containers(sys_kv=sys_kv)
            except HTTPException as e:
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "module_status_report_failed",
                        "message": "module_status_report_failed",
                        "detail": e.detail,
                        "instance_id": INSTANCE_ID,
                    },
                    trace_id=tid,
                )
                await _ws_voice_job_done(ws, tid)
                return True
            except Exception as e:
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "module_status_report_failed",
                        "message": "module_status_report_failed",
                        "detail": str(e),
                        "instance_id": INSTANCE_ID,
                    },
                    trace_id=tid,
                )
                await _ws_voice_job_done(ws, tid)
                return True

            lines: list[str] = []
            ok_n = 0
            bad_n = 0
            for it in items:
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name") or it.get("service") or "").strip()
                status = str(it.get("status") or "").strip() or "unknown"
                health = str(it.get("health") or "").strip() or "unknown"
                if health in {"healthy", "ok"} or status in {"running", "up", "online"}:
                    ok_n += 1
                if health in {"unhealthy"} or status in {"exited", "dead"}:
                    bad_n += 1
                lines.append(f"- {name}: {status} / {health}")

            title = "System module status report"
            report = title + "\n" + "\n".join(lines) if lines else title + "\n(no containers found)"
            await _ws_send_json(ws, {"type": "text", "text": report, "instance_id": INSTANCE_ID}, trace_id=tid)
            try:
                await _maybe_capture_to_memory(ws, key="runtime.module_status_report.latest", value=report, source="system.module_status_report")
            except Exception:
                pass

            voice = f"Module status report. {ok_n} ok. {bad_n} issues.".strip()
            try:
                await _live_say(ws, voice)
            except Exception:
                pass
            await _ws_voice_job_done(ws, tid)
            return True
        if action in {"clear_job", "clear", "cancel_job", "cancel"}:
            await _ws_send_json(
                ws,
                {
                    "type": "text",
                    "text": "system.clear_job: reconnecting",
                    "instance_id": INSTANCE_ID,
                },
                trace_id=tid,
            )
            try:
                await _maybe_capture_to_memory(ws, key="runtime.system.clear_job.latest", value="system.clear_job: reconnecting", source="system.clear_job")
            except Exception:
                pass
            # Ask the frontend to reconnect, which effectively clears any in-flight Gemini Live job.
            await _ws_send_json(
                ws,
                {
                    "type": "reconnect",
                    "reason": "system_clear_job",
                    "instance_id": INSTANCE_ID,
                },
                trace_id=tid,
            )
            await _ws_voice_job_done(ws, tid)
            return True
        if action in {"sys_kv_set", "syskv_set", "sys_set"}:
            sys_kv = getattr(ws.state, "sys_kv", None)
            enabled_raw = ""
            if isinstance(sys_kv, dict):
                enabled_raw = str(sys_kv.get("sys_kv.write.enabled") or "").strip()
            # If key is missing, attempt a one-time refresh from the sheet. This helps when
            # the user has just added sys_kv.write.enabled in the sheet but the websocket
            # session still has a stale sys_kv snapshot.
            if not enabled_raw:
                try:
                    fresh = await _load_sys_kv_from_sheet()
                    if isinstance(fresh, dict) and fresh:
                        ws.state.sys_kv = fresh
                        enabled_raw = str(fresh.get("sys_kv.write.enabled") or "").strip()
                except Exception:
                    pass
            if enabled_raw and not _parse_bool_cell(enabled_raw):
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "sys_kv_write_disabled",
                        "message": "sys_kv_write_disabled",
                        "detail": "Enable via sys sheet key sys_kv.write.enabled=true",
                        "instance_id": INSTANCE_ID,
                    },
                    trace_id=tid,
                )
                return True
            # If key is missing, keep disabled by default.
            if not enabled_raw:
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "sys_kv_write_disabled",
                        "message": "sys_kv_write_disabled",
                        "detail": "Missing sys sheet key sys_kv.write.enabled (default disabled)",
                        "instance_id": INSTANCE_ID,
                    },
                    trace_id=tid,
                )
                return True

            k = str(msg.get("key") or "").strip()
            v = str(msg.get("value") or "").strip()
            dry_run = bool(msg.get("dry_run") is True)
            try:
                result = await _sys_kv_upsert_sheet(key=k, value=v, dry_run=dry_run)
            except Exception as e:
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "sys_kv_set_failed",
                        "message": "sys_kv_set_failed",
                        "detail": str(e),
                        "instance_id": INSTANCE_ID,
                    },
                    trace_id=tid,
                )
                return True
            if not isinstance(result, dict) or not result.get("ok"):
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "sys_kv_set_failed",
                        "message": "sys_kv_set_failed",
                        "detail": str((result or {}).get("error") or "unknown"),
                        "instance_id": INSTANCE_ID,
                    },
                    trace_id=tid,
                )
                return True
            await _ws_send_json(
                ws,
                {
                    "type": "text",
                    "text": f"sys_kv_set ok: {k}={v}" + (" (dry_run)" if dry_run else ""),
                    "instance_id": INSTANCE_ID,
                    "sys_kv_set": result,
                },
                trace_id=tid,
            )
            # Refresh sys_kv state + global cache so HTTP endpoints (e.g., /config/voice_commands)
            # reflect the new values immediately.
            if not dry_run:
                try:
                    fresh = await _load_sys_kv_from_sheet()
                    if isinstance(fresh, dict) and fresh:
                        try:
                            ws.state.sys_kv = fresh
                        except Exception:
                            pass
                        _set_cached_sys_kv_only(fresh)
                except Exception:
                    pass
            try:
                await _maybe_capture_to_memory(
                    ws,
                    key="runtime.system.sys_kv_set.latest",
                    value=f"sys_kv_set ok: {k}={v}" + (" (dry_run)" if dry_run else ""),
                    source="system.sys_kv_set",
                )
            except Exception:
                pass
            await _ws_voice_job_done(ws, tid)
            return True
        await _ws_send_json(
            ws,
            {"type": "error", "kind": "invalid_system_action", "message": f"invalid_system_action: {action}", "instance_id": INSTANCE_ID},
            trace_id=tid,
        )
        try:
            await _maybe_capture_to_memory(ws, key="runtime.system.invalid_action.latest", value=f"invalid_system_action: {action}", source="system.invalid_action")
        except Exception:
            pass
        return True

    if msg_type == "notes":
        action = str(msg.get("action") or "").strip().lower()
        if action in {"check", "latest", "list"}:
            await _handle_notes_check(ws, "notes")
            await _ws_voice_job_done(ws, tid)
            return True
        if action in {"next"}:
            await _handle_notes_next(ws, "notes")
            await _ws_voice_job_done(ws, tid)
            return True
        if action in {"add", "create"}:
            body = str(msg.get("text") or msg.get("note") or "").strip()
            if not body:
                await _ws_send_json(
                    ws,
                    {"type": "error", "kind": "notes_missing_text", "message": "notes_missing_text", "instance_id": INSTANCE_ID},
                    trace_id=tid,
                )
                return True
            await _handle_note_trigger(ws, f"make a note: {body}", speak=False)
            await _ws_voice_job_done(ws, tid)
            return True
        await _ws_send_json(
            ws,
            {"type": "error", "kind": "invalid_notes_action", "message": f"invalid_notes_action: {action}", "instance_id": INSTANCE_ID},
            trace_id=tid,
        )
        return True

    if msg_type == "reminders":
        action = str(msg.get("action") or "").strip().lower()

        def _pick_rid() -> str:
            rid0 = str(msg.get("reminder_id") or "").strip()
            if rid0:
                return rid0
            rid1 = str(getattr(ws.state, "last_selected_reminder_id", "") or "").strip()
            if rid1:
                return rid1
            rid2 = str(getattr(ws.state, "last_reminder_id", "") or "").strip()
            return rid2

        if action in {"add", "create"}:
            payload = str(msg.get("text") or "").strip()
            if not payload:
                await _ws_send_json(
                    ws,
                    {"type": "error", "kind": "reminders_missing_text", "message": "reminders_missing_text", "instance_id": INSTANCE_ID},
                    trace_id=tid,
                )
                return True
            # Reuse existing reminder setup pipeline (calendar event if time present, else task) but suppress speech.
            await _handle_reminder_setup_trigger(ws, f"reminder setup: {payload}", speak=False)
            await _ws_voice_job_done(ws, tid)
            return True

        await _ws_send_json(
            ws,
            {
                "type": "error",
                "kind": "reminders_legacy_removed",
                "message": "reminders_legacy_removed",
                "instance_id": INSTANCE_ID,
            },
            trace_id=tid,
        )
        return True

    if msg_type == "gems":
        action = str(msg.get("action") or "").strip().lower()
        sys_kv = getattr(ws.state, "sys_kv", None)
        try:
            _gems_drafts_prune()
        except Exception:
            pass
        ss_id = _system_spreadsheet_id()
        sh_name = "gems"
        if isinstance(sys_kv, dict) and sys_kv:
            ss_id = str(sys_kv.get("gems_ss") or ss_id).strip()
            sh_name = str(sys_kv.get("gems_sh") or sh_name).strip() or "gems"
        if not ss_id:
            await _ws_send_json(ws, {"type": "error", "kind": "gems_missing_spreadsheet", "message": "gems_missing_spreadsheet", "instance_id": INSTANCE_ID}, trace_id=tid)
            return True

        if action in {"list", "ls"}:
            payload = await _load_sheet_gems(sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
            try:
                _set_cached_sheet_gems(payload)
            except Exception:
                pass
            gems = payload.get("gems") if isinstance(payload, dict) else None
            out = []
            if isinstance(gems, dict):
                for gid in sorted(gems.keys()):
                    g = gems.get(gid)
                    if isinstance(g, dict):
                        out.append({"id": g.get("id"), "name": g.get("name"), "purpose": g.get("purpose")})
            await _ws_send_json(ws, {"type": "gems_list", "items": out, "source": payload.get("source") if isinstance(payload, dict) else None, "instance_id": INSTANCE_ID}, trace_id=tid)
            await _ws_voice_job_done(ws, tid)
            return True

        if action in {"add", "create", "update", "upsert"}:
            gem = msg.get("gem") if isinstance(msg.get("gem"), dict) else None
            if not isinstance(gem, dict):
                await _ws_send_json(ws, {"type": "error", "kind": "gems_missing_gem", "message": "gems_missing_gem", "instance_id": INSTANCE_ID}, trace_id=tid)
                return True
            gem_id = _normalize_gem_id(gem.get("id") or gem.get("gem_id"))
            if not gem_id:
                await _ws_send_json(ws, {"type": "error", "kind": "gems_missing_id", "message": "gems_missing_id", "instance_id": INSTANCE_ID}, trace_id=tid)
                return True

            header, row_num, idx = await _sheet_gems_find_row(spreadsheet_id=ss_id, sheet_name=sh_name, gem_id=gem_id)
            row = _sheet_gems_build_row(header=header, idx=idx, gem={**gem, "id": gem_id})
            if row_num <= 0:
                res = await _sheet_gems_append(spreadsheet_id=ss_id, sheet_name=sh_name, row=row)
                op = "added"
            else:
                res = await _sheet_gems_update_row(spreadsheet_id=ss_id, sheet_name=sh_name, row_number=row_num, row=row)
                op = "updated"
            payload = await _load_sheet_gems(sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
            try:
                _set_cached_sheet_gems(payload)
            except Exception:
                pass
            await _ws_send_json(ws, {"type": "gems_upserted", "op": op, "gem_id": gem_id, "result": res, "instance_id": INSTANCE_ID}, trace_id=tid)
            await _ws_voice_job_done(ws, tid)
            return True

        if action in {"analyze"}:
            gem_id = _normalize_gem_id(msg.get("id") or msg.get("gem_id"))
            criteria = str(msg.get("criteria") or msg.get("text") or "").strip()
            model_override = str(msg.get("model") or "").strip() or None
            if not gem_id:
                await _ws_send_json(ws, {"type": "error", "kind": "gems_missing_id", "message": "gems_missing_id", "instance_id": INSTANCE_ID}, trace_id=tid)
                return True
            src = await _resolve_sheet_gem(gem_id, sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
            if not isinstance(src, dict) or not src:
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "gem_not_found",
                        "message": "gem_not_found",
                        "detail": f"gem_id={gem_id} sheet={sh_name} spreadsheet_id={ss_id} | Try: gems list | Try: reload gems",
                        "gem_id": gem_id,
                        "instance_id": INSTANCE_ID,
                    },
                    trace_id=tid,
                )
                return True

            await _ws_send_json(ws, {"type": "progress", "phase": "start", "text": f"gems.analyze: {gem_id}", "instance_id": INSTANCE_ID}, trace_id=tid)
            suggestion, err = await _gems_analyze_suggest_update(ws=ws, gem=src, criteria=criteria, model_override=model_override)
            if not isinstance(suggestion, dict) or err:
                err_s = str(err or "unknown")
                if ("RESOURCE_EXHAUSTED" in err_s) or ("429" in err_s and "quota" in err_s.lower()):
                    retry_after_seconds = None
                    try:
                        # Typical error string contains: "Please retry in 46.910851409s."
                        m = re.search(r"retry in\s+([0-9.]+)s", err_s, flags=re.IGNORECASE)
                        if m:
                            retry_after_seconds = float(m.group(1))
                        else:
                            # Some SDKs include retryDelay: '46s'
                            m2 = re.search(r"retryDelay'\s*:\s*'([0-9.]+)s'", err_s, flags=re.IGNORECASE)
                            if m2:
                                retry_after_seconds = float(m2.group(1))
                    except Exception:
                        retry_after_seconds = None
                    await _ws_send_json(
                        ws,
                        {
                            "type": "error",
                            "kind": "gems_rate_limited",
                            "message": "gems_rate_limited",
                            "detail": err_s,
                            "retry_after_seconds": retry_after_seconds,
                            "gem_id": gem_id,
                            "instance_id": INSTANCE_ID,
                        },
                        trace_id=tid,
                    )
                    return True
                await _ws_send_json(
                    ws,
                    {"type": "error", "kind": "gems_analyze_failed", "message": "gems_analyze_failed", "detail": err_s, "gem_id": gem_id, "instance_id": INSTANCE_ID},
                    trace_id=tid,
                )
                return True

            before = {
                "id": _normalize_gem_id(src.get("id")),
                "name": src.get("name"),
                "purpose": src.get("purpose"),
                "system_instruction": src.get("system_instruction"),
                "user_instruction": src.get("user_instruction"),
                "output_format": src.get("output_format"),
                "tools_policy": src.get("tools_policy"),
            }
            after = {
                "id": _normalize_gem_id(suggestion.get("id")),
                "name": suggestion.get("name"),
                "purpose": suggestion.get("purpose"),
                "system_instruction": suggestion.get("system_instruction"),
                "user_instruction": suggestion.get("user_instruction"),
                "output_format": suggestion.get("output_format"),
                "tools_policy": suggestion.get("tools_policy"),
            }
            changed: list[str] = []
            for k in ["name", "purpose", "system_instruction", "user_instruction", "output_format", "tools_policy"]:
                try:
                    if str(before.get(k) or "").strip() != str(after.get(k) or "").strip():
                        changed.append(k)
                except Exception:
                    pass

            draft_id = uuid.uuid4().hex[:12]
            session_id = str(getattr(ws.state, "session_id", "") or "").strip() or "(no_session)"
            _GEMS_DRAFTS[draft_id] = {
                "draft_id": draft_id,
                "session_id": session_id,
                "gem_id": gem_id,
                "criteria": criteria,
                "created_at": int(time.time()),
                "before": before,
                "after": after,
                "changed": changed,
            }

            await _ws_send_json(
                ws,
                {
                    "type": "gems_draft_created",
                    "draft_id": draft_id,
                    "gem_id": gem_id,
                    "changed": changed,
                    "before": before,
                    "after": after,
                    "instance_id": INSTANCE_ID,
                },
                trace_id=tid,
            )
            await _ws_voice_job_done(ws, tid)
            return True

        if action in {"draft_get"}:
            draft_id = str(msg.get("draft_id") or "").strip()
            if not draft_id:
                await _ws_send_json(ws, {"type": "error", "kind": "gems_missing_draft_id", "message": "gems_missing_draft_id", "instance_id": INSTANCE_ID}, trace_id=tid)
                return True
            draft = _GEMS_DRAFTS.get(draft_id)
            if not isinstance(draft, dict):
                await _ws_send_json(ws, {"type": "error", "kind": "gems_draft_not_found", "message": "gems_draft_not_found", "draft_id": draft_id, "instance_id": INSTANCE_ID}, trace_id=tid)
                return True
            await _ws_send_json(ws, {"type": "gems_draft", **draft, "instance_id": INSTANCE_ID}, trace_id=tid)
            await _ws_voice_job_done(ws, tid)
            return True

        if action in {"draft_discard"}:
            draft_id = str(msg.get("draft_id") or "").strip()
            if not draft_id:
                await _ws_send_json(ws, {"type": "error", "kind": "gems_missing_draft_id", "message": "gems_missing_draft_id", "instance_id": INSTANCE_ID}, trace_id=tid)
                return True
            existed = _GEMS_DRAFTS.pop(draft_id, None) is not None
            await _ws_send_json(ws, {"type": "gems_draft_discarded", "draft_id": draft_id, "existed": existed, "instance_id": INSTANCE_ID}, trace_id=tid)
            await _ws_voice_job_done(ws, tid)
            return True

        if action in {"draft_apply"}:
            draft_id = str(msg.get("draft_id") or "").strip()
            if not draft_id:
                await _ws_send_json(ws, {"type": "error", "kind": "gems_missing_draft_id", "message": "gems_missing_draft_id", "instance_id": INSTANCE_ID}, trace_id=tid)
                return True
            draft = _GEMS_DRAFTS.get(draft_id)
            if not isinstance(draft, dict):
                await _ws_send_json(ws, {"type": "error", "kind": "gems_draft_not_found", "message": "gems_draft_not_found", "draft_id": draft_id, "instance_id": INSTANCE_ID}, trace_id=tid)
                return True
            gem_id = _normalize_gem_id(draft.get("gem_id"))
            after = draft.get("after") if isinstance(draft.get("after"), dict) else None
            if not gem_id or not isinstance(after, dict):
                await _ws_send_json(ws, {"type": "error", "kind": "gems_draft_invalid", "message": "gems_draft_invalid", "draft_id": draft_id, "instance_id": INSTANCE_ID}, trace_id=tid)
                return True

            header, row_num, idx = await _sheet_gems_find_row(spreadsheet_id=ss_id, sheet_name=sh_name, gem_id=gem_id)
            row = _sheet_gems_build_row(header=header, idx=idx, gem={**after, "id": gem_id})
            if row_num <= 0:
                res = await _sheet_gems_append(spreadsheet_id=ss_id, sheet_name=sh_name, row=row)
                op = "added"
            else:
                res = await _sheet_gems_update_row(spreadsheet_id=ss_id, sheet_name=sh_name, row_number=row_num, row=row)
                op = "updated"
            payload = await _load_sheet_gems(sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
            try:
                _set_cached_sheet_gems(payload)
            except Exception:
                pass
            try:
                _GEMS_DRAFTS.pop(draft_id, None)
            except Exception:
                pass
            await _ws_send_json(ws, {"type": "gems_draft_applied", "draft_id": draft_id, "op": op, "gem_id": gem_id, "result": res, "instance_id": INSTANCE_ID}, trace_id=tid)
            await _ws_voice_job_done(ws, tid)
            return True

        if action in {"remove", "delete"}:
            gem_id = _normalize_gem_id(msg.get("id") or msg.get("gem_id"))
            if not gem_id:
                await _ws_send_json(ws, {"type": "error", "kind": "gems_missing_id", "message": "gems_missing_id", "instance_id": INSTANCE_ID}, trace_id=tid)
                return True
            header, row_num, idx = await _sheet_gems_find_row(spreadsheet_id=ss_id, sheet_name=sh_name, gem_id=gem_id)
            if row_num <= 0:
                await _ws_send_json(ws, {"type": "error", "kind": "gem_not_found", "message": "gem_not_found", "gem_id": gem_id, "instance_id": INSTANCE_ID}, trace_id=tid)
                return True
            empty = [""] * len(header)
            res = await _sheet_gems_update_row(spreadsheet_id=ss_id, sheet_name=sh_name, row_number=row_num, row=empty)
            payload = await _load_sheet_gems(sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
            try:
                _set_cached_sheet_gems(payload)
            except Exception:
                pass
            await _ws_send_json(ws, {"type": "gems_removed", "gem_id": gem_id, "result": res, "instance_id": INSTANCE_ID}, trace_id=tid)
            await _ws_voice_job_done(ws, tid)
            return True

        await _ws_send_json(ws, {"type": "error", "kind": "invalid_gems_action", "message": f"invalid_gems_action: {action}", "instance_id": INSTANCE_ID}, trace_id=tid)
        return True

    return False


async def _handle_note_trigger(ws: WebSocket, text: str, *, speak: bool = True) -> bool:
    note_text = _extract_note_text(text)
    if not note_text:
        if _is_note_trigger(text):
            # User said "make a note" but didn't provide content. Ask for follow-up and
            # keep a short continuation window so the next message becomes the note.
            ws.state.active_agent_id = "note"
            ws.state.active_agent_until_ts = int(time.time()) + AGENT_CONTINUE_WINDOW_SECONDS
            await _ws_send_json(ws, {"type": "note_prompt", "message": "note_missing_text", "instance_id": INSTANCE_ID})
            if speak:
                try:
                    await _live_say(ws, "จะให้จดอะไร?" if _text_is_thai(text) else "What should I write in the note?")
                except Exception:
                    pass
            return True
        return False

    sys_kv = getattr(ws.state, "sys_kv", None)
    spreadsheet_id = (
        str(sys_kv.get("notes_ss") or "").strip()
        if isinstance(sys_kv, dict)
        else ""
    )
    if not spreadsheet_id:
        spreadsheet_id = _system_spreadsheet_id()

    sheet_name = (
        str(sys_kv.get("notes_sh") or "").strip()
        if isinstance(sys_kv, dict)
        else ""
    )
    if not sheet_name:
        await _ws_send_json(
            ws,
            {
                "type": "note_error",
                "message": "missing_notes_sheet_name",
                "detail": "Missing notes_sh/notes.sheet_name in system sheet (no env fallback).",
                "instance_id": INSTANCE_ID,
            },
        )
        return True

    if not spreadsheet_id:
        await _ws_send_json(
            ws,
            {
                "type": "note_error",
                "message": "missing_notes_ss",
                "detail": "Missing notes_ss in system sheet and CHABA_SYSTEM_SPREADSHEET_ID env is not set.",
                "instance_id": INSTANCE_ID,
            },
        )
        return True

    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    status = "new"
    processed_time = ""
    # Notes board schema (v2):
    # A: id (computed in-sheet)
    # B..S: date_time..parent_id
    # We append into B:S (19 columns).
    row = [
        now_iso,  # date_time
        "note",  # subject
        str(note_text or "").strip(),  # notes
        status,  # status
        processed_time,  # time_processed
        "note",  # type
        "user",  # owner
        "",  # assignee
        "",  # job_gem
        "",  # job_payload
        "",  # claimed_at
        "",  # started_at
        "",  # done_at
        "",  # result
        "",  # result_sources
        "",  # error
        "",  # run_id
        "",  # parent_id
    ]

    sheet_name_a1 = _sheet_name_to_a1(sheet_name or "notes.0", default="notes.0")
    append_range = f"{sheet_name_a1}!B:S"

    tool = _pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
    res = await _mcp_tools_call(
        tool,
        {
            "spreadsheet_id": spreadsheet_id,
            "range": append_range,
            "values": [row],
            "value_input_option": "USER_ENTERED",
            "insert_data_option": "INSERT_ROWS",
        },
    )
    parsed = _mcp_text_json(res)

    # Best-effort: extract the row number from the append response so we can report a stable id.
    # Google usually returns e.g. `notes!B12:F12`. We map sheet row -> note id by subtracting 1 (header row).
    note_id: Optional[int] = None
    try:
        updated_range = ""
        if isinstance(parsed, dict):
            updated_range = str((((parsed.get("data") or {}).get("updates") or {}).get("updatedRange") or "")).strip()
        m = re.search(r"!(?:[A-Z]+)(\d+):", updated_range)
        if not m:
            m = re.search(r"!(?:[A-Z]+)(\d+)$", updated_range)
        if m:
            row_num = int(m.group(1))
            note_id = max(1, row_num - 1)
    except Exception:
        note_id = None

    await _ws_send_json(
        ws,
        {
            "type": "note_created",
            "note": {
                "id": note_id,
                "date_time": now_iso,
                "subject": "note",
                "notes": str(note_text or "").strip(),
                "status": status,
                "time": processed_time,
                # Backwards compatible fields (UI may still expect them).
                "input": str(text or "").strip(),
                "input_improve": "",
            },
            "result": parsed if isinstance(parsed, dict) else {"raw": parsed},
            "instance_id": INSTANCE_ID,
        },
    )
    if speak:
        try:
            await _live_say(ws, "บันทึกแล้ว" if _text_is_thai(text) else "Saved a note.")
        except Exception:
            pass
    return True


async def _handle_note_followup(ws: WebSocket, text: str) -> bool:
    # After a note trigger with missing text, treat the next message as the note body.
    note_text = str(text or "").strip()
    if not note_text:
        return True
    # Avoid accepting another trigger phrase as the note itself.
    if _is_note_trigger(note_text):
        return True
    return await _handle_note_trigger(ws, f"จดบันทึก: {note_text}" if _text_is_thai(note_text) else f"make a note: {note_text}")


def _get_news_follow_focus(user_id: str) -> list[str]:
    cached = _get_news_cache(_news_follow_cache_key_focus(user_id))
    payload = cached.get("payload") if isinstance(cached, dict) else None
    focus = payload.get("focus") if isinstance(payload, dict) else None
    if isinstance(focus, list):
        out: list[str] = []
        seen: set[str] = set()
        for f in focus:
            t = str(f or "").strip()
            k = t.lower()
            if t and k not in seen:
                seen.add(k)
                out.append(t)
        return out
    return ["Thai Baht", "USD/THB", "gold", "oil", "Iran"]


def _set_news_follow_focus(user_id: str, focus: list[str]) -> None:
    _set_news_cache(_news_follow_cache_key_focus(user_id), {"focus": focus, "updated_at": int(time.time())})


def _get_news_follow_summaries(user_id: str) -> list[dict[str, Any]]:
    cached = _get_news_cache(_news_follow_cache_key_summaries(user_id))
    payload = cached.get("payload") if isinstance(cached, dict) else None
    items = payload.get("summaries") if isinstance(payload, dict) else None
    if isinstance(items, list):
        out: list[dict[str, Any]] = []
        for it in items:
            if isinstance(it, dict):
                out.append(it)
        return out
    return []


def _set_news_follow_summaries(user_id: str, summaries: list[dict[str, Any]]) -> None:
    _set_news_cache(_news_follow_cache_key_summaries(user_id), {"summaries": summaries, "updated_at": int(time.time())})


async def _refresh_news_follow_summaries(user_id: str, focus: list[str]) -> dict[str, Any]:
    feeds = [
        "https://rss.cnn.com/rss/edition.rss",
        "https://rss.cnn.com/rss/edition_world.rss",
        "https://rss.cnn.com/rss/money_latest.rss",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
    ]
    all_items: list[dict[str, Any]] = []
    for url in feeds:
        xml_text = await _mcp_web_fetch_text(url, max_length=250000)
        all_items.extend(_parse_rss_items(xml_text))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for it in all_items:
        key = str(it.get("link") or "") or str(it.get("title") or "")
        key = key.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    focus_norm = [str(f or "").strip() for f in focus if str(f or "").strip()]
    matched: list[dict[str, Any]] = []
    for it in deduped:
        blob = f"{it.get('title','')} {it.get('description','')}"
        if _topic_match(blob, focus_norm):
            matched.append(it)

    sources: list[str] = []
    lines: list[str] = []
    for it in matched[:20]:
        title = str(it.get("title") or "").strip()
        link = str(it.get("link") or "").strip()
        if link and link not in sources:
            sources.append(link)
        if title:
            if link:
                lines.append(f"- {title} ({link})")
            else:
                lines.append(f"- {title}")

    summary_text = "\n".join(lines).strip()
    now_ts = int(time.time())
    summary_id = f"nf_{uuid.uuid4().hex[:12]}"
    summary_obj = {
        "summary_id": summary_id,
        "title": "ติดตามข่าว: สรุปล่าสุด",
        "focus": focus_norm,
        "text": summary_text,
        "sources": sources,
        "created_at": now_ts,
    }

    summaries = _get_news_follow_summaries(user_id)
    summaries = [summary_obj] + [s for s in summaries if isinstance(s, dict) and str(s.get("summary_id") or "") != summary_id]
    summaries = summaries[:20]
    _set_news_follow_summaries(user_id, summaries)
    payload = {"summary": "news-follow refreshed", "focus": focus_norm, "summaries": summaries, "updated_at": now_ts}
    _upsert_agent_status(user_id, "follow_news", payload)
    return payload


async def _handle_news_follow_trigger(ws: WebSocket, text: str) -> bool:
    cmd = _parse_news_follow_command(text)
    action = cmd.get("action") or ""
    arg = cmd.get("arg") or ""

    s = " ".join(str(text or "").lower().split())
    is_trigger = action != "" or ("ติดตามข่าว" in s) or ("โฟกัสข่าว" in s) or ("follow_news" in s) or ("follow news" in s) or ("news follow" in s) or ("track news" in s)
    if not is_trigger:
        return False

    user_id = DEFAULT_USER_ID
    focus = _get_news_follow_focus(user_id)
    summaries = _get_news_follow_summaries(user_id)

    if action == "focus_list":
        await ws.send_json({"type": "news_follow_focus", "focus": focus})
        return True

    if action == "focus_add":
        item = str(arg or "").strip()
        if not item:
            await ws.send_json({"type": "news_follow_error", "message": "missing_focus_item"})
            return True
        new_focus = focus + [item]
        _set_news_follow_focus(user_id, new_focus)
        await ws.send_json({"type": "news_follow_focus_updated", "focus": _get_news_follow_focus(user_id)})
        return True

    if action == "focus_remove":
        item = str(arg or "").strip().lower()
        if not item:
            await ws.send_json({"type": "news_follow_error", "message": "missing_focus_item"})
            return True
        new_focus = [f for f in focus if str(f or "").strip().lower() != item]
        _set_news_follow_focus(user_id, new_focus)
        await ws.send_json({"type": "news_follow_focus_updated", "focus": _get_news_follow_focus(user_id)})
        return True

    if action == "refresh":
        payload = await _refresh_news_follow_summaries(user_id, focus)
        await ws.send_json({"type": "news_follow_refreshed", "status": payload})
        return True

    if action == "report":
        target = str(arg or "").strip()
        if not target:
            await ws.send_json({"type": "news_follow_error", "message": "missing_summary_id"})
            return True
        chosen: Optional[dict[str, Any]] = None
        for it in summaries:
            if isinstance(it, dict) and str(it.get("summary_id") or "").strip() == target:
                chosen = it
                break
        if not chosen:
            await ws.send_json({"type": "news_follow_error", "message": "summary_not_found", "summary_id": target})
            return True
        await ws.send_json({"type": "news_follow_report", "summary": chosen})
        return True

    if not summaries:
        await ws.send_json(
            {
                "type": "news_follow",
                "message": "ยังไม่มีสรุปที่เก็บไว้ พิมพ์: ติดตามข่าว รีเฟรช",
                "focus": focus,
            }
        )
        return True

    available = [
        {
            "summary_id": str(it.get("summary_id") or ""),
            "title": str(it.get("title") or ""),
            "created_at": it.get("created_at"),
            "focus": it.get("focus"),
        }
        for it in summaries
        if isinstance(it, dict)
    ]
    await ws.send_json(
        {
            "type": "news_follow_available",
            "focus": focus,
            "summaries": available,
            "message": "ต้องการให้รายงานอันไหน? พิมพ์: รายงานข่าว: <summary_id> หรือ ติดตามข่าว รีเฟรช",
        }
    )
    return True


async def _dispatch_sub_agents(ws: WebSocket, text: str) -> bool:
    # Continuation handling: if a sub-agent is active for this websocket, let it handle followups.
    now_ts = int(time.time())
    active_agent_id = str(getattr(ws.state, "active_agent_id", "") or "").strip() or None
    active_until = getattr(ws.state, "active_agent_until_ts", None)
    try:
        active_until_ts = int(active_until) if active_until is not None else 0
    except Exception:
        active_until_ts = 0

    async def _run_agent(agent_id: str) -> bool:
        agent_id_norm = str(agent_id or "").strip()
        if agent_id_norm == "note":
            handled = await _handle_note_followup(ws, text)
            if handled:
                ws.state.active_agent_id = None
                ws.state.active_agent_until_ts = None
            return handled
        if agent_id_norm == "memo_enrich":
            handled = await _handle_memo_enrich_followup(ws, text)
            if handled:
                ws.state.active_agent_id = None
                ws.state.active_agent_until_ts = None
            return handled
        if agent_id_norm == "reminder-setup":
            handled = await _handle_reminder_setup_trigger(ws, text)
            if handled:
                ws.state.active_agent_id = agent_id_norm
                ws.state.active_agent_until_ts = int(time.time()) + AGENT_CONTINUE_WINDOW_SECONDS
            return handled
        if agent_id_norm == "current-news":
            handled = await _handle_current_news_trigger(ws, text)
            if handled:
                ws.state.active_agent_id = agent_id_norm
                ws.state.active_agent_until_ts = int(time.time()) + AGENT_CONTINUE_WINDOW_SECONDS
            return handled
        if agent_id_norm == "deep-research":
            handled = await _handle_deep_research_trigger(ws, text)
            if handled:
                ws.state.active_agent_id = agent_id_norm
                ws.state.active_agent_until_ts = int(time.time()) + AGENT_CONTINUE_WINDOW_SECONDS
            return handled
        if agent_id_norm == "follow_news":
            handled = await _handle_news_follow_trigger(ws, text)
            if handled:
                ws.state.active_agent_id = agent_id_norm
                ws.state.active_agent_until_ts = int(time.time()) + AGENT_CONTINUE_WINDOW_SECONDS
            return handled
        return False

    if active_agent_id and active_until_ts >= now_ts:
        handled = await _run_agent(active_agent_id)
        if handled:
            return True

    sys_kv = getattr(ws.state, "sys_kv", None)

    if feature_enabled("memo", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
        handled = await _handle_memo_trigger(ws, text)
        if handled:
            return True

    handled = await _handle_notes_check(ws, text)
    if handled:
        return True

    if feature_enabled("memory", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
        handled = await _handle_memory_trigger(ws, text)
        if handled:
            return True

    if feature_enabled("knowledge", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
        handled = await _handle_knowledge_trigger(ws, text)
        if handled:
            return True

    handled = await _handle_note_trigger(ws, text)
    if handled:
        return True

    handled = await _handle_github_watch_voice(ws, text)
    if handled:
        return True

    # Trigger matching.
    triggers = _agent_triggers_snapshot()
    s = str(text or "")
    for agent_id, phrases in triggers.items():
        for phrase in phrases:
            if phrase and phrase.lower() in s.lower():
                handled = await _run_agent(agent_id)
                if handled:
                    return True

    # Clear expired continuation state.
    if active_agent_id and active_until_ts < now_ts:
        ws.state.active_agent_id = None
        ws.state.active_agent_until_ts = None
    return False


async def _handle_reload_system(ws: WebSocket, text: str) -> bool:
    s = " ".join(str(text or "").strip().split())
    if not s:
        return False

    # Voice/STT-friendly matching: allow extra words/punctuation.
    sl = s.lower()
    compact = re.sub(r"[^a-z0-9\u0E00-\u0E7F]+", " ", sl).strip()
    compact = " ".join(compact.split())

    words = set(compact.split())
    has_action = any(k in words for k in {"reload", "reset", "restart", "reboot"}) or ("reload" in compact)
    has_target = any(k in words for k in {"system", "sys", "sheets", "sheet"}) or ("system" in compact) or ("sheets" in compact)

    is_reload_en = (
        (has_action and has_target)
        or "reload system" in compact
        or "reload sheets" in compact
        or "reload sheet" in compact
        or compact in {"reload", "reload sys", "reset", "restart"}
        or compact.startswith("reload")
        or compact.startswith("reset")
        or compact.startswith("restart")
    )

    # Thai common variants.
    th = compact
    is_reload_th = False
    if any(k in th for k in ["รีโหลด", "โหลด", "รีเฟรช", "รีเซ็ต", "รีสตาร์ท", "restart", "reset"]):
        if any(k in th for k in ["ระบบ", "ชีต", "ชีท", "ชี้ต", "ซิส", "ซิสเต็ม", "system", "sheets"]):
            is_reload_th = True
        if "ใหม่" in th and "โหลด" in th:
            is_reload_th = True
        if "เริ่ม" in th and "ใหม่" in th:
            is_reload_th = True

    if not (is_reload_en or is_reload_th):
        return False

    # Debounce repeated triggers from STT/voice (per websocket).
    try:
        now_ts = time.time()
        last_ts = float(getattr(ws.state, "reload_system_last_ts", 0.0) or 0.0)
        if last_ts and (now_ts - last_ts) < RELOAD_SYSTEM_DEBOUNCE_SECONDS:
            return True
        ws.state.reload_system_last_ts = now_ts
    except Exception:
        pass

    # Only allow one reload at a time (global) to avoid overlapping MCP/Sheets calls.
    if _reload_system_lock.locked():
        try:
            await _ws_send_json(
                ws,
                {
                    "type": "text",
                    "text": "reloading system: already running",
                    "instance_id": INSTANCE_ID,
                },
            )
        except Exception:
            pass
        return True

    try:
        logger.info("reload_system_triggered compact=%s", compact)
    except Exception:
        pass

    async with _reload_system_lock:
        lang = str(getattr(ws.state, "user_lang", "") or "").strip() or "en"
        try:
            await _ws_send_json(ws, {"type": "text", "text": "reloading system", "instance_id": INSTANCE_ID})
        except Exception:
            pass

        try:
            # System reload now only refreshes the system KV sheet and system.instruction.
            await _load_ws_system_kv(ws)
        except Exception as e:
            def _short_reload_err(err: Exception) -> str:
                s = str(err or "").strip()
                # Heuristic: extract the root cause from nested MCP error dicts.
                try:
                    if "mcp_error" in s:
                        m = re.search(r"'error':\s*'([^']+)'", s)
                        if m:
                            return m.group(1)
                        m2 = re.search(r"\"error\"\s*:\s*\"([^\"]+)\"", s)
                        if m2:
                            return m2.group(1)
                except Exception:
                    pass
                # Common fast-path: our MCP servers throw specific sentinel errors.
                for tok in (
                    "missing_google_sheets_client_id",
                    "missing_google_tasks_client_id",
                    "missing_google_calendar_client_id",
                    "auth_required",
                    "invalid_client",
                ):
                    if tok in s:
                        return tok
                # Fallback: trim huge nested blobs.
                if len(s) > 180:
                    return s[:180] + "..."
                return s

            short = _short_reload_err(e)
            msg = (
                f"Reload System failed: {short}" if lang != "th" else f"Reload System ล้มเหลว: {short}"
            )
            try:
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "reload_system_failed",
                        "message": msg,
                        "detail": str(e),
                        "instance_id": INSTANCE_ID,
                    },
                )
            except Exception:
                pass
            return True

        try:
            out = "system reloaded"
            if lang == "th":
                out = "รีโหลดระบบสำเร็จ"
            await _ws_send_json(ws, {"type": "text", "text": out, "instance_id": INSTANCE_ID})
        except Exception:
            pass

        # Start notes board runner only after system reload succeeded.
        try:
            existing = getattr(ws.state, "notes_board_task", None)
            if existing is None or not hasattr(existing, "done") or existing.done():
                ws.state.notes_board_task = asyncio.create_task(_notes_board_runner(ws), name="notes_board_runner")
        except Exception:
            pass
    return True


def _parse_bool_cell(v: Any) -> bool:
    s = str(v or "").strip().lower()
    return s in {"1", "true", "t", "yes", "y", "on", "enabled"}


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _sheet_name_to_a1(sheet_name: str, default: str = "Sheet1") -> str:
    return sheets_utils.sheet_name_to_a1(sheet_name, default=default)


async def _run_notes_board_job(*, ws: WebSocket, job_text: str, gem_name: str | None) -> tuple[str, str]:
    """Return (result_text, error_text)."""
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return "", "missing_api_key"

    sys_kv = getattr(ws.state, "sys_kv", None)
    instruction, model_override = await _resolve_gem_instruction_and_model(gem_name=gem_name, sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
    system_instruction = "You are Jarvis. Complete the user's job and return only the final result.".strip()

    notes_policy = _notes_policy_text_from_sys_kv(sys_kv)
    if notes_policy:
        system_instruction += "\n\nNOTES_POLICY (internal)\n" + notes_policy

    mem_ctx = str(getattr(ws.state, "memory_context_text", "") or "").strip()
    know_ctx = str(getattr(ws.state, "knowledge_context_text", "") or "").strip()
    if mem_ctx:
        system_instruction += "\n\nMEMORY (from Google Sheets):\n" + mem_ctx
    if know_ctx:
        system_instruction += "\n\nKNOWLEDGE (from Google Sheets):\n" + know_ctx
    mem_inst = str(getattr(ws.state, "memory_instruction", "") or "").strip()
    know_inst = str(getattr(ws.state, "knowledge_instruction", "") or "").strip()
    if mem_inst:
        system_instruction += "\n\nMEMORY_INSTRUCTION (from system sheet):\n" + mem_inst
    if know_inst:
        system_instruction += "\n\nKNOWLEDGE_INSTRUCTION (from system sheet):\n" + know_inst
    extra_sys = str(getattr(ws.state, "system_instruction_extra", "") or "").strip()
    if extra_sys:
        system_instruction += "\n\nSYSTEM_INSTRUCTION (from system sheet):\n" + extra_sys
    if instruction:
        system_instruction += "\n\n" + str(instruction)

    model = _normalize_model_name(
        str(model_override or os.getenv("GEMINI_TEXT_MODEL") or "gemini-2.0-flash").strip() or "gemini-2.0-flash"
    )

    try:
        client = genai.Client(api_key=api_key)
        cfg = {"system_instruction": system_instruction}
        res = await client.aio.models.generate_content(model=model, contents=str(job_text), config=cfg)
        txt = getattr(res, "text", None)
        if txt is None:
            txt = str(res)
        out = str(txt or "").strip()
        if not out:
            return "", "empty_result"
        return out, ""
    except Exception as e:
        return "", str(e)


async def _notes_board_poll_once(ws: WebSocket) -> None:
    sys_kv = getattr(ws.state, "sys_kv", None)
    spreadsheet_id = ""
    if isinstance(sys_kv, dict):
        spreadsheet_id = str(sys_kv.get("notes_ss") or "").strip()
    if not spreadsheet_id:
        spreadsheet_id = _system_spreadsheet_id()
    if not spreadsheet_id:
        return

    enabled_raw = ""
    if isinstance(sys_kv, dict):
        enabled_raw = str(sys_kv.get("notes.board.enabled") or "").strip()
    if enabled_raw and not _parse_bool_cell(enabled_raw):
        return

    sheet_name = ""
    if isinstance(sys_kv, dict):
        sheet_name = str(sys_kv.get("notes.sheet_name") or sys_kv.get("notes_sh") or "").strip()
    if not sheet_name:
        return

    rows = await _load_sheet_table(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name, max_rows=400, max_cols="S")
    if not rows:
        return

    header = rows[0] if isinstance(rows[0], list) else []
    idx = _idx_from_header(header)
    # Required columns.
    col_status = idx.get("status")
    col_notes = idx.get("notes")
    col_assignee = idx.get("assignee")
    col_job_gem = idx.get("job_gem")
    if col_status is None or col_notes is None or col_assignee is None:
        return

    # Find first unclaimed job: status=new and assignee=jarvis
    target_row_num: int | None = None
    job_text = ""
    job_gem = ""
    for i, raw in enumerate(rows[1:], start=2):
        if not isinstance(raw, list) or not raw:
            continue
        status = str(raw[col_status] if col_status < len(raw) else "").strip().lower()
        assignee = str(raw[col_assignee] if col_assignee < len(raw) else "").strip().lower()
        if status != "new" or assignee != "jarvis":
            continue
        job_text = str(raw[col_notes] if col_notes < len(raw) else "").strip()
        if not job_text:
            continue
        if col_job_gem is not None and col_job_gem < len(raw):
            job_gem = str(raw[col_job_gem] or "").strip()
        target_row_num = i
        break

    if target_row_num is None:
        return

    run_id = uuid.uuid4().hex[:16]
    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

    sheet_a1 = _sheet_name_to_a1(sheet_name, default="notes.0")
    # Update E:R (status..run_id) to claim/start
    claim_range = f"{sheet_a1}!E{target_row_num}:R{target_row_num}"
    claim_values = [[
        "doing",  # status
        "",  # time_processed
        "job",  # type
        "",  # owner
        "jarvis",  # assignee
        str(job_gem or "").strip(),  # job_gem
        "",  # job_payload
        now_iso,  # claimed_at
        now_iso,  # started_at
        "",  # done_at
        "",  # result
        "",  # result_sources
        "",  # error
        run_id,  # run_id
    ]]
    tool_upd = _pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
    await _mcp_tools_call(
        tool_upd,
        {
            "spreadsheet_id": spreadsheet_id,
            "range": claim_range,
            "values": claim_values,
            "value_input_option": "USER_ENTERED",
        },
    )

    result_text, err_text = await _run_notes_board_job(ws=ws, job_text=job_text, gem_name=job_gem or None)

    done_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    final_status = "done" if result_text and not err_text else "failed"
    final_range = f"{sheet_a1}!E{target_row_num}:R{target_row_num}"
    final_values = [[
        final_status,
        done_iso,
        "job",
        "",
        "jarvis",
        str(job_gem or "").strip(),
        "",
        now_iso,
        now_iso,
        done_iso,
        str(result_text or "").strip(),
        "",
        str(err_text or "").strip(),
        run_id,
    ]]
    await _mcp_tools_call(
        tool_upd,
        {
            "spreadsheet_id": spreadsheet_id,
            "range": final_range,
            "values": final_values,
            "value_input_option": "USER_ENTERED",
        },
    )


async def _notes_board_runner(ws: WebSocket) -> None:
    # WS-scoped polling loop. Runs only while the websocket is alive.
    backoff_s = 0.0
    try:
        while True:
            try:
                await _notes_board_poll_once(ws)
                backoff_s = 0.0
            except Exception:
                # Backoff on rate limiting / transient failures.
                msg = ""
                try:
                    msg = str(sys.exc_info()[1] or "")
                except Exception:
                    msg = ""
                if "429" in msg or "resource_exhausted" in msg.lower() or "rate" in msg.lower():
                    backoff_s = max(backoff_s, 10.0)
                    backoff_s = min(120.0, backoff_s * 2.0 if backoff_s else 10.0)
                else:
                    backoff_s = max(backoff_s, 2.0)
                    backoff_s = min(30.0, backoff_s * 1.5 if backoff_s else 2.0)
            # Default poll interval (keep low pressure on Sheets).
            base = 15.0
            await asyncio.sleep(base + (backoff_s or 0.0))
    except asyncio.CancelledError:
        return


async def _load_sheet_kv5(*, spreadsheet_id: str, sheet_name: str) -> list[dict[str, Any]]:
    # Expects a table with columns: key, value, enabled, scope, priority.
    tool = _pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
    res = await _mcp_tools_call(tool, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_name}!A:G"})
    parsed = _mcp_text_json(res)
    if not isinstance(parsed, dict):
        raise RuntimeError("google_sheets_values_get_invalid_response")
    values = parsed.get("values")
    if not isinstance(values, list) or not values:
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if isinstance(data, dict):
            values = data.get("values")
    if not isinstance(values, list) or not values:
        raise RuntimeError(
            f"google_sheets_values_get_missing_values spreadsheet_id={spreadsheet_id} sheet={sheet_name}"
        )

    # Header normalization.
    header = [str(c or "").strip().lower() for c in (values[0] if isinstance(values[0], list) else [])]
    idx: dict[str, int] = {}
    for i, col in enumerate(header):
        if col:
            idx[col] = i

    def get_cell(row: list[Any], name: str) -> Any:
        j = idx.get(name)
        if j is None or j < 0 or j >= len(row):
            return ""
        return row[j]

    out: list[dict[str, Any]] = []
    for raw in values[1:]:
        if not isinstance(raw, list) or not raw:
            continue
        key = str(get_cell(raw, "key") or raw[0] or "").strip()
        if not key:
            continue
        val = str(get_cell(raw, "value") or (raw[1] if len(raw) > 1 else "")).strip()
        enabled = _parse_bool_cell(get_cell(raw, "enabled") or (raw[2] if len(raw) > 2 else "true"))
        scope = str(get_cell(raw, "scope") or (raw[3] if len(raw) > 3 else "global")).strip() or "global"
        priority = _safe_int(get_cell(raw, "priority") or (raw[4] if len(raw) > 4 else 0), default=0)
        out.append({"key": key, "value": val, "enabled": enabled, "scope": scope, "priority": priority})
    return out


async def _load_ws_sheet_memory(ws: WebSocket) -> None:
    spreadsheet_id = _system_spreadsheet_id()
    if not spreadsheet_id:
        return

    sys_sheet = _system_sheet_name()
    sys_rows = await _load_sheet_kv5(spreadsheet_id=spreadsheet_id, sheet_name=sys_sheet)
    sys_kv = {
        str(it.get("key") or "").strip(): str(it.get("value") or "").strip()
        for it in sys_rows
        if isinstance(it, dict) and bool(it.get("enabled")) and str(it.get("key") or "").strip()
    }

    # Optional: extra system instruction to inject into Gemini system prompt.
    try:
        ws.state.system_instruction_extra = _system_instruction_from_sys_kv(sys_kv)
    except Exception:
        pass

    # Explicit sheet load plan driven by system KV.
    # No silent fallbacks: if system.sheets is missing or invalid, raise for debugging.
    sheets_plan_raw = str(sys_kv.get("system.sheets") or "").strip()
    if not sheets_plan_raw:
        raise RuntimeError("missing_system_sheets: expected sys_kv key system.sheets")
    plan = _split_phrases(sheets_plan_raw)
    if not plan:
        raise RuntimeError("invalid_system_sheets: system.sheets is empty")

    memory_sheet: str | None = None
    knowledge_sheet: str | None = None
    for entry in plan:
        e = str(entry or "").strip()
        if not e:
            continue
        role = None
        name = e
        if ":" in e:
            left, right = e.split(":", 1)
            left = left.strip().lower()
            right = right.strip()
            if left in {"memory", "knowledge"}:
                role = left
                name = right
        if role is None:
            low = e.strip().lower()
            if low in {"memory", "knowledge"}:
                role = low
                name = e

        if role == "memory":
            override = str(sys_kv.get("memory.sheet_name") or "").strip()
            memory_sheet = override or str(name or "").strip()
            if not memory_sheet:
                raise RuntimeError("invalid_system_sheets: memory sheet name is empty")
            continue
        if role == "knowledge":
            override = str(sys_kv.get("knowledge.sheet_name") or "").strip()
            knowledge_sheet = override or str(name or "").strip()
            if not knowledge_sheet:
                raise RuntimeError("invalid_system_sheets: knowledge sheet name is empty")
            continue

        raise RuntimeError(
            f"unknown_system_sheet_entry: {e} (system.sheets supports only memory/knowledge; configure notes via notes_ss + notes.sheet_name/notes_sh)"
        )

    if not memory_sheet:
        raise RuntimeError("missing_system_sheets: memory not configured in system.sheets")
    if not knowledge_sheet:
        raise RuntimeError("missing_system_sheets: knowledge not configured in system.sheets")

    # Per-sheet metadata (from system KV): <sheet>.info and <sheet>.instruction.
    memory_info = str(sys_kv.get("memory.info") or "").strip()
    knowledge_info = str(sys_kv.get("knowledge.info") or "").strip()
    memory_instruction = str(sys_kv.get("memory.instruction") or "").strip()
    knowledge_instruction = str(sys_kv.get("knowledge.instruction") or "").strip()

    knowledge_items_raw = await _load_sheet_kv5(spreadsheet_id=spreadsheet_id, sheet_name=knowledge_sheet)
    knowledge_items = [
        it
        for it in knowledge_items_raw
        if isinstance(it, dict)
        and bool(it.get("enabled"))
        and str(it.get("key") or "").strip()
        and str(it.get("value") or "").strip()
    ]
    knowledge_by_key: set[str] = {str(it.get("key") or "").strip() for it in knowledge_items if isinstance(it, dict)}

    scope_precedence_raw = str(sys_kv.get("memory.scopes_precedence") or "session,user,global").strip()
    scopes = [s.strip() for s in scope_precedence_raw.split(",") if s.strip()]
    if not scopes:
        scopes = ["session", "user", "global"]
    scope_rank = {s: i for i, s in enumerate(scopes)}

    items = await _load_sheet_kv5(spreadsheet_id=spreadsheet_id, sheet_name=memory_sheet)
    enabled_items = [
        it
        for it in items
        if isinstance(it, dict)
        and bool(it.get("enabled"))
        and str(it.get("key") or "").strip()
        and str(it.get("value") or "").strip()
        and str(it.get("key") or "").strip() not in knowledge_by_key
    ]

    enabled_items.sort(
        key=lambda it: (
            scope_rank.get(str(it.get("scope") or "global"), 999),
            -_safe_int(it.get("priority"), default=0),
        )
    )

    try:
        ws.state.sys_kv = sys_kv
        ws.state.memory_items = enabled_items
        ws.state.memory_sheet_name = memory_sheet
        ws.state.knowledge_items = knowledge_items
        ws.state.knowledge_sheet_name = knowledge_sheet
        ws.state.memory_info = memory_info
        ws.state.knowledge_info = knowledge_info
        ws.state.memory_instruction = memory_instruction
        ws.state.knowledge_instruction = knowledge_instruction
    except Exception:
        pass

    # Build a compact text blob for Gemini context injection.
    max_items = _safe_int(sys_kv.get("memory.max_items"), default=120)
    if max_items <= 0:
        max_items = 120

    lines: list[str] = []
    if memory_info:
        lines.append(f"INFO: {memory_info}")
    for it in enabled_items[:max_items]:
        k = str(it.get("key") or "").strip()
        v = str(it.get("value") or "").strip()
        sc = str(it.get("scope") or "").strip()
        pr = _safe_int(it.get("priority"), default=0)
        if not k or not v:
            continue
        lines.append(f"- [{sc}:{pr}] {k}: {v}")

    ctx = "\n".join(lines).strip()
    try:
        ws.state.memory_context_text = ctx
    except Exception:
        pass

    k_lines: list[str] = []
    if knowledge_info:
        k_lines.append(f"INFO: {knowledge_info}")
    max_k = _safe_int(sys_kv.get("knowledge.max_items"), default=180)
    if max_k <= 0:
        max_k = 180
    for it in knowledge_items[:max_k]:
        k = str(it.get("key") or "").strip()
        v = str(it.get("value") or "").strip()
        sc = str(it.get("scope") or "").strip()
        pr = _safe_int(it.get("priority"), default=0)
        if not k or not v:
            continue
        k_lines.append(f"- [{sc}:{pr}] {k}: {v}")

    k_ctx = "\n".join(k_lines).strip()
    try:
        ws.state.knowledge_context_text = k_ctx
    except Exception:
        pass

    try:
        _set_cached_sheet_memory(
            {
                "sys_kv": sys_kv,
                "memory_items": enabled_items,
                "memory_sheet_name": memory_sheet,
                "memory_context_text": ctx,
            }
        )
    except Exception:
        pass

    try:
        _set_cached_sheet_knowledge(
            {
                "knowledge_items": knowledge_items,
                "knowledge_sheet_name": knowledge_sheet,
                "knowledge_context_text": k_ctx,
            }
        )
    except Exception:
        pass


async def _load_ws_system_kv(ws: WebSocket) -> dict[str, str]:
    spreadsheet_id = _system_spreadsheet_id()
    sys_sheet = _system_sheet_name()
    sys_rows = await _load_sheet_kv5(spreadsheet_id=spreadsheet_id, sheet_name=sys_sheet)
    sys_kv = {
        str(it.get("key") or "").strip(): str(it.get("value") or "").strip()
        for it in sys_rows
        if isinstance(it, dict) and bool(it.get("enabled")) and str(it.get("key") or "").strip()
    }
    try:
        ws.state.sys_kv = sys_kv
    except Exception:
        pass
    _set_cached_sys_kv_only(sys_kv)
    try:
        ws.state.system_instruction_extra = _system_instruction_from_sys_kv(sys_kv)
    except Exception:
        pass

    # Sys-only reload: clear any previously loaded sheet context so Gemini doesn't
    # keep using stale memory/knowledge content.
    try:
        ws.state.memory_items = None
        ws.state.memory_sheet_name = None
        ws.state.memory_context_text = ""
        ws.state.knowledge_items = None
        ws.state.knowledge_sheet_name = None
        ws.state.knowledge_context_text = ""
        ws.state.memory_info = ""
        ws.state.knowledge_info = ""
        ws.state.memory_instruction = ""
        ws.state.knowledge_instruction = ""
    except Exception:
        pass
    return sys_kv


def _validate_system_sheets_plan(sys_kv: Any) -> Optional[str]:
    if not isinstance(sys_kv, dict):
        return "invalid_sys_kv"
    sheets_plan_raw = str(sys_kv.get("system.sheets") or "").strip()
    if not sheets_plan_raw:
        return "missing_system_sheets"
    plan = _split_phrases(sheets_plan_raw)
    if not plan:
        return "invalid_system_sheets"
    saw_memory = False
    saw_knowledge = False
    for entry in plan:
        e = str(entry or "").strip()
        if not e:
            continue
        role = None
        name = e
        if ":" in e:
            left, right = e.split(":", 1)
            left = left.strip().lower()
            right = right.strip()
            if left in {"memory", "knowledge"}:
                role = left
                name = right
        if role is None:
            low = e.strip().lower()
            if low in {"memory", "knowledge"}:
                role = low
                name = e
        if role == "memory":
            if str(name or "").strip():
                saw_memory = True
            continue
        if role == "knowledge":
            if str(name or "").strip():
                saw_knowledge = True
            continue
        return f"unknown_system_sheet_entry: {e}"
    if not saw_memory:
        return "missing_system_sheets: memory"
    if not saw_knowledge:
        return "missing_system_sheets: knowledge"
    return None


async def _refresh_sheet_memory_background(ws: WebSocket, lang: str) -> None:
    global _SHEET_MEMORY_REFRESHING, _SHEET_MEMORY_LAST_REFRESH_AT
    now = int(time.time())
    if _SHEET_MEMORY_REFRESHING:
        return
    if _SHEET_MEMORY_LAST_REFRESH_AT and now - int(_SHEET_MEMORY_LAST_REFRESH_AT) < 10:
        return
    _SHEET_MEMORY_REFRESHING = True
    _SHEET_MEMORY_LAST_REFRESH_AT = now
    try:
        try:
            await _ws_progress(ws, "Loading sys/memory", phase="start")
        except Exception:
            pass
        await _load_ws_sheet_memory(ws)
        try:
            await _ws_progress(ws, "Loaded sys/memory", phase="done")
        except Exception:
            pass
    except Exception as e:
        try:
            logger.warning("sheet_memory_load_failed error=%s", str(e))
        except Exception:
            pass
        try:
            await _ws_progress(ws, "Failed loading sys/memory", phase="error")
        except Exception:
            pass
    finally:
        _SHEET_MEMORY_REFRESHING = False


async def _refresh_sheet_knowledge_background(ws: WebSocket, lang: str) -> None:
    global _SHEET_KNOWLEDGE_REFRESHING, _SHEET_KNOWLEDGE_LAST_REFRESH_AT
    now = int(time.time())
    if _SHEET_KNOWLEDGE_REFRESHING:
        return
    if _SHEET_KNOWLEDGE_LAST_REFRESH_AT and now - int(_SHEET_KNOWLEDGE_LAST_REFRESH_AT) < 10:
        return
    _SHEET_KNOWLEDGE_REFRESHING = True
    _SHEET_KNOWLEDGE_LAST_REFRESH_AT = now
    try:
        try:
            await _ws_progress(ws, "Loading knowledge", phase="start")
        except Exception:
            pass
        # knowledge is loaded as part of _load_ws_sheet_memory to share sys_kv and allow de-dup.
        await _load_ws_sheet_memory(ws)
        try:
            await _ws_progress(ws, "Loaded knowledge", phase="done")
        except Exception:
            pass
    except Exception as e:
        try:
            logger.warning("sheet_knowledge_load_failed error=%s", str(e))
        except Exception:
            pass
        try:
            await _ws_progress(ws, "Failed loading knowledge", phase="error")
        except Exception:
            pass
    finally:
        _SHEET_KNOWLEDGE_REFRESHING = False


async def _handle_memory_trigger(ws: WebSocket, text: str) -> bool:
    s_raw = str(text or "")
    s = " ".join(s_raw.strip().lower().split())
    if not s:
        return False

    # Quick Thai triggers.
    is_summary = ("สรุป" in s and "memory" in s) or ("สรุป" in s and "เมม" in s) or (s.startswith("memory ") and "summary" in s)
    is_list = ("list" in s and "memory" in s) or (s.startswith("memory list"))
    is_get = ("memory key" in s) or s.startswith("memory_get") or ("คีย์" in s and "memory" in s)
    is_search = s.startswith("memory_search") or ("ค้น" in s and "memory" in s) or ("search" in s and "memory" in s)

    if not (is_summary or is_list or is_get or is_search):
        return False

    items = getattr(ws.state, "memory_items", None)
    if not isinstance(items, list) or not items:
        # Try lazy-load once.
        try:
            await _load_ws_sheet_memory(ws)
        except Exception:
            pass
        items = getattr(ws.state, "memory_items", None)

    if not isinstance(items, list) or not items:
        msg = "ยังไม่ได้โหลด memory จากชีต (หรืออ่านไม่สำเร็จ)" if _text_is_thai(s_raw) else "Memory is not loaded (or failed to load)."
        await _ws_send_json(ws, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
        return True

    # Helper index.
    by_key: dict[str, dict[str, Any]] = {}
    for it in items:
        if isinstance(it, dict):
            k = str(it.get("key") or "").strip()
            if k and k not in by_key:
                by_key[k] = it

    if is_get:
        # Extract key after ':' or after 'memory key'.
        key = None
        if ":" in s_raw:
            key = s_raw.split(":", 1)[1].strip()
        if not key:
            parts = s.split()
            if "key" in parts:
                try:
                    key = s_raw.split("key", 1)[1].strip()
                except Exception:
                    key = None
        key = str(key or "").strip().strip("`\"'")
        if not key:
            msg = "ระบุคีย์ที่ต้องการดูด้วย เช่น: memory key sys.sheet_purpose" if _text_is_thai(s_raw) else "Specify a key, e.g. memory key sys.sheet_purpose"
            await _ws_send_json(ws, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
            return True
        hit = by_key.get(key)
        if not isinstance(hit, dict):
            msg = f"ไม่พบคีย์: {key}" if _text_is_thai(s_raw) else f"Key not found: {key}"
            await _ws_send_json(ws, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
            return True
        sc = str(hit.get("scope") or "global")
        pr = _safe_int(hit.get("priority"), default=0)
        val = str(hit.get("value") or "").strip()
        out = f"[{sc}:{pr}] {key}: {val}".strip()
        await _ws_send_json(ws, {"type": "text", "text": out, "instance_id": INSTANCE_ID})
        return True

    if is_search:
        q = None
        if ":" in s_raw:
            q = s_raw.split(":", 1)[1].strip()
        if not q and s.startswith("memory_search"):
            q = s_raw[len("memory_search") :].strip()
        q = str(q or "").strip()
        if not q:
            msg = "ระบุคำค้นด้วย เช่น: ค้น memory: โน้ต" if _text_is_thai(s_raw) else "Provide a query, e.g. memory_search notes"
            await _ws_send_json(ws, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
            return True

        ql = q.lower()
        hits: list[dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            k = str(it.get("key") or "")
            v = str(it.get("value") or "")
            if ql in k.lower() or ql in v.lower():
                hits.append(it)
            if len(hits) >= 20:
                break
        if not hits:
            msg = f"ไม่พบรายการที่ตรงกับ: {q}" if _text_is_thai(s_raw) else f"No matches for: {q}"
            await _ws_send_json(ws, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
            return True
        lines = []
        for it in hits:
            k = str(it.get("key") or "").strip()
            sc = str(it.get("scope") or "global")
            pr = _safe_int(it.get("priority"), default=0)
            lines.append(f"- [{sc}:{pr}] {k}")
        await _ws_send_json(ws, {"type": "text", "text": "\n".join(lines), "instance_id": INSTANCE_ID})
        return True

    # Summary/list.
    top = items[:20]
    lines = []
    for it in top:
        if not isinstance(it, dict):
            continue
        k = str(it.get("key") or "").strip()
        v = str(it.get("value") or "").strip()
        sc = str(it.get("scope") or "global")
        pr = _safe_int(it.get("priority"), default=0)
        if not k:
            continue
        # Keep summary short.
        v_short = v
        if len(v_short) > 140:
            v_short = v_short[:140].rstrip() + "…"
        lines.append(f"- [{sc}:{pr}] {k}: {v_short}")

    title = "สรุป memory ที่โหลดอยู่ (top 20)" if _text_is_thai(s_raw) else "Loaded memory summary (top 20)"
    await _ws_send_json(ws, {"type": "text", "text": title + "\n" + "\n".join(lines), "instance_id": INSTANCE_ID})
    return True


async def _memory_sheet_upsert(
    ws: WebSocket,
    *,
    key: Optional[str],
    value: str,
    scope: str,
    priority: int,
    enabled: bool,
    source: str,
    trace_id: Optional[str] = None,
) -> dict[str, Any]:
    # Authoritative write: update or append to the memory KV5 sheet.
    spreadsheet_id = _system_spreadsheet_id()
    if not spreadsheet_id:
        raise HTTPException(status_code=500, detail="missing_system_spreadsheet_id")

    sheet_name = str(getattr(ws.state, "memory_sheet_name", "") or "").strip()
    if not sheet_name:
        # Ensure we load sheets plan to discover memory sheet.
        try:
            await _load_ws_sheet_memory(ws)
        except Exception:
            pass
        sheet_name = str(getattr(ws.state, "memory_sheet_name", "") or "").strip()
    if not sheet_name:
        raise HTTPException(status_code=500, detail="missing_memory_sheet_name")

    k = str(key or "").strip()
    if not k:
        k = f"auto.{int(time.time())}.{os.urandom(3).hex()}"
    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

    def _col_letter(n: int) -> str:
        s = ""
        x = int(n)
        while x > 0:
            x, r = divmod(x - 1, 26)
            s = chr(ord("A") + r) + s
        return s

    tool_get = _pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
    res = await _mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_name}!A:Z"})
    parsed = _mcp_text_json(res)
    values = None
    if isinstance(parsed, dict):
        values = parsed.get("values")
        if not isinstance(values, list):
            data = parsed.get("data")
            if isinstance(data, dict):
                values = data.get("values")

    header: list[str] = []
    idx: dict[str, int] = {}
    if isinstance(values, list) and values and isinstance(values[0], list):
        header = [str(c or "").strip().lower() for c in values[0]]
        for i, col in enumerate(header):
            if col:
                idx[col] = i

    def _get_col(name: str) -> Optional[int]:
        j = idx.get(name)
        if j is None:
            return None
        try:
            return int(j)
        except Exception:
            return None

    def _ensure_len(row_in: list[Any], n: int) -> list[Any]:
        out = list(row_in)
        while len(out) < n:
            out.append("")
        return out

    key_col = _get_col("key")
    val_col = _get_col("value")
    enabled_col = _get_col("enabled")
    scope_col = _get_col("scope")
    priority_col = _get_col("priority")
    created_at_col = _get_col("created_at")
    updated_at_col = _get_col("updated_at")
    source_col = _get_col("source")

    header_mode = key_col is not None and val_col is not None
    existing_row_num: Optional[int] = None
    existing_row: list[Any] = []
    if header_mode and isinstance(values, list):
        for i, r in enumerate(values[1:], start=2):
            if not isinstance(r, list) or not r:
                continue
            rr = _ensure_len(r, max(1, len(header)))
            if str(rr[key_col] or "").strip() == k:
                existing_row_num = i
                existing_row = rr
                break

    if not header_mode:
        row = [
            k,
            str(value or "").strip(),
            "true" if enabled else "false",
            str(scope or "global").strip() or "global",
            int(priority),
        ]

        existing_row_num = None
        try:
            if isinstance(values, list) and values:
                for i, r in enumerate(values[1:], start=2):
                    if not isinstance(r, list) or not r:
                        continue
                    if str(r[0] or "").strip() == k:
                        existing_row_num = i
                        break
        except Exception:
            existing_row_num = None

        if existing_row_num is not None:
            tool_upd = _pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
            rng = f"{sheet_name}!A{existing_row_num}:E{existing_row_num}"
            res2 = await _mcp_tools_call(
                tool_upd,
                {
                    "spreadsheet_id": spreadsheet_id,
                    "range": rng,
                    "values": [row],
                    "value_input_option": "USER_ENTERED",
                },
            )
            parsed2 = _mcp_text_json(res2)
            return {
                "ok": True,
                "mode": "update",
                "key": k,
                "value": row[1],
                "enabled": enabled,
                "scope": row[3],
                "priority": row[4],
                "source": source,
                "row_number": existing_row_num,
                "result": parsed2 if isinstance(parsed2, dict) else {"raw": parsed2},
            }

        tool_app = _pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
        res3 = await _mcp_tools_call(
            tool_app,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_name}!A:E",
                "values": [row],
                "value_input_option": "USER_ENTERED",
                "insert_data_option": "INSERT_ROWS",
            },
        )
        parsed3 = _mcp_text_json(res3)
        return {
            "ok": True,
            "mode": "append",
            "key": k,
            "value": row[1],
            "enabled": enabled,
            "scope": row[3],
            "priority": row[4],
            "source": source,
            "result": parsed3 if isinstance(parsed3, dict) else {"raw": parsed3},
        }

    col_count = max(1, len(header))
    base_row = _ensure_len(existing_row if existing_row else [], col_count)
    out_row = list(base_row)

    out_row[key_col] = k
    out_row[val_col] = str(value or "").strip()
    if enabled_col is not None:
        out_row[enabled_col] = "true" if enabled else "false"
    if scope_col is not None:
        out_row[scope_col] = str(scope or "global").strip() or "global"
    if priority_col is not None:
        out_row[priority_col] = int(priority)

    if created_at_col is not None:
        prev = str(out_row[created_at_col] or "").strip()
        if not prev:
            out_row[created_at_col] = now_iso
    if updated_at_col is not None:
        out_row[updated_at_col] = now_iso
    if source_col is not None:
        out_row[source_col] = str(source or "").strip()

    last_col = _col_letter(col_count)
    if existing_row_num is not None:
        tool_upd2 = _pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
        rng2 = f"{sheet_name}!A{existing_row_num}:{last_col}{existing_row_num}"
        res4 = await _mcp_tools_call(
            tool_upd2,
            {
                "spreadsheet_id": spreadsheet_id,
                "range": rng2,
                "values": [out_row],
                "value_input_option": "USER_ENTERED",
            },
        )
        parsed4 = _mcp_text_json(res4)
        return {
            "ok": True,
            "mode": "update",
            "key": k,
            "value": str(out_row[val_col] or "").strip(),
            "enabled": enabled,
            "scope": str(out_row[scope_col] if scope_col is not None else (scope or "global")),
            "priority": int(out_row[priority_col]) if priority_col is not None else int(priority),
            "source": source,
            "row_number": existing_row_num,
            "result": parsed4 if isinstance(parsed4, dict) else {"raw": parsed4},
        }

    tool_app2 = _pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
    res5 = await _mcp_tools_call(
        tool_app2,
        {
            "spreadsheet_id": spreadsheet_id,
            "range": f"{sheet_name}!A:{last_col}",
            "values": [out_row],
            "value_input_option": "USER_ENTERED",
            "insert_data_option": "INSERT_ROWS",
        },
    )
    parsed5 = _mcp_text_json(res5)
    return {
        "ok": True,
        "mode": "append",
        "key": k,
        "value": str(out_row[val_col] or "").strip(),
        "enabled": enabled,
        "scope": str(out_row[scope_col] if scope_col is not None else (scope or "global")),
        "priority": int(out_row[priority_col]) if priority_col is not None else int(priority),
        "source": source,
        "result": parsed5 if isinstance(parsed5, dict) else {"raw": parsed5},
    }


async def _handle_knowledge_trigger(ws: WebSocket, text: str) -> bool:
    s_raw = str(text or "")
    s = " ".join(s_raw.strip().lower().split())
    if not s:
        return False

    # Quick triggers.
    is_summary = ("สรุป" in s and "knowledge" in s) or (s.startswith("knowledge ") and "summary" in s)
    is_list = ("list" in s and "knowledge" in s) or (s.startswith("knowledge list"))
    is_get = ("knowledge key" in s) or s.startswith("knowledge_get")
    is_search = s.startswith("knowledge_search") or ("search" in s and "knowledge" in s)

    if not (is_summary or is_list or is_get or is_search):
        return False

    items = getattr(ws.state, "knowledge_items", None)
    if not isinstance(items, list) or not items:
        # Try lazy-load once.
        try:
            await _load_ws_sheet_memory(ws)
        except Exception:
            pass
        items = getattr(ws.state, "knowledge_items", None)

    if not isinstance(items, list) or not items:
        msg = "ยังไม่ได้โหลด knowledge จากชีต (หรืออ่านไม่สำเร็จ)" if _text_is_thai(s_raw) else "Knowledge is not loaded (or failed to load)."
        await _ws_send_json(ws, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
        return True

    by_key: dict[str, dict[str, Any]] = {}
    for it in items:
        if isinstance(it, dict):
            k = str(it.get("key") or "").strip()
            if k and k not in by_key:
                by_key[k] = it

    if is_get:
        key = None
        if ":" in s_raw:
            key = s_raw.split(":", 1)[1].strip()
        if not key:
            parts = s.split()
            if "key" in parts:
                try:
                    key = s_raw.split("key", 1)[1].strip()
                except Exception:
                    key = None
        key = str(key or "").strip().strip("`\"'")
        if not key:
            msg = "ระบุคีย์ที่ต้องการดูด้วย เช่น: knowledge key pricing.rules" if _text_is_thai(s_raw) else "Specify a key, e.g. knowledge key pricing.rules"
            await _ws_send_json(ws, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
            return True
        hit = by_key.get(key)
        if not isinstance(hit, dict):
            msg = f"ไม่พบคีย์: {key}" if _text_is_thai(s_raw) else f"Key not found: {key}"
            await _ws_send_json(ws, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
            return True
        sc = str(hit.get("scope") or "global")
        pr = _safe_int(hit.get("priority"), default=0)
        val = str(hit.get("value") or "").strip()
        out = f"[{sc}:{pr}] {key}: {val}".strip()
        await _ws_send_json(ws, {"type": "text", "text": out, "instance_id": INSTANCE_ID})
        return True

    if is_search:
        q = None
        if ":" in s_raw:
            q = s_raw.split(":", 1)[1].strip()
        if not q and s.startswith("knowledge_search"):
            q = s_raw[len("knowledge_search") :].strip()
        q = str(q or "").strip()
        if not q:
            msg = "ระบุคำค้นด้วย เช่น: knowledge_search: policy" if _text_is_thai(s_raw) else "Provide a query, e.g. knowledge_search policy"
            await _ws_send_json(ws, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
            return True

        ql = q.lower()
        hits: list[dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            k = str(it.get("key") or "")
            v = str(it.get("value") or "")
            if ql in k.lower() or ql in v.lower():
                hits.append(it)
            if len(hits) >= 20:
                break
        if not hits:
            msg = f"ไม่พบรายการที่ตรงกับ: {q}" if _text_is_thai(s_raw) else f"No matches for: {q}"
            await _ws_send_json(ws, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
            return True
        lines = []
        for it in hits:
            k = str(it.get("key") or "").strip()
            sc = str(it.get("scope") or "global")
            pr = _safe_int(it.get("priority"), default=0)
            lines.append(f"- [{sc}:{pr}] {k}")
        await _ws_send_json(ws, {"type": "text", "text": "\n".join(lines), "instance_id": INSTANCE_ID})
        return True

    top = items[:20]
    lines = []
    for it in top:
        if not isinstance(it, dict):
            continue
        k = str(it.get("key") or "").strip()
        v = str(it.get("value") or "").strip()
        sc = str(it.get("scope") or "global")
        pr = _safe_int(it.get("priority"), default=0)
        if not k:
            continue
        v_short = v
        if len(v_short) > 140:
            v_short = v_short[:140].rstrip() + "…"
        lines.append(f"- [{sc}:{pr}] {k}: {v_short}")

    title = "สรุป knowledge ที่โหลดอยู่ (top 20)" if _text_is_thai(s_raw) else "Loaded knowledge summary (top 20)"
    await _ws_send_json(ws, {"type": "text", "text": title + "\n" + "\n".join(lines), "instance_id": INSTANCE_ID})
    return True


def _extract_mcp_text(result: Any) -> str:
    return mcp_client.extract_mcp_text(result)


async def _mcp_web_fetch_text(url: str, max_length: int = 200000) -> str:
    meta = MCP_TOOL_MAP.get("web_fetch") or {}
    mcp_name = str(meta.get("mcp_name") or "").strip()
    if not mcp_name:
        raise HTTPException(status_code=500, detail="mcp_web_fetch_missing")
    result = await _mcp_tools_call(mcp_name, {"url": url, "max_length": int(max_length)})
    return _extract_mcp_text(result)


def _parse_rss_items(xml_text: str) -> list[dict[str, Any]]:
    s = str(xml_text or "")
    if not s.strip():
        return []
    try:
        root = ET.fromstring(s)
    except Exception:
        return []

    items: list[dict[str, Any]] = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        desc = (it.findtext("description") or "").strip()
        if not title and not link:
            continue
        items.append({"title": title, "link": link, "pubDate": pub, "description": desc})
    return items


def _topic_match(text: str, keywords: list[str]) -> bool:
    s = " ".join(str(text or "").lower().split())
    if not s:
        return False
    for k in keywords:
        if k and k.lower() in s:
            return True
    return False


def _build_current_news_context(items: list[dict[str, Any]]) -> dict[str, Any]:
    def pick(keywords: list[str], limit: int = 6) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for it in items:
            blob = f"{it.get('title','')} {it.get('description','')}"
            if _topic_match(blob, keywords):
                out.append(it)
            if len(out) >= limit:
                break
        return out

    iran = pick(
        [
            "iran",
            "israel",
            "tehran",
            "gaza",
            "hezbollah",
            "missile",
            "drone",
            "strike",
            "ceasefire",
            "u.s.",
            "us ",
            "pentagon",
        ]
    )
    gold = pick(["gold", "bullion", "xau"], limit=4)
    usd = pick(["dollar", "usd", "treasury", "yield", "fed"], limit=4)
    oil = pick(["oil", "crude", "brent", "wti", "opec"], limit=4)
    thb = pick(["thai baht", "baht", "thb", "usd/thb", "thb/usd", "bank of thailand", "bot"], limit=4)

    sources: list[str] = []
    for it in (iran + gold + usd + oil + thb):
        link = str(it.get("link") or "").strip()
        if link and link not in sources:
            sources.append(link)

    def brief_lines(section_items: list[dict[str, Any]], max_lines: int) -> list[str]:
        lines: list[str] = []
        for it in section_items[:max_lines]:
            t = str(it.get("title") or "").strip()
            if t:
                lines.append(t)
        return lines

    now_ts = int(time.time())
    return {
        "summary": "CNN current-news context refreshed",
        "updated_at": now_ts,
        "sources": sources,
        "topics": {
            "iran_war": {"headlines": brief_lines(iran, 5), "items": iran},
            "gold": {"headlines": brief_lines(gold, 3), "items": gold},
            "usd": {"headlines": brief_lines(usd, 3), "items": usd},
            "oil": {"headlines": brief_lines(oil, 3), "items": oil},
            "thb": {"headlines": brief_lines(thb, 3), "items": thb},
        },
    }


def _render_current_news_brief(ctx: dict[str, Any]) -> str:
    topics = ctx.get("topics") if isinstance(ctx, dict) else None
    if not isinstance(topics, dict):
        return "Current news: no cached context available. Say 'current news refresh' to fetch from CNN."

    def block(title: str, key: str, max_lines: int) -> str:
        sec = topics.get(key)
        headlines = sec.get("headlines") if isinstance(sec, dict) else None
        if not isinstance(headlines, list) or not headlines:
            return f"{title}: (no recent CNN headlines found)"
        lines = [f"{title}:"]
        for h in headlines[:max_lines]:
            hh = str(h or "").strip()
            if hh:
                lines.append(f"- {hh}")
        return "\n".join(lines)

    parts = [
        block("Iran war", "iran_war", 5),
        block("Gold", "gold", 3),
        block("Dollar/US rates", "usd", 3),
        block("Oil", "oil", 3),
        block("Thai Baht", "thb", 3),
        "\nYou can ask: 'details iran', 'details oil', 'details baht', 'list sources', or 'refresh current news'.",
    ]
    return "\n\n".join([p for p in parts if p.strip()])


async def _refresh_current_news_cache() -> dict[str, Any]:
    feeds = [
        "https://rss.cnn.com/rss/edition.rss",
        "https://rss.cnn.com/rss/edition_world.rss",
        "https://rss.cnn.com/rss/money_latest.rss",
    ]
    all_items: list[dict[str, Any]] = []
    for url in feeds:
        xml_text = await _mcp_web_fetch_text(url, max_length=250000)
        all_items.extend(_parse_rss_items(xml_text))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for it in all_items:
        key = str(it.get("link") or "") or str(it.get("title") or "")
        key = key.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    ctx = _build_current_news_context(deduped)
    _set_news_cache("current-news", ctx)
    _upsert_agent_status(DEFAULT_USER_ID, "current-news", ctx)
    return ctx


async def _handle_current_news_trigger(ws: WebSocket, text: str) -> bool:
    s = " ".join(str(text or "").strip().lower().split())
    if not s:
        return False

    wants_refresh = any(
        p in s
        for p in (
            "refresh current news",
            "current news refresh",
            "refresh news",
            "update current news",
            "current news update",
        )
    )
    wants_sources = "list sources" in s or s == "sources"
    wants_details = s.startswith("details ") or s.startswith("detail ")
    is_trigger = (
        ("current news" in s)
        or ("cnn news" in s)
        or ("thai baht" in s)
        or (" baht" in f" {s}")
        or ("thb" in s)
        or wants_refresh
        or wants_details
        or wants_sources
    )
    if not is_trigger:
        return False

    cached = _get_news_cache("current-news")
    ctx: Optional[dict[str, Any]] = None
    if cached and isinstance(cached.get("payload"), dict):
        ctx = cached["payload"]

    if wants_refresh or ctx is None:
        ctx = await _refresh_current_news_cache()

    if not isinstance(ctx, dict):
        return False

    if wants_sources:
        await ws.send_json(
            {
                "type": "current_news_sources",
                "sources": ctx.get("sources") or [],
                "updated_at": ctx.get("updated_at"),
            }
        )
        return True

    if wants_details:
        topic = str(s.split(" ", 1)[1] if " " in s else "").strip()
        topics = ctx.get("topics") if isinstance(ctx.get("topics"), dict) else {}
        key_map = {
            "iran": "iran_war",
            "iran war": "iran_war",
            "war": "iran_war",
            "gold": "gold",
            "dollar": "usd",
            "usd": "usd",
            "oil": "oil",
            "baht": "thb",
            "thai baht": "thb",
            "thb": "thb",
            "usd/thb": "thb",
        }
        chosen = key_map.get(topic, "")
        if chosen and isinstance(topics, dict) and isinstance(topics.get(chosen), dict):
            await ws.send_json(
                {"type": "current_news_details", "topic": chosen, "data": topics.get(chosen), "updated_at": ctx.get("updated_at")}
            )
        else:
            await ws.send_json(
                {
                    "type": "current_news_details",
                    "topic": topic,
                    "error": "unknown_topic",
                    "hint": "Try: details iran | details gold | details usd | details oil",
                }
            )
        return True

    brief = _render_current_news_brief(ctx)
    await ws.send_json({"type": "current_news", "brief": brief, "context": ctx, "updated_at": ctx.get("updated_at")})
    return True


@app.get("/current-news/brief")
async def current_news_brief() -> dict[str, Any]:
    cached = _get_news_cache("current-news")
    if cached and isinstance(cached.get("payload"), dict):
        ctx = cached["payload"]
        return {"ok": True, "cached": True, "brief": _render_current_news_brief(ctx), "context": ctx}
    ctx2 = await _refresh_current_news_cache()
    return {"ok": True, "cached": False, "brief": _render_current_news_brief(ctx2), "context": ctx2}


@app.post("/current-news/refresh")
async def current_news_refresh() -> dict[str, Any]:
    ctx = await _refresh_current_news_cache()
    return {"ok": True, "context": ctx}


def _parse_deep_research_command(text: str) -> dict[str, str]:
    raw = str(text or "").strip()
    s = " ".join(raw.lower().split())
    if not s:
        return {"action": "", "arg": ""}

    # Start commands
    if s.startswith("deep research:") or s.startswith("deep research "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 2)[2].strip() if len(raw.split()) >= 3 else ""
        return {"action": "start", "arg": arg}
    if s.startswith("research:") or s.startswith("research "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip()
        return {"action": "start", "arg": arg}

    # Status/result commands
    if s.startswith("research status"):
        return {"action": "status", "arg": raw[len("research status") :].strip()}
    if s.startswith("research result"):
        return {"action": "result", "arg": raw[len("research result") :].strip()}
    if s.startswith("research poll"):
        return {"action": "poll", "arg": raw[len("research poll") :].strip()}

    # Follow-up command
    if s.startswith("research followup:") or s.startswith("research followup "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 2)[2].strip() if len(raw.split()) >= 3 else ""
        return {"action": "followup", "arg": arg}
    if s.startswith("followup:") or s.startswith("followup "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip()
        return {"action": "followup", "arg": arg}

    # If the user just says "deep research" with no query, treat as help.
    if s == "deep research" or s == "research" or s == "deep-research":
        return {"action": "help", "arg": ""}

    return {"action": "", "arg": ""}


async def _handle_deep_research_trigger(ws: WebSocket, text: str) -> bool:
    cmd = _parse_deep_research_command(text)
    action = cmd.get("action") or ""
    arg = cmd.get("arg") or ""

    # Trigger matching should also route generic mentions.
    s = " ".join(str(text or "").lower().split())
    is_trigger = (
        action != ""
        or ("deep research" in s)
        or ("research" in s)
        or ("investigate" in s)
        or ("research report" in s)
    )
    if not is_trigger:
        return False

    async def _send_help() -> None:
        await ws.send_json(
            {
                "type": "deep_research_help",
                "message": "Use: 'deep research: <question>' then 'research status' or 'research result'. For followups: 'research followup: <question>'.",
            }
        )

    if action == "help" or (action == "start" and not arg.strip()):
        await _send_help()
        return True

    # Session state: remember last job and interaction for convenience.
    last_job_id = str(getattr(ws.state, "deep_research_job_id", "") or "").strip()
    last_interaction_id = str(getattr(ws.state, "deep_research_interaction_id", "") or "").strip()

    if action == "start":
        res = await _deep_research_worker_post("/deep-research/start", {"query": arg})
        job_id = str(res.get("job_id") or "").strip()
        interaction_id = str(res.get("interaction_id") or "").strip()
        status = res.get("status")
        ws.state.deep_research_job_id = job_id
        ws.state.deep_research_interaction_id = interaction_id
        _upsert_agent_status(
            DEFAULT_USER_ID,
            "deep-research",
            {
                "summary": f"deep research started (status={status})",
                "job_id": job_id,
                "interaction_id": interaction_id,
                "status": status,
                "updated_at": int(time.time()),
            },
        )
        await ws.send_json({"type": "deep_research_started", "worker": res})
        return True

    # Determine target job id.
    target = arg.strip() or last_job_id
    if action in ("status", "poll", "result") and not target:
        await ws.send_json({"type": "deep_research_error", "message": "missing_job_id", "hint": "Start with: deep research: <question>"})
        return True

    if action in ("status", "result"):
        data = await _deep_research_worker_get(f"/deep-research/jobs/{target}")
        job = data.get("job") if isinstance(data, dict) else None
        await ws.send_json({"type": f"deep_research_{action}", "job": job})
        return True

    if action == "poll":
        data = await _deep_research_worker_post(f"/deep-research/poll/{target}", {})
        job = data.get("job") if isinstance(data, dict) else None
        if isinstance(job, dict):
            st = job.get("status")
            if st in ("completed", "failed", "cancelled"):
                # Prefer continuing followups from the completed interaction id.
                ws.state.deep_research_interaction_id = str(job.get("interaction_id") or "")
            _upsert_agent_status(
                DEFAULT_USER_ID,
                "deep-research",
                {
                    "summary": f"deep research poll (status={st})",
                    "job_id": str(job.get("job_id") or target),
                    "interaction_id": str(job.get("interaction_id") or ""),
                    "status": st,
                    "updated_at": int(time.time()),
                },
            )
        await ws.send_json({"type": "deep_research_poll", "job": job})
        return True

    if action == "followup":
        prev = last_interaction_id
        if not prev:
            await ws.send_json(
                {
                    "type": "deep_research_error",
                    "message": "missing_previous_interaction_id",
                    "hint": "Run a deep research first and poll until completed.",
                }
            )
            return True
        res = await _deep_research_worker_post("/deep-research/followup", {"previous_interaction_id": prev, "question": arg})
        job_id = str(res.get("job_id") or "").strip()
        interaction_id = str(res.get("interaction_id") or "").strip()
        status = res.get("status")
        ws.state.deep_research_job_id = job_id
        ws.state.deep_research_interaction_id = interaction_id
        _upsert_agent_status(
            DEFAULT_USER_ID,
            "deep-research",
            {
                "summary": f"deep research followup started (status={status})",
                "job_id": job_id,
                "interaction_id": interaction_id,
                "status": status,
                "updated_at": int(time.time()),
            },
        )
        await ws.send_json({"type": "deep_research_followup_started", "worker": res})
        return True

    await _send_help()
    return True


def _get_user_timezone(user_id: str) -> ZoneInfo:
    # Placeholder for future user-profile timezone retrieval.
    # For now, use a default timezone.
    try:
        return ZoneInfo(DEFAULT_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def _next_morning_brief_at(now: datetime, tz: ZoneInfo, due_at: Optional[datetime]) -> datetime:
    base = due_at.astimezone(tz) if due_at is not None else now.astimezone(tz)
    candidate = datetime(
        year=base.year,
        month=base.month,
        day=base.day,
        hour=MORNING_BRIEF_HOUR,
        minute=MORNING_BRIEF_MINUTE,
        tzinfo=tz,
    )
    if candidate <= now.astimezone(tz):
        candidate = candidate + timedelta(days=1)
    return candidate


def _next_local_morning_at(now: datetime, tz: ZoneInfo, *, hour: int, minute: int, days_ahead: int) -> datetime:
    local = now.astimezone(tz)
    base = datetime(year=local.year, month=local.month, day=local.day, tzinfo=tz)
    base = base + timedelta(days=max(0, int(days_ahead)))
    return base.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)


def _default_hide_until(now: datetime, tz: ZoneInfo, days_ahead: int) -> datetime:
    # User preference: 08:30 local time.
    return _next_local_morning_at(now, tz, hour=8, minute=30, days_ahead=max(1, int(days_ahead)))


def _suggest_reschedule_notify_at(now: datetime, tz: ZoneInfo) -> datetime:
    local = now.astimezone(tz)
    if local.hour < 16:
        cand = local + timedelta(hours=2)
        minute = int(cand.minute)
        rounded = ((minute + 14) // 15) * 15
        if rounded >= 60:
            cand = cand.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            cand = cand.replace(minute=rounded, second=0, microsecond=0)
        return cand
    return _default_hide_until(now, tz, days_ahead=1)


def _parse_time_from_text(text: str, now: datetime, tz: ZoneInfo) -> tuple[Optional[datetime], Optional[str]]:
    s = str(text or "").strip().lower()
    if not s:
        return None, None

    day: Optional[datetime] = None
    if re.search(r"\btomorrow\b", s):
        local = now.astimezone(tz)
        day = datetime(local.year, local.month, local.day, tzinfo=tz) + timedelta(days=1)
    elif re.search(r"\btoday\b", s):
        local = now.astimezone(tz)
        day = datetime(local.year, local.month, local.day, tzinfo=tz)

    time_match = re.search(r"\b(at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", s)
    if not time_match and day is None:
        return None, None

    hour = 9
    minute = 0
    meridiem = None
    if time_match:
        hour = int(time_match.group(2))
        minute = int(time_match.group(3) or "0")
        meridiem = time_match.group(4)
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0

    if day is None:
        local = now.astimezone(tz)
        day = datetime(local.year, local.month, local.day, tzinfo=tz)
        # If time already passed today, treat it as tomorrow.
        candidate = day.replace(hour=hour, minute=minute)
        if candidate <= local:
            candidate = candidate + timedelta(days=1)
        return candidate.astimezone(timezone.utc), f"{candidate.isoformat()}"

    candidate = day.replace(hour=hour, minute=minute)
    return candidate.astimezone(timezone.utc), f"{candidate.isoformat()}"


def _reminder_dedupe_key(title: str, due_at_ts: Optional[int], schedule_type: str) -> str:
    t = " ".join(str(title or "").strip().lower().split())
    d = str(int(due_at_ts)) if due_at_ts is not None else "none"
    s = " ".join(str(schedule_type or "").strip().lower().split())
    return f"{t}|{d}|{s}"[:512]


async def _weaviate_get_memory_item_by_external_key(external_key: str) -> Optional[dict[str, Any]]:
    await _weaviate_ensure_schema()
    ek = str(external_key or "").strip()
    if not ek:
        return None
    obj_id = _weaviate_object_uuid(ek)
    try:
        existing = await _weaviate_request("GET", f"/v1/objects/{obj_id}")
    except Exception:
        return None
    if not isinstance(existing, dict):
        return None
    props = existing.get("properties")
    if not isinstance(props, dict):
        return None
    return props





async def _broadcast_to_user(user_id: str, payload: dict[str, Any]) -> None:
    conns = list(_ws_by_user.get(user_id, set()))
    if not conns:
        return
    dead: list[WebSocket] = []
    for ws in conns:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    if dead:
        s = _ws_by_user.get(user_id)
        if s is not None:
            for ws in dead:
                s.discard(ws)


@app.on_event("startup")
async def _startup() -> None:
    global _SHEETS_LOGS_TASK
    global _SHEETS_LOGS_SERVER_TASK
    try:
        _init_session_db()
    except Exception as e:
        logger.warning("session_db_init_failed error=%s", e)
    try:
        _ensure_cars_data_dirs()
    except Exception as e:
        logger.warning("cars_data_dir_init_failed error=%s", e)
    try:
        await _startup_resync_from_weaviate()
    except Exception as e:
        logger.warning("startup_resync_failed error=%s", e)

    # Prewarm system sheets into cache (does not require a UI connection).
    try:
        asyncio.create_task(_startup_prewarm_sheets(), name="startup_prewarm_sheets")
    except Exception as e:
        logger.warning("startup_prewarm_task_failed error=%s", e)

    try:
        if _SHEETS_LOGS_TASK is None or _SHEETS_LOGS_TASK.done():
            _SHEETS_LOGS_TASK = asyncio.create_task(_sheets_logs_flush_loop(), name="sheets_logs_flush")
    except Exception:
        pass

    try:
        if _SHEETS_LOGS_SERVER_TASK is None or _SHEETS_LOGS_SERVER_TASK.done():
            _SHEETS_LOGS_SERVER_TASK = asyncio.create_task(_sheets_logs_server_loop(), name="sheets_logs_server")
    except Exception:
        pass

    # Optional: auto-watch GitHub Actions and broadcast completion to UI.
    try:
        sys_kv = _sys_kv_snapshot()
    except Exception:
        sys_kv = {}

    def _sys_str(k: str) -> str:
        if not isinstance(sys_kv, dict):
            return ""
        return str(sys_kv.get(k) or "").strip()

    raw_enabled = _sys_str("github.actions.watch.enabled")
    try:
        enabled = _parse_bool_cell(raw_enabled) if raw_enabled else False
    except Exception:
        enabled = False

    if enabled:
        try:
            owner = (
                _sys_str("github.actions.watch.owner")
                or "tonezzz"
            ).strip() or "tonezzz"
            repo = (
                _sys_str("github.actions.watch.repo")
                or "chaba"
            ).strip() or "chaba"
            branch_raw = _sys_str("github.actions.watch.branch")
            branch = branch_raw.strip() or None
            event_raw = _sys_str("github.actions.watch.event")
            event = event_raw.strip() or None

            poll_raw = _sys_str("github.actions.watch.poll_seconds")
            try:
                poll_seconds = float(poll_raw) if poll_raw else 15.0
            except Exception:
                poll_seconds = 15.0
            poll_seconds = max(2.0, min(300.0, poll_seconds))

            stop_raw = _sys_str("github.actions.watch.stop_on_completed")
            try:
                stop_on_completed = _parse_bool_cell(stop_raw) if stop_raw else True
            except Exception:
                stop_on_completed = True

            timeout_raw = _sys_str("github.actions.watch.max_runtime_seconds")
            try:
                max_runtime_seconds = float(timeout_raw) if timeout_raw else 900.0
            except Exception:
                max_runtime_seconds = 900.0
            max_runtime_seconds = max(5.0, min(7200.0, max_runtime_seconds))

            key = _github_watch_key(owner, repo, branch, event)
            existing = _GITHUB_WATCH_TASKS.get(key)
            if not (existing and not existing.done()):
                _GITHUB_WATCH_TASKS[key] = asyncio.create_task(
                    _github_watch_loop(
                        key=key,
                        owner=owner,
                        repo=repo,
                        branch=branch,
                        event=event,
                        poll_seconds=poll_seconds,
                        stop_on_completed=stop_on_completed,
                        max_runtime_seconds=max_runtime_seconds,
                    ),
                    name=f"github_watch:{key}",
                )
        except Exception as e:
            logger.warning("github_watch_autostart_failed error=%s", e)


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _SHEETS_LOGS_TASK
    global _SHEETS_LOGS_SERVER_TASK
    if _SHEETS_LOGS_TASK is not None:
        _SHEETS_LOGS_TASK.cancel()
        _SHEETS_LOGS_TASK = None
    if _SHEETS_LOGS_SERVER_TASK is not None:
        _SHEETS_LOGS_SERVER_TASK.cancel()
        _SHEETS_LOGS_SERVER_TASK = None


def _mcp_text_json(result: Any) -> Any:
    return mcp_client.mcp_text_json(result)


async def _google_calendar_create_reminder_event(*, title: str, due_at_utc: datetime, tz: ZoneInfo, source_text: str) -> dict[str, Any]:
    due_local = due_at_utc.astimezone(tz)
    end_local = due_local + timedelta(minutes=5)
    payload: dict[str, Any] = {
        "summary": str(title or "Reminder").strip() or "Reminder",
        "description": str(source_text or "").strip(),
        "start": due_local.isoformat(),
        "end": end_local.isoformat(),
        "timezone": tz.key,
        "reminders_minutes": [10],
    }
    await _mcp_tools_call("google-calendar_1mcp_google_calendar_ensure_jarvis_calendar", {})
    res = await _mcp_tools_call("google-calendar_1mcp_google_calendar_create_event", payload)
    parsed = _mcp_text_json(res)
    if isinstance(parsed, dict):
        return parsed
    return {"ok": True, "raw": res}


def _set_session_last_item(session_id: str, slot: str, kind: str, payload: dict[str, Any]) -> None:
    db_session.set_session_last_item(SESSION_DB_PATH, session_id, slot, kind, payload)


def _get_session_last_item(session_id: str, slot: str) -> Optional[dict[str, Any]]:
    return db_session.get_session_last_item(SESSION_DB_PATH, session_id, slot)


def _create_pending_write(session_id: str, action: str, payload: Any) -> str:
    return db_session.create_pending_write(SESSION_DB_PATH, session_id, action, payload)


def _list_pending_writes(session_id: str) -> list[dict[str, Any]]:
    return db_session.list_pending_writes(SESSION_DB_PATH, session_id)


def _pop_pending_write(session_id: str, confirmation_id: str) -> Optional[dict[str, Any]]:
    return db_session.pop_pending_write(SESSION_DB_PATH, session_id, confirmation_id)


def _cancel_pending_write(session_id: str, confirmation_id: str) -> bool:
    return db_session.cancel_pending_write(SESSION_DB_PATH, session_id, confirmation_id)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"] ,
)


def _split_phrases(value: Any) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    parts: list[str] = []
    for line in raw.replace("\r", "\n").split("\n"):
        # Allow inline comments in system sheet config cells.
        # Example: "memory:memory  # authoritative".
        try:
            line = str(line or "")
            if "#" in line:
                line = line.split("#", 1)[0]
        except Exception:
            pass
        for p in str(line or "").split(","):
            s = str(p or "").strip()
            if s:
                parts.append(s)
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        k = p.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def _sys_kv_snapshot() -> dict[str, str]:
    cached = _get_cached_sheet_memory()
    if isinstance(cached, dict):
        skv = cached.get("sys_kv")
        if isinstance(skv, dict):
            out: dict[str, str] = {}
            for k, v in skv.items():
                ks = str(k or "").strip()
                if not ks:
                    continue
                out[ks] = str(v or "").strip()
            return out
    return {}


def _voice_command_config_from_sys_kv(sys_kv: dict[str, str]) -> dict[str, Any]:
    def _get(k: str, default: str = "") -> str:
        v = str(sys_kv.get(k) or "").strip()
        return v if v else default

    enabled = True
    raw_enabled = _get("voice_cmd.enabled", "")
    if raw_enabled:
        try:
            enabled = _parse_bool_cell(raw_enabled)
        except Exception:
            enabled = True

    try:
        debounce_ms = int(float(_get("voice_cmd.debounce_ms", "10000")))
        debounce_ms = max(0, min(debounce_ms, 120_000))
    except Exception:
        debounce_ms = 10_000

    return {
        "enabled": enabled,
        "debounce_ms": debounce_ms,
        "reload": {
            "enabled": _parse_bool_cell(_get("voice_cmd.reload.enabled", "true")),
            "phrases": _split_phrases(_get("voice_cmd.reload.phrases", "")),
            "mode_keywords": {
                "gems": _split_phrases(_get("voice_cmd.reload.keywords.gems", "gems,gem,models,model,เจม,โมเดล")),
                "knowledge": _split_phrases(_get("voice_cmd.reload.keywords.knowledge", "knowledge,kb,know,ความรู้")),
                "memory": _split_phrases(_get("voice_cmd.reload.keywords.memory", "memory,mem,เมม,เมมโม")),
            },
        },
        "reminders_add": {
            "enabled": _parse_bool_cell(_get("voice_cmd.reminders_add.enabled", "true")),
            "phrases": _split_phrases(_get("voice_cmd.reminders_add.phrases", "")),
        },
        "gems_list": {
            "enabled": _parse_bool_cell(_get("voice_cmd.gems_list.enabled", "true")),
            "phrases": _split_phrases(_get("voice_cmd.gems_list.phrases", "")),
        },
        "github_watch": {
            "enabled": _parse_bool_cell(_get("voice_cmd.github_watch.enabled", "false")),
            "phrases": _split_phrases(
                _get(
                    "voice_cmd.github_watch.phrases",
                    "watch build,watch action,watch github action,github action status,ดู build,ดู action,ดู github action,เช็ค build",
                )
            ),
            "owner": _get("voice_cmd.github_watch.owner", "tonezzz"),
            "repo": _get("voice_cmd.github_watch.repo", "chaba"),
            "branch": _get("voice_cmd.github_watch.branch", ""),
            "event": _get("voice_cmd.github_watch.event", ""),
            "poll_seconds": float(_safe_int(_get("voice_cmd.github_watch.poll_seconds", "15"), default=15)),
            "timeout_seconds": float(_safe_int(_get("voice_cmd.github_watch.timeout_seconds", "3600"), default=3600)),
            "debounce_ms": _safe_int(_get("voice_cmd.github_watch.debounce_ms", str(debounce_ms)), default=debounce_ms),
        },
    }


@app.get("/config/voice_commands")
@app.get("/jarvis/config/voice_commands")
def config_voice_commands() -> dict[str, Any]:
    sys_kv = _sys_kv_snapshot()
    cfg = _voice_command_config_from_sys_kv(sys_kv)
    return {"ok": True, "config": cfg}


@app.get("/health")
@app.get("/jarvis/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "jarvis-backend",
        "instance_id": INSTANCE_ID,
        "weaviate_enabled": _weaviate_enabled(),
        "build": {
            "git_sha": str(os.getenv("JARVIS_GIT_SHA") or os.getenv("GIT_SHA") or "").strip() or None,
            "image_tag": str(os.getenv("JARVIS_IMAGE_TAG") or os.getenv("IMAGE_TAG") or "").strip() or None,
        },
    }


@app.get("/debug/tools")
@app.get("/jarvis/debug/tools")
def debug_tools() -> dict[str, Any]:
    sys_kv = _sys_kv_snapshot()
    tools = _mcp_tool_declarations()
    names: list[str] = []
    for t in tools:
        if isinstance(t, dict):
            n = str(t.get("name") or "").strip()
            if n:
                names.append(n)
    names = sorted(set(names))
    enabled = {
        "memo": feature_enabled("memo", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True),
        "memory": feature_enabled("memory", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True),
        "knowledge": feature_enabled("knowledge", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True),
    }
    env = {
        "JARVIS_FEATURE_MEMO_ENABLED": os.getenv("JARVIS_FEATURE_MEMO_ENABLED"),
        "JARVIS_FEATURE_MEMORY_ENABLED": os.getenv("JARVIS_FEATURE_MEMORY_ENABLED"),
        "JARVIS_FEATURE_KNOWLEDGE_ENABLED": os.getenv("JARVIS_FEATURE_KNOWLEDGE_ENABLED"),
    }
    return {"ok": True, "enabled": enabled, "env": env, "tools": names}


@app.get("/debug/memo")
@app.get("/jarvis/debug/memo")
async def debug_memo() -> dict[str, Any]:
    sys_kv = _sys_kv_snapshot()

    # Best-effort: if sys_kv cache is cold, try to load once so this endpoint reflects the sheet.
    try:
        spreadsheet_id0, sheet_name0 = _memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
        if not sheet_name0:
            class _DummyWS:
                def __init__(self) -> None:
                    from types import SimpleNamespace

                    self.state = SimpleNamespace()

            await _load_ws_system_kv(_DummyWS())
            sys_kv = _sys_kv_snapshot()
    except Exception:
        pass

    feat = feature_enabled("memo", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True)
    memo_enabled = _sys_kv_bool(sys_kv, "memo.enabled", default=False)
    spreadsheet_id, sheet_name = _memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
    sheet_a1 = _sheet_name_to_a1(sheet_name, default="memo") if sheet_name else ""

    auth_status: Any = None
    auth_err: str | None = None
    try:
        tool_auth = _pick_sheets_tool_name("google_sheets_auth_status", "google_sheets_auth_status")
        auth_status = _mcp_text_json(await _mcp_tools_call(tool_auth, {}))
    except Exception as e:
        auth_err = f"{type(e).__name__}: {e}"

    header: Any = None
    header_err: str | None = None
    try:
        if spreadsheet_id and sheet_a1:
            header = await _sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
    except Exception as e:
        header_err = f"{type(e).__name__}: {e}"

    return {
        "ok": True,
        "feature_enabled": feat,
        "memo_enabled": memo_enabled,
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "sheet_a1": sheet_a1,
        "sheets_auth_status": auth_status,
        "sheets_auth_error": auth_err,
        "header": header,
        "header_error": header_err,
    }


@app.get("/debug/counts")
@app.get("/jarvis/debug/counts")
async def debug_counts() -> dict[str, Any]:
    sys_kv = _sys_kv_snapshot()

    # Memory count (best-effort)
    mem_n = 0
    mem_cached_n = 0
    mem_sheet: str | None = None
    try:
        mem_sheet = str((_SHEET_MEMORY_CACHE.get("memory_sheet_name") if isinstance(_SHEET_MEMORY_CACHE, dict) else "") or "").strip() or None
        cached_items = _SHEET_MEMORY_CACHE.get("memory_items") if isinstance(_SHEET_MEMORY_CACHE, dict) else None
        mem_cached_n = len(cached_items) if isinstance(cached_items, list) else 0
    except Exception:
        mem_cached_n = 0

    try:
        # If cache is empty, try to lazy-load once.
        if mem_cached_n <= 0:
            class _DummyWS:
                def __init__(self) -> None:
                    from types import SimpleNamespace

                    self.state = SimpleNamespace()

            ws = _DummyWS()
            await _load_ws_sheet_memory(ws)
            items = getattr(ws.state, "memory_items", None)
            mem_n = len(items) if isinstance(items, list) else 0
            ms = str(getattr(ws.state, "memory_sheet_name", "") or "").strip()
            if ms:
                mem_sheet = ms
        else:
            mem_n = mem_cached_n
    except Exception:
        mem_n = mem_cached_n

    # Memo row count (best-effort)
    memo_rows = 0
    memo_sheet_name: str | None = None
    memo_spreadsheet_id: str | None = None
    memo_error: str | None = None
    try:
        memo_spreadsheet_id, memo_sheet_name = _memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
        if memo_spreadsheet_id and memo_sheet_name:
            sheet_a1 = _sheet_name_to_a1(memo_sheet_name, default="memo")
            tool_get = _pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
            res = await _mcp_tools_call(tool_get, {"spreadsheet_id": memo_spreadsheet_id, "range": f"{sheet_a1}!A:A"})
            parsed = _mcp_text_json(res)
            values = None
            if isinstance(parsed, dict):
                values = parsed.get("values")
                if not isinstance(values, list):
                    data = parsed.get("data")
                    if isinstance(data, dict):
                        values = data.get("values")
            if isinstance(values, list) and values:
                # first row is header
                memo_rows = max(0, len(values) - 1)
    except Exception as e:
        memo_error = f"{type(e).__name__}: {e}"

    return {
        "ok": True,
        "memory": {
            "sheet": mem_sheet,
            "count": int(mem_n),
            "cached_count": int(mem_cached_n),
        },
        "memo": {
            "spreadsheet_id": memo_spreadsheet_id,
            "sheet": memo_sheet_name,
            "rows": int(memo_rows),
            "error": memo_error,
        },
    }


@app.get("/status")
@app.get("/jarvis/status")
@app.get("/api/status")
@app.get("/jarvis/api/status")
async def status() -> dict[str, Any]:
    st = _STARTUP_PREWARM_STATUS if isinstance(_STARTUP_PREWARM_STATUS, dict) else {}
    try:
        uptime_s = max(0.0, float(time.time() - float(_PROCESS_START_TS)))
    except Exception:
        uptime_s = 0.0
    hostname = str(os.getenv("HOSTNAME") or "").strip() or None
    try:
        pid = int(os.getpid())
    except Exception:
        pid = None
    out = {
        "ok": True,
        "service": "jarvis-backend",
        "instance_id": INSTANCE_ID,
        "hostname": hostname,
        "pid": pid,
        "uptime_s": uptime_s,
        "weaviate_enabled": _weaviate_enabled(),
        "startup_prewarm": {
            "ts": int(st.get("ts") or 0),
            "running": bool(st.get("running")),
            "ok": bool(st.get("ok")),
            "memory_n": int(st.get("memory_n") or 0),
            "knowledge_n": int(st.get("knowledge_n") or 0),
            "error": str(st.get("error") or "").strip(),
        },
    }

    # Best-effort: include container/module status rows when Portainer is configured.
    try:
        sys_kv = _sys_kv_snapshot()
        cfg = _portainer_cfg(sys_kv)
        if cfg.get("url") and cfg.get("api_key") and cfg.get("endpoint_id") and cfg.get("stack_name"):
            out["containers"] = await _portainer_list_stack_containers(sys_kv=sys_kv)
    except HTTPException as e:
        out["containers_error"] = e.detail
    except Exception as e:
        out["containers_error"] = str(e)

    return out


def _github_ro_token() -> str:
    return str(os.getenv("GITHUB_PERSONAL_TOKEN_RO") or "").strip()


async def _github_api_get(path: str, *, params: dict[str, Any] | None = None) -> Any:
    token = _github_ro_token()
    if not token:
        raise HTTPException(status_code=500, detail="missing_github_personal_token_ro")

    url = f"https://api.github.com{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "jarvis-backend",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.get(url, headers=headers, params=params)
        if res.status_code >= 400:
            detail: Any
            try:
                detail = res.json()
            except Exception:
                detail = res.text
            raise HTTPException(status_code=int(res.status_code), detail={"github_error": detail})
        try:
            return res.json()
        except Exception:
            return res.text


def _normalize_run_summary(run: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(run, dict):
        return {}
    return {
        "id": run.get("id"),
        "name": run.get("name") or run.get("display_title"),
        "event": run.get("event"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "run_started_at": run.get("run_started_at"),
        "head_branch": run.get("head_branch"),
        "head_sha": run.get("head_sha"),
        "html_url": run.get("html_url"),
    }


_GITHUB_WATCH_TASKS: dict[str, asyncio.Task[None]] = {}
_GITHUB_WATCH_STATE: dict[str, dict[str, Any]] = {}


def _github_watch_key(owner: str, repo: str, branch: str | None, event: str | None) -> str:
    o = str(owner or "").strip().lower()
    r = str(repo or "").strip().lower()
    b = str(branch or "").strip().lower()
    e = str(event or "").strip().lower()
    return f"{o}/{r}?branch={b}&event={e}"


async def _github_watch_loop(
    *,
    key: str,
    owner: str,
    repo: str,
    branch: str | None,
    event: str | None,
    poll_seconds: float,
    stop_on_completed: bool = True,
    max_runtime_seconds: float = 900.0,
) -> None:
    last_run_id: str | None = None
    last_status: str | None = None
    last_conclusion: str | None = None

    started_ts = time.time()

    while True:
        try:
            payload = await github_actions_latest(owner=owner, repo=repo, branch=branch, event=event)
            run = payload.get("run") if isinstance(payload, dict) else None
            if not isinstance(run, dict) or not run:
                _GITHUB_WATCH_STATE[key] = {
                    "owner": owner,
                    "repo": repo,
                    "branch": branch,
                    "event": event,
                    "run": None,
                    "ts": int(time.time()),
                }
            else:
                run_id = str(run.get("id") or "").strip() or None
                status = str(run.get("status") or "").strip() or None
                conclusion = str(run.get("conclusion") or "").strip() or None

                _GITHUB_WATCH_STATE[key] = {
                    "owner": owner,
                    "repo": repo,
                    "branch": branch,
                    "event": event,
                    "run": run,
                    "ts": int(time.time()),
                }

                if run_id and run_id != last_run_id:
                    last_run_id = run_id
                    last_status = status
                    try:
                        _append_ui_log_entries(
                            [
                                {
                                    "type": "github_actions",
                                    "kind": "run_detected",
                                    "ts": int(time.time()),
                                    "key": key,
                                    "owner": owner,
                                    "repo": repo,
                                    "branch": branch,
                                    "event": event,
                                    "run": run,
                                }
                            ]
                        )
                    except Exception:
                        pass
                    await _broadcast_to_user(
                        DEFAULT_USER_ID,
                        {
                            "type": "github_actions",
                            "kind": "run_detected",
                            "key": key,
                            "owner": owner,
                            "repo": repo,
                            "branch": branch,
                            "event": event,
                            "run": run,
                        },
                    )
                    try:
                        name = str(run.get("name") or "").strip() or "workflow"
                        st = (status or "").strip().lower()
                        if st and st != "completed":
                            msg = f"CI started: {name}"
                            await _broadcast_to_user(DEFAULT_USER_ID, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
                    except Exception:
                        pass

                if status and status != last_status:
                    last_status = status

                if status == "completed" and (conclusion != last_conclusion or last_conclusion is None):
                    last_conclusion = conclusion
                    try:
                        _append_ui_log_entries(
                            [
                                {
                                    "type": "github_actions",
                                    "kind": "run_completed",
                                    "ts": int(time.time()),
                                    "key": key,
                                    "owner": owner,
                                    "repo": repo,
                                    "branch": branch,
                                    "event": event,
                                    "run": run,
                                }
                            ]
                        )
                    except Exception:
                        pass
                    await _broadcast_to_user(
                        DEFAULT_USER_ID,
                        {
                            "type": "github_actions",
                            "kind": "run_completed",
                            "key": key,
                            "owner": owner,
                            "repo": repo,
                            "branch": branch,
                            "event": event,
                            "run": run,
                        },
                    )
                    try:
                        name = str(run.get("name") or "").strip() or "workflow"
                        conc = str(conclusion or "completed").strip()
                        msg = f"CI completed: {name} ({conc})"
                        await _broadcast_to_user(DEFAULT_USER_ID, {"type": "text", "text": msg, "instance_id": INSTANCE_ID})
                    except Exception:
                        pass
                    if stop_on_completed:
                        try:
                            st = dict(_GITHUB_WATCH_STATE.get(key) or {})
                            st["running"] = False
                            st["stopped_reason"] = "completed"
                            st["ts"] = int(time.time())
                            _GITHUB_WATCH_STATE[key] = st
                        except Exception:
                            pass
                        return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _GITHUB_WATCH_STATE[key] = {
                "owner": owner,
                "repo": repo,
                "branch": branch,
                "event": event,
                "run": None,
                "ts": int(time.time()),
                "error": str(e),
            }
            try:
                _append_ui_log_entries(
                    [
                        {
                            "type": "github_actions",
                            "kind": "watch_error",
                            "ts": int(time.time()),
                            "key": key,
                            "owner": owner,
                            "repo": repo,
                            "branch": branch,
                            "event": event,
                            "error": f"{type(e).__name__}: {str(e)}",
                        }
                    ]
                )
            except Exception:
                pass
            try:
                detail = str(e)
                hint = ""
                if "missing_github_personal_token_ro" in detail:
                    hint = " (missing GITHUB_PERSONAL_TOKEN_RO)"
                await _broadcast_to_user(
                    DEFAULT_USER_ID,
                    {
                        "type": "text",
                        "text": f"GitHub Actions watch error for {owner}/{repo} branch={branch or '*'} event={event or '*'}: {type(e).__name__}: {detail}{hint}",
                        "instance_id": INSTANCE_ID,
                    },
                )
            except Exception:
                pass
        try:
            if max_runtime_seconds and (time.time() - started_ts) >= float(max_runtime_seconds):
                try:
                    _append_ui_log_entries(
                        [
                            {
                                "type": "github_actions",
                                "kind": "watch_timeout",
                                "ts": int(time.time()),
                                "key": key,
                                "owner": owner,
                                "repo": repo,
                                "branch": branch,
                                "event": event,
                                "timeout_seconds": float(max_runtime_seconds),
                            }
                        ]
                    )
                except Exception:
                    pass
                try:
                    st = dict(_GITHUB_WATCH_STATE.get(key) or {})
                    st["running"] = False
                    st["stopped_reason"] = "timeout"
                    st["ts"] = int(time.time())
                    _GITHUB_WATCH_STATE[key] = st
                except Exception:
                    pass
                return
        except Exception:
            pass

        await asyncio.sleep(poll_seconds)


class GitHubActionsWatchStartRequest(BaseModel):
    owner: str = "tonezzz"
    repo: str = "chaba"
    branch: str | None = None
    event: str | None = None
    poll_seconds: float = 15.0
    stop_on_completed: bool = True
    max_runtime_seconds: float = 900.0


@app.post("/github/actions/watch/start")
@app.post("/jarvis/github/actions/watch/start")
async def github_actions_watch_start(req: GitHubActionsWatchStartRequest) -> dict[str, Any]:
    try:
        token = _github_ro_token()
        if not token:
            raise HTTPException(status_code=500, detail="missing_github_personal_token_ro")

        owner = str(req.owner or "").strip() or "tonezzz"
        repo = str(req.repo or "").strip() or "chaba"
        branch = str(req.branch).strip() if req.branch is not None else None
        event = str(req.event).strip() if req.event is not None else None

        try:
            poll_seconds = float(req.poll_seconds)
        except Exception:
            poll_seconds = 15.0
        poll_seconds = max(2.0, min(300.0, poll_seconds))

        stop_on_completed = bool(req.stop_on_completed is True)
        try:
            max_runtime_seconds = float(req.max_runtime_seconds)
        except Exception:
            max_runtime_seconds = 900.0
        max_runtime_seconds = max(5.0, min(7200.0, max_runtime_seconds))

        key = _github_watch_key(owner, repo, branch, event)
        existing = _GITHUB_WATCH_TASKS.get(key)
        if existing and not existing.done():
            return {"ok": True, "started": False, "key": key, "already_running": True, "state": _GITHUB_WATCH_STATE.get(key)}

        task = asyncio.create_task(
            _github_watch_loop(
                key=key,
                owner=owner,
                repo=repo,
                branch=branch,
                event=event,
                poll_seconds=poll_seconds,
                stop_on_completed=stop_on_completed,
                max_runtime_seconds=max_runtime_seconds,
            )
        )
        _GITHUB_WATCH_TASKS[key] = task
        _GITHUB_WATCH_STATE[key] = {
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "event": event,
            "poll_seconds": poll_seconds,
            "stop_on_completed": stop_on_completed,
            "max_runtime_seconds": max_runtime_seconds,
            "ts": int(time.time()),
            "running": True,
        }
        return {"ok": True, "started": True, "key": key}
    except HTTPException:
        raise
    except Exception as e:
        detail = f"{type(e).__name__}: {str(e)}"
        raise HTTPException(status_code=500, detail={"error": "github_actions_watch_start_failed", "detail": detail})


@app.post("/github/actions/watch/stop")
@app.post("/jarvis/github/actions/watch/stop")
async def github_actions_watch_stop(
    owner: str = "tonezzz",
    repo: str = "chaba",
    branch: str | None = None,
    event: str | None = None,
) -> dict[str, Any]:
    key = _github_watch_key(owner, repo, branch, event)
    task = _GITHUB_WATCH_TASKS.get(key)
    if not task:
        return {"ok": True, "stopped": False, "key": key, "missing": True}
    try:
        task.cancel()
    except Exception:
        pass
    return {"ok": True, "stopped": True, "key": key}


@app.get("/github/actions/watch/list")
@app.get("/jarvis/github/actions/watch/list")
def github_actions_watch_list() -> dict[str, Any]:
    items: list[dict[str, Any]] = []

    keys: set[str] = set()
    try:
        keys.update(list(_GITHUB_WATCH_TASKS.keys()))
    except Exception:
        pass
    try:
        keys.update(list(_GITHUB_WATCH_STATE.keys()))
    except Exception:
        pass

    for key in sorted(keys):
        task = _GITHUB_WATCH_TASKS.get(key)
        running = bool(task is not None and not task.done())
        st = dict(_GITHUB_WATCH_STATE.get(key) or {})
        st["key"] = key
        st["running"] = running
        items.append(st)

    return {"ok": True, "watches": items}


@app.get("/github/actions/latest")
@app.get("/jarvis/github/actions/latest")
async def github_actions_latest(
    owner: str = "tonezzz",
    repo: str = "chaba",
    branch: str | None = None,
    event: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": 1}
    if branch:
        params["branch"] = str(branch)
    if event:
        params["event"] = str(event)

    data = await _github_api_get(f"/repos/{owner}/{repo}/actions/runs", params=params)
    runs = data.get("workflow_runs") if isinstance(data, dict) else None
    latest = runs[0] if isinstance(runs, list) and runs else None
    return {
        "ok": True,
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "event": event,
        "run": _normalize_run_summary(latest) if isinstance(latest, dict) else None,
    }


@app.get("/github/actions/watch")
@app.get("/jarvis/github/actions/watch")
async def github_actions_watch(
    owner: str = "tonezzz",
    repo: str = "chaba",
    branch: str | None = None,
    event: str | None = None,
    poll_seconds: float = 10.0,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    try:
        poll_seconds = float(poll_seconds)
    except Exception:
        poll_seconds = 10.0
    poll_seconds = max(2.0, min(120.0, poll_seconds))

    try:
        timeout_seconds = float(timeout_seconds)
    except Exception:
        timeout_seconds = 600.0
    timeout_seconds = max(5.0, min(7200.0, timeout_seconds))

    started = time.time()
    last_run: dict[str, Any] | None = None
    while True:
        payload = await github_actions_latest(owner=owner, repo=repo, branch=branch, event=event)
        run = payload.get("run") if isinstance(payload, dict) else None
        last_run = run if isinstance(run, dict) else last_run

        if isinstance(run, dict) and str(run.get("status") or "") == "completed":
            return {
                "ok": True,
                "owner": owner,
                "repo": repo,
                "branch": branch,
                "event": event,
                "completed": True,
                "run": run,
            }

        if time.time() - started >= timeout_seconds:
            return {
                "ok": True,
                "owner": owner,
                "repo": repo,
                "branch": branch,
                "event": event,
                "completed": False,
                "run": last_run,
                "timeout_seconds": timeout_seconds,
            }

        await asyncio.sleep(poll_seconds)


@app.post("/gem/demo", response_model=GemDemoResponse)
async def gem_demo(req: GemDemoRequest) -> GemDemoResponse:
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="missing_api_key")

    # Auto-switch to progress gem for delay-prone sheet ops unless caller explicitly selected a gem.
    effective_gem = req.gem
    if (effective_gem is None or not str(effective_gem).strip()) and _should_auto_progress_gem(str(req.text)):
        effective_gem = "sheet_ops_progress"

    gem_name = _resolve_gem_name(effective_gem)
    extra = _gem_instruction(gem_name)
    system_instruction = "You are Jarvis. Respond to the user with ONLY the final answer."
    if extra:
        system_instruction = system_instruction + "\n" + extra

    try:
        cached = _get_cached_sheet_memory()
        sys_kv = cached.get("sys_kv") if isinstance(cached, dict) else None
        _, gem_model = await _resolve_gem_instruction_and_model(
            gem_name=gem_name,
            sys_kv=sys_kv if isinstance(sys_kv, dict) else None,
        )
    except Exception:
        gem_model = None

    model = _normalize_model_name(
        str(req.model or (gem_model or "") or os.getenv("GEMINI_TEXT_MODEL") or "gemini-2.0-flash").strip() or "gemini-2.0-flash"
    )
    client = genai.Client(api_key=api_key)
    cfg = {"system_instruction": system_instruction}
    try:
        res = await client.aio.models.generate_content(model=model, contents=str(req.text), config=cfg)
        txt = getattr(res, "text", None)
        if txt is None:
            txt = str(res)
        return GemDemoResponse(gem=gem_name, model=model, text=str(txt or "").strip())
    except genai_errors.ClientError as e:
        # Most common failure mode in local dev: quota/rate-limit exhaustion (RESOURCE_EXHAUSTED / 429).
        msg = str(e)
        status_code = int(getattr(e, "status_code", 502) or 502)
        detail: dict[str, Any] = {"gemini_error": msg}

        if status_code == 429 or "resource_exhausted" in msg.lower() or "quota" in msg.lower():
            status_code = 503
            detail["reason"] = "resource_exhausted"

        raise HTTPException(status_code=status_code, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=502, detail={"gem_demo_failed": str(e)})


@app.get("/agents")
def list_agents() -> dict[str, Any]:
    agents = _agents_snapshot()
    out: list[dict[str, Any]] = []
    for agent_id, meta in agents.items():
        out.append(
            {
                "id": agent_id,
                "name": meta.get("name") or agent_id,
                "kind": meta.get("kind") or "",
                "version": meta.get("version") or "",
                "path": meta.get("path") or "",
            }
        )
    return {"ok": True, "agents": out}


@app.post("/tasks/sequential/suggest", response_model=SequentialSuggestResponse)
def tasks_sequential_suggest(req: SequentialSuggestRequest) -> SequentialSuggestResponse:
    task = req.task if isinstance(req.task, dict) else {}
    suggestion = suggest_next_step_from_task(task)

    template: Optional[list[str]] = None
    if req.completed_tasks is not None:
        template = suggest_template_from_completed_tasks(req.completed_tasks)

    return SequentialSuggestResponse(
        ok=True,
        next_step_text=suggestion.next_step_text,
        next_step_index=suggestion.next_step_index,
        template=template,
    )


@app.post("/tasks/sequential/apply", response_model=SequentialApplyResponse)
def tasks_sequential_apply(req: SequentialApplyRequest) -> SequentialApplyResponse:
    updated, changed = mark_checklist_step_done(req.notes, req.step_index)
    return SequentialApplyResponse(ok=True, changed=changed, notes=updated)


@app.post("/tasks/sequential/apply_by_text", response_model=SequentialApplyByTextResponse)
def tasks_sequential_apply_by_text(req: SequentialApplyByTextRequest) -> SequentialApplyByTextResponse:
    updated, changed, matched_idx = mark_checklist_step_done_by_text(req.notes, req.step_text)
    return SequentialApplyByTextResponse(ok=True, changed=changed, notes=updated, matched_step_index=matched_idx)


@app.post("/tasks/sequential/apply_all", response_model=SequentialApplyAllResponse)
def tasks_sequential_apply_all(req: SequentialApplyAllRequest) -> SequentialApplyAllResponse:
    updated, changed, changed_count = mark_all_checklist_steps_done(req.notes)
    return SequentialApplyAllResponse(ok=True, changed=changed, changed_count=changed_count, notes=updated)


@app.post("/tasks/sequential/apply_and_suggest", response_model=SequentialApplyAndSuggestResponse)
def tasks_sequential_apply_and_suggest(req: SequentialApplyAndSuggestRequest) -> SequentialApplyAndSuggestResponse:
    mode = str(req.mode or "suggest")
    notes_in = str(req.notes or "")

    updated_notes = notes_in
    changed = False
    changed_count: Optional[int] = None
    matched_step_index: Optional[int] = None

    if mode == "suggest":
        pass
    elif mode == "index":
        if req.step_index is None:
            raise HTTPException(status_code=400, detail="missing_step_index")
        updated_notes, changed = mark_checklist_step_done(updated_notes, int(req.step_index))
    elif mode == "text":
        step_text = str(req.step_text or "").strip()
        if not step_text:
            raise HTTPException(status_code=400, detail="missing_step_text")
        matches = find_checklist_step_indices_by_text(updated_notes, step_text)
        if len(matches) >= 2:
            hint = req.step_index_hint
            if hint is not None and int(hint) in matches:
                matched_step_index = int(hint)
                updated_notes, changed = mark_checklist_step_done(updated_notes, matched_step_index)
            else:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "ambiguous_step_text": True,
                        "step_text": step_text,
                        "match_indices": matches,
                    },
                )
        else:
            updated_notes, changed, matched_step_index = mark_checklist_step_done_by_text(updated_notes, step_text)
    elif mode == "all":
        updated_notes, changed, cnt = mark_all_checklist_steps_done(updated_notes)
        changed_count = cnt
    else:
        raise HTTPException(status_code=400, detail="invalid_mode")

    suggestion = suggest_next_step_from_task({"notes": updated_notes})
    template: Optional[list[str]] = None
    if req.completed_tasks is not None:
        template = suggest_template_from_completed_tasks(req.completed_tasks)

    return SequentialApplyAndSuggestResponse(
        ok=True,
        mode=mode,
        notes=updated_notes,
        changed=changed,
        changed_count=changed_count,
        matched_step_index=matched_step_index,
        next_step_text=suggestion.next_step_text,
        next_step_index=suggestion.next_step_index,
        template=template,
    )


@app.post("/agents/{agent_id}/status")
def post_agent_status(agent_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    agents = _agents_snapshot()
    agent_id = str(agent_id or "").strip()
    if agent_id not in agents:
        raise HTTPException(status_code=404, detail="agent_not_found")
    _upsert_agent_status(DEFAULT_USER_ID, agent_id, payload)
    return {"ok": True}


async def _resolve_google_tasks_tasklist(*, tasklist_id: Optional[str], tasklist_title: Optional[str]) -> tuple[Optional[str], str]:
    return await google_common.resolve_google_tasks_tasklist(
        tasklist_id=tasklist_id,
        tasklist_title=tasklist_title,
        mcp_tool_map=MCP_TOOL_MAP,
        mcp_tools_call=_mcp_tools_call,
        mcp_text_json=_mcp_text_json,
    )


async def _google_tasks_fetch_task(*, tasklist_id: str, task_id: str) -> Optional[dict[str, Any]]:
    return await google_common.google_tasks_fetch_task(
        tasklist_id=tasklist_id,
        task_id=task_id,
        mcp_tool_map=MCP_TOOL_MAP,
        mcp_tools_call=_mcp_tools_call,
        mcp_text_json=_mcp_text_json,
    )


async def _undo_sheet_append(entry: dict[str, Any]) -> None:
    spreadsheet_id = _system_spreadsheet_id()
    if not spreadsheet_id:
        return
    sheet_name = "undo"

    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

    def _dump(obj: Any) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            return str(obj)

    row = [
        now_iso,
        str(entry.get("event") or ""),
        str(entry.get("scope") or ""),
        str(entry.get("action") or ""),
        str(entry.get("undo_id") or ""),
        str(entry.get("confirmation_id") or ""),
        str(entry.get("tasklist_id") or ""),
        str(entry.get("task_id") or ""),
        str(entry.get("event_id") or ""),
        str(entry.get("status") or ""),
        _dump(entry.get("before")),
        _dump(entry.get("after")),
        _dump(entry.get("result")),
        INSTANCE_ID,
    ]

    try:
        await _mcp_tools_call(
            "google_sheets_values_append",
            {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_name}!A:N",
                "values": [row],
                "value_input_option": "USER_ENTERED",
                "insert_data_option": "INSERT_ROWS",
            },
        )
    except Exception:
        return


def _google_tasks_undo_log(action: str, tasklist_id: Optional[str], task_id: Optional[str], before: Any, after: Any) -> str:
    return db_session.google_tasks_undo_log(SESSION_DB_PATH, action, tasklist_id, task_id, before, after)


def _google_tasks_undo_list(limit: int) -> list[dict[str, Any]]:
    return db_session.google_tasks_undo_list(SESSION_DB_PATH, limit)


def _google_tasks_undo_pop_last(n: int) -> list[dict[str, Any]]:
    return db_session.google_tasks_undo_pop_last(SESSION_DB_PATH, n)


async def _google_calendar_fetch_event(*, event_id: str) -> Optional[dict[str, Any]]:
    return await google_common.google_calendar_fetch_event(
        event_id=event_id,
        mcp_tool_map=MCP_TOOL_MAP,
        mcp_tools_call=_mcp_tools_call,
        mcp_text_json=_mcp_text_json,
    )


def _google_calendar_undo_log(action: str, event_id: Optional[str], before: Any, after: Any) -> str:
    return db_session.google_calendar_undo_log(SESSION_DB_PATH, action, event_id, before, after)


def _google_calendar_undo_list(limit: int) -> list[dict[str, Any]]:
    return db_session.google_calendar_undo_list(SESSION_DB_PATH, limit)


def _google_calendar_undo_pop_last(n: int) -> list[dict[str, Any]]:
    return db_session.google_calendar_undo_pop_last(SESSION_DB_PATH, n)


@app.get("/daily-brief")
async def daily_brief() -> dict[str, Any]:
    agents = _agents_snapshot()
    if "daily-brief" not in agents:
        raise HTTPException(status_code=500, detail="daily_brief_agent_missing")
    return {"ok": True, "brief": await _render_daily_brief(DEFAULT_USER_ID)}


@app.get("/debug/agents")
def debug_agents() -> dict[str, Any]:
    agents = _agents_snapshot()
    triggers = _agent_triggers_snapshot()
    return {
        "ok": True,
        "agents_dir": AGENTS_DIR,
        "agent_count": len(agents),
        "agents": agents,
        "triggers": triggers,
        "continuation_window_seconds": AGENT_CONTINUE_WINDOW_SECONDS,
    }


def _parse_sse_first_message_data(text: str) -> dict[str, Any]:
    return mcp_client.parse_sse_first_message_data(text)


async def _mcp_rpc(method: str, params: dict[str, Any]) -> Any:
    return await mcp_client.mcp_rpc(MCP_BASE_URL, method, params)


async def _aim_mcp_rpc(method: str, params: dict[str, Any]) -> Any:
    return await mcp_client.aim_mcp_rpc(AIM_MCP_BASE_URL, method, params)


async def _mcp_rpc_base(base_url: str, method: str, params: dict[str, Any]) -> Any:
    return await mcp_client.mcp_rpc_base(base_url, method, params)


async def _mcp_tools_list() -> list[dict[str, Any]]:
    base = MCP_BASE_URL
    if MCP_PLAYWRIGHT_BASE_URL:
        # Merge Playwright tools into the main list.
        try:
            main_tools = await mcp_client.mcp_tools_list(MCP_BASE_URL)
        except Exception:
            main_tools = []
        try:
            pw_tools = await mcp_client.mcp_tools_list(MCP_PLAYWRIGHT_BASE_URL)
        except Exception:
            pw_tools = []
        # De-dupe by name.
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for t in (main_tools or []) + (pw_tools or []):
            try:
                n = str((t or {}).get("name") or "").strip()
            except Exception:
                n = ""
            if not n or n in seen:
                continue
            seen.add(n)
            out.append(t)
        return out
    return await mcp_client.mcp_tools_list(base)


async def _resolve_mcp_tool_name(alias: str, *, fallback: str) -> str:
    name = _get_sheets_tool_name(alias)
    if name:
        return name
    try:
        tools = await _mcp_tools_list()
    except Exception:
        tools = []
    want = str(fallback or alias or "").strip()
    if want:
        for t in tools or []:
            if not isinstance(t, dict):
                continue
            n = str(t.get("name") or "").strip()
            if n == want:
                return n
            if want in n:
                return n
    return want or str(alias or "").strip()


def _google_gate_for_tool(tool_name: str) -> tuple[str, bool] | None:
    n = str(tool_name or "").strip().lower()
    if not n:
        return None
    if n.startswith("google_sheets_"):
        return ("google.sheets.enabled", True)
    if n.startswith("google_calendar_"):
        return ("google.calendar.enabled", False)
    if n.startswith("google_tasks_"):
        return ("google.tasks.enabled", False)
    if n.startswith("gmail_"):
        return ("gmail.enabled", False)
    if n.startswith("google_"):
        return ("google.tools.enabled", False)
    return None


async def _mcp_tools_call(name: str, arguments: dict[str, Any]) -> Any:
    gate = _google_gate_for_tool(str(name or ""))
    if gate is not None:
        gate_key, gate_default = gate
        sys_kv = _sys_kv_snapshot()
        default_enabled = gate_default
        if gate_key != "google.tools.enabled":
            default_enabled = _sys_kv_bool(sys_kv, "google.tools.enabled", default=gate_default)
        enabled = _sys_kv_bool(sys_kv, gate_key, default=default_enabled)
        if not enabled:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "google_tools_disabled",
                    "tool": str(name or ""),
                    "required_sys_kv_key": gate_key,
                },
            )
    base = MCP_BASE_URL
    if MCP_PLAYWRIGHT_BASE_URL and (
        str(name or "").startswith("playwright_") or str(name or "").startswith("browser_")
    ):
        base = MCP_PLAYWRIGHT_BASE_URL
    return await mcp_client.mcp_tools_call(base, name, arguments)


async def _aim_mcp_tools_call(name: str, arguments: dict[str, Any]) -> Any:
    return await mcp_client.aim_mcp_tools_call(AIM_MCP_BASE_URL, name, arguments)


async def _web_fetcher_post(path: str, payload: Any) -> Any:
    url = f"{WEB_FETCHER_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.post(url, json=payload)
        if res.status_code >= 400:
            detail: Any
            try:
                detail = res.json()
            except Exception:
                detail = res.text
            raise HTTPException(status_code=res.status_code, detail=detail)
        return res.json()


def _require_confirmation(confirm: bool, action: str, payload: Any) -> None:
    if confirm:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "requires_confirmation": True,
            "action": action,
            "payload": payload,
        },
    )


def _adapt_aim_tool_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name != "aim_memory_store":
        return args

    if isinstance(args.get("entities"), list):
        return args

    name = str(args.get("name") or "").strip() or "Memory"
    description = str(args.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="missing_description")

    entity_type = str(args.get("entityType") or args.get("entity_type") or "note").strip() or "note"
    tz = _get_user_timezone(DEFAULT_USER_ID)
    now = datetime.now(tz=timezone.utc)
    due_at_utc, local_iso = _parse_time_from_text(description, now, tz)
    if due_at_utc is not None:
        entity_type = "reminder"
    observations = args.get("observations")
    if not isinstance(observations, list):
        observations = [description]
    else:
        # Normalize observations to strings
        observations = [str(o) for o in observations if str(o).strip()]
        if not observations:
            observations = [description]

    if due_at_utc is not None and local_iso is not None:
        observations = list(observations)
        observations.append(f"TIMEZONE: {tz.key}")
        observations.append(f"ISO_TIME: {due_at_utc.replace(tzinfo=timezone.utc).isoformat()}")
        observations.append(f"LOCAL_TIME: {local_iso}")

    out: dict[str, Any] = {}
    context = args.get("context")
    if context is not None:
        out["context"] = str(context)
    location = args.get("location")
    if location is not None:
        out["location"] = str(location)

    out["entities"] = [
        {
            "name": name,
            "entityType": entity_type,
            "observations": observations,
        }
    ]
    return out


MCP_TOOL_MAP: dict[str, dict[str, Any]] = {
    "web_fetch": {
        "mcp_name": "fetch_1mcp_fetch",
        "description": "Fetch and extract readable text from a URL via the 1MCP fetch server.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "HTTP(S) URL to fetch."},
                "max_length": {"type": "integer", "description": "Maximum number of characters to return."},
                "start_index": {"type": "integer", "description": "Start content from this character index."},
                "raw": {"type": "boolean", "description": "Return raw content without markdown conversion."},
            },
            "required": ["url"],
        },
        "requires_confirmation": False,
    },
    "google_sheets_ping": {
        "mcp_name": "google-sheets_1mcp_google_sheets_ping",
        "description": "Minimal connectivity test for the Google Sheets MCP server.",
        "parameters": {"type": "object", "properties": {"message": {"type": "string"}}},
        "requires_confirmation": False,
    },
    "google_sheets_auth_status": {
        "mcp_name": "google-sheets_1mcp_google_sheets_auth_status",
        "description": "Check OAuth token status for Google Sheets (single-account).",
        "parameters": {"type": "object", "properties": {"include_raw_tokens": {"type": "boolean"}}},
        "requires_confirmation": False,
    },
    "google_sheets_get_spreadsheet": {
        "mcp_name": "google-sheets_1mcp_google_sheets_get_spreadsheet",
        "description": "Fetch spreadsheet metadata (sheet titles, ids) to help build valid ranges.",
        "parameters": {
            "type": "object",
            "properties": {"spreadsheet_id": {"type": "string"}},
            "required": ["spreadsheet_id"],
        },
        "requires_confirmation": False,
    },
    "google_sheets_values_get": {
        "mcp_name": "google-sheets_1mcp_google_sheets_values_get",
        "description": "Read values from a spreadsheet range (requires OAuth tokens).",
        "parameters": {
            "type": "object",
            "properties": {"spreadsheet_id": {"type": "string"}, "range": {"type": "string"}},
            "required": ["spreadsheet_id", "range"],
        },
        "requires_confirmation": False,
    },
    "google_sheets_values_append": {
        "mcp_name": "google-sheets_1mcp_google_sheets_values_append",
        "description": "Append rows to a spreadsheet range (requires write OAuth scope).",
        "parameters": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string"},
                "range": {"type": "string"},
                "values": {"type": "array", "items": {"type": "array", "items": {}}},
                "value_input_option": {"type": "string"},
                "insert_data_option": {"type": "string"},
            },
            "required": ["spreadsheet_id", "range", "values"],
        },
        "requires_confirmation": True,
    },
    "google_sheets_values_update": {
        "mcp_name": "google-sheets_1mcp_google_sheets_values_update",
        "description": "Update values in a spreadsheet range in-place (requires write OAuth scope).",
        "parameters": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string"},
                "range": {"type": "string"},
                "values": {"type": "array", "items": {"type": "array", "items": {}}},
                "value_input_option": {"type": "string"},
            },
            "required": ["spreadsheet_id", "range", "values"],
        },
        "requires_confirmation": True,
    },
    "sequential_thinking": {
        "mcp_name": "server-sequential-thinking_1mcp_sequentialthinking",
        "description": "Run a step of Sequential Thinking (via 1MCP).",
        "parameters": {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "nextThoughtNeeded": {"type": "boolean"},
                "thoughtNumber": {"type": "integer"},
                "totalThoughts": {"type": "integer"},
                "isRevision": {"type": "boolean"},
                "revisesThought": {"type": "integer"},
                "branchFromThought": {"type": "integer"},
                "branchId": {"type": "string"},
                "needsMoreThoughts": {"type": "boolean"},
            },
            "required": ["thought", "nextThoughtNeeded", "thoughtNumber", "totalThoughts"],
        },
        "requires_confirmation": False,
    },
    "browser_navigate": {
        "mcp_name": "browser_navigate",
        "description": "Navigate the browser to a URL (via 1MCP Playwright). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
        },
        "requires_confirmation": True,
    },
    "browser_snapshot": {
        "mcp_name": "browser_snapshot",
        "description": "Capture an accessibility snapshot of the page (via 1MCP Playwright).",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
            },
        },
        "requires_confirmation": False,
    },
    "browser_click": {
        "mcp_name": "browser_click",
        "description": "Click an element (via 1MCP Playwright). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "element": {"type": "string"},
                "ref": {"type": "string"},
            },
            "required": ["ref"],
        },
        "requires_confirmation": True,
    },
    "browser_type": {
        "mcp_name": "browser_type",
        "description": "Type into an element (via 1MCP Playwright). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "element": {"type": "string"},
                "ref": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["ref", "text"],
        },
        "requires_confirmation": True,
    },
    "browser_wait_for": {
        "mcp_name": "browser_wait_for",
        "description": "Wait for text or time (via 1MCP Playwright).",
        "parameters": {
            "type": "object",
            "properties": {
                "time": {"type": "number"},
                "text": {"type": "string"},
                "textGone": {"type": "string"},
            },
        },
        "requires_confirmation": False,
    },

    "google_tasks_auth_status": {
        "mcp_name": "google-tasks_1mcp_google_tasks_auth_status",
        "description": "Check OAuth token status for Google Tasks (via 1MCP google-tasks).",
        "parameters": {
            "type": "object",
            "properties": {
                "include_raw_tokens": {
                    "type": "boolean",
                    "description": "If true, include raw token JSON in the response (not recommended).",
                }
            },
        },
        "requires_confirmation": False,
    },
    "google_tasks_list_tasklists": {
        "mcp_name": "google-tasks_1mcp_google_tasks_list_tasklists",
        "description": "List Google Tasklists (via 1MCP google-tasks).",
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Max results (1-100)."},
                "page_token": {"type": "string", "description": "Page token from a previous call."},
            },
        },
        "requires_confirmation": False,
    },
    "google_tasks_list_tasks": {
        "mcp_name": "google-tasks_1mcp_google_tasks_list_tasks",
        "description": "List tasks within a tasklist (via 1MCP google-tasks).",
        "parameters": {
            "type": "object",
            "properties": {
                "tasklist_id": {"type": "string", "description": "Tasklist ID. If omitted, uses the first tasklist."},
                "max_results": {"type": "integer", "description": "Max results (1-100)."},
                "page_token": {"type": "string", "description": "Page token from a previous call."},
                "show_completed": {"type": "boolean", "description": "Include completed tasks."},
                "show_hidden": {"type": "boolean", "description": "Include hidden tasks."},
            },
        },
        "requires_confirmation": False,
    },
    "google_tasks_create_task": {
        "mcp_name": "google-tasks_1mcp_google_tasks_create_task",
        "description": "Create a task in Google Tasks (via 1MCP google-tasks). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "tasklist_id": {"type": "string", "description": "Tasklist ID. If omitted, uses the first tasklist."},
                "title": {"type": "string", "description": "Task title."},
                "notes": {"type": "string", "description": "Optional notes."},
                "due": {"type": "string", "description": "Optional RFC3339 due datetime."},
            },
            "required": ["title"],
        },
        "requires_confirmation": True,
    },

    "google_tasks_update_task": {
        "mcp_name": "google-tasks_1mcp_google_tasks_update_task",
        "description": "Update a task in Google Tasks (via 1MCP google-tasks). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "tasklist_id": {"type": "string", "description": "Tasklist ID. If omitted, uses the first tasklist."},
                "task_id": {"type": "string", "description": "Task ID to update."},
                "title": {"type": "string", "description": "Optional new title."},
                "notes": {"type": "string", "description": "Optional new notes."},
                "due": {"type": "string", "description": "Optional RFC3339 due datetime."},
                "status": {"type": "string", "description": "Optional status (e.g. needsAction|completed)."},
            },
            "required": ["task_id"],
        },
        "requires_confirmation": True,
    },
    "google_tasks_complete_task": {
        "mcp_name": "google-tasks_1mcp_google_tasks_complete_task",
        "description": "Mark a task completed in Google Tasks (via 1MCP google-tasks). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "tasklist_id": {"type": "string", "description": "Tasklist ID. If omitted, uses the first tasklist."},
                "task_id": {"type": "string", "description": "Task ID to complete."},
            },
            "required": ["task_id"],
        },
        "requires_confirmation": True,
    },
    "google_tasks_delete_task": {
        "mcp_name": "google-tasks_1mcp_google_tasks_delete_task",
        "description": "Delete a task in Google Tasks (via 1MCP google-tasks). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "tasklist_id": {"type": "string", "description": "Tasklist ID. If omitted, uses the first tasklist."},
                "task_id": {"type": "string", "description": "Task ID to delete."},
            },
            "required": ["task_id"],
        },
        "requires_confirmation": True,
    },

    "google_calendar_auth_status": {
        "mcp_name": "google-calendar_1mcp_google_calendar_auth_status",
        "description": "Check OAuth token status for Google Calendar (via 1MCP google-calendar).",
        "parameters": {
            "type": "object",
            "properties": {
                "include_raw_tokens": {
                    "type": "boolean",
                    "description": "If true, include raw token JSON in the response (not recommended).",
                }
            },
        },
        "requires_confirmation": False,
    },
    "google_calendar_ensure_jarvis_calendar": {
        "mcp_name": "google-calendar_1mcp_google_calendar_ensure_jarvis_calendar",
        "description": "Find or create the dedicated Jarvis Reminders calendar (via 1MCP google-calendar).",
        "parameters": {"type": "object", "properties": {}},
        "requires_confirmation": False,
    },
    "google_calendar_list_events": {
        "mcp_name": "google-calendar_1mcp_google_calendar_list_events",
        "description": "List events in the Jarvis Reminders calendar (via 1MCP google-calendar).",
        "parameters": {
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "RFC3339 inclusive lower bound (optional)."},
                "time_max": {"type": "string", "description": "RFC3339 exclusive upper bound (optional)."},
                "q": {"type": "string", "description": "Free text search (optional)."},
                "max_results": {"type": "integer", "description": "Max results (1-250)."},
                "single_events": {"type": "boolean", "description": "Expand recurring events into instances."},
                "order_by": {"type": "string", "description": "Order by (startTime|updated)."},
            },
        },
        "requires_confirmation": False,
    },
    "google_calendar_create_event": {
        "mcp_name": "google-calendar_1mcp_google_calendar_create_event",
        "description": "Create an event in the Jarvis Reminders calendar (via 1MCP google-calendar). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event summary/title."},
                "description": {"type": "string", "description": "Optional description."},
                "start": {"type": "string", "description": "RFC3339 start datetime (or YYYY-MM-DD for all-day)."},
                "end": {"type": "string", "description": "RFC3339 end datetime (or YYYY-MM-DD for all-day)."},
                "timezone": {"type": "string", "description": "IANA timezone (e.g. Asia/Bangkok)."},
                "reminders_minutes": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Popup reminder offsets in minutes.",
                },
                "rrule": {"type": "string", "description": "Optional RRULE string (without 'RRULE:')."},
            },
            "required": ["summary", "start", "end"],
        },
        "requires_confirmation": True,
    },
    "google_calendar_update_event": {
        "mcp_name": "google-calendar_1mcp_google_calendar_update_event",
        "description": "Update an event in the Jarvis Reminders calendar (via 1MCP google-calendar). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Event ID."},
                "summary": {"type": "string", "description": "Optional new summary/title."},
                "description": {"type": "string", "description": "Optional new description."},
                "start": {"type": "string", "description": "Optional new start (RFC3339 or YYYY-MM-DD)."},
                "end": {"type": "string", "description": "Optional new end (RFC3339 or YYYY-MM-DD)."},
                "timezone": {"type": "string", "description": "IANA timezone (optional)."},
                "reminders_minutes": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional new popup reminder offsets in minutes.",
                },
                "rrule": {"type": "string", "description": "Optional RRULE string (without 'RRULE:')."},
            },
            "required": ["event_id"],
        },
        "requires_confirmation": True,
    },
    "google_calendar_delete_event": {
        "mcp_name": "google-calendar_1mcp_google_calendar_delete_event",
        "description": "Delete an event in the Jarvis Reminders calendar (via 1MCP google-calendar). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Event ID."},
            },
            "required": ["event_id"],
        },
        "requires_confirmation": True,
    },

    "aim_memory_store": {
        "mcp_name": "aim-kg_1mcp_aim_memory_store",
        "description": "Store entities/observations in the AIM knowledge graph memory store.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "Optional memory context. Defaults to master database if not specified.",
                },
                "location": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "description": "Optional storage location override.",
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "The name of the entity"},
                            "entityType": {"type": "string", "description": "The type of the entity"},
                            "observations": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Observations associated with the entity",
                            },
                        },
                        "required": ["name", "entityType", "observations"],
                    },
                },
            },
            "required": ["entities"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_add_facts": {
        "mcp_name": "aim-kg_1mcp_aim_memory_add_facts",
        "description": "Add facts/observations to an existing memory entity.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "Optional memory context."},
                "location": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "description": "Optional storage location override.",
                },
                "observations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entityName": {"type": "string"},
                            "contents": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["entityName", "contents"],
                    },
                },
            },
            "required": ["observations"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_link": {
        "mcp_name": "aim-kg_1mcp_aim_memory_link",
        "description": "Link two memory entities together.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "Optional memory context."},
                "location": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "description": "Optional storage location override.",
                },
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "string"},
                            "to": {"type": "string"},
                            "relationType": {"type": "string"},
                        },
                        "required": ["from", "to", "relationType"],
                    },
                },
            },
            "required": ["relations"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_search": {
        "mcp_name": "aim-kg_1mcp_aim_memory_search",
        "description": "Search memory entities by keyword.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "query": {"type": "string"},
                "format": {"type": "string", "enum": ["json", "pretty"]},
            },
            "required": ["query"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_get": {
        "mcp_name": "aim-kg_1mcp_aim_memory_get",
        "description": "Get memory entities by exact name.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "names": {"type": "array", "items": {"type": "string"}},
                "format": {"type": "string", "enum": ["json", "pretty"]},
            },
            "required": ["names"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_read_all": {
        "mcp_name": "aim-kg_1mcp_aim_memory_read_all",
        "description": "Read all memories from a store.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "format": {"type": "string", "enum": ["json", "pretty"]},
            },
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_list_stores": {
        "mcp_name": "aim-kg_1mcp_aim_memory_list_stores",
        "description": "List available memory stores/databases.",
        "parameters": {"type": "object", "properties": {}},
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_forget": {
        "mcp_name": "aim-kg_1mcp_aim_memory_forget",
        "description": "Forget/delete memories.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "entityNames": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["entityNames"],
        },
        "requires_confirmation": True,
        "mcp_base": "aim",
    },
    "aim_memory_remove_facts": {
        "mcp_name": "aim-kg_1mcp_aim_memory_remove_facts",
        "description": "Remove facts from an existing memory entity.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "deletions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entityName": {"type": "string"},
                            "observations": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["entityName", "observations"],
                    },
                },
            },
            "required": ["deletions"],
        },
        "requires_confirmation": True,
        "mcp_base": "aim",
    },
    "aim_memory_unlink": {
        "mcp_name": "aim-kg_1mcp_aim_memory_unlink",
        "description": "Remove links between memory entities.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "string"},
                            "to": {"type": "string"},
                            "relationType": {"type": "string"},
                        },
                        "required": ["from", "to", "relationType"],
                    },
                },
            },
            "required": ["relations"],
        },
        "requires_confirmation": True,
        "mcp_base": "aim",
    },
}


app.include_router(
    _create_google_tasks_router(
        mcp_tool_map=MCP_TOOL_MAP,
        mcp_tools_call=lambda name, arguments: _mcp_tools_call(name, arguments),
        mcp_text_json=lambda result: _mcp_text_json(result),
        require_confirmation=_require_confirmation,
        resolve_tasklist=lambda tasklist_id, tasklist_title: _resolve_google_tasks_tasklist(
            tasklist_id=tasklist_id, tasklist_title=tasklist_title
        ),
        fetch_task=lambda tasklist_id, task_id: _google_tasks_fetch_task(tasklist_id=tasklist_id, task_id=task_id),
        undo_log=_google_tasks_undo_log,
        undo_sheet_append=lambda entry: _undo_sheet_append(entry),
        undo_list=_google_tasks_undo_list,
        undo_pop_last=_google_tasks_undo_pop_last,
        parse_checklist_steps=parse_checklist_steps,
        next_actionable_step=next_actionable_step,
        suggest_template_from_completed_tasks=suggest_template_from_completed_tasks,
    )
)


app.include_router(
    _create_google_calendar_router(
        mcp_tool_map=MCP_TOOL_MAP,
        mcp_tools_call=lambda name, arguments: _mcp_tools_call(name, arguments),
        mcp_text_json=lambda result: _mcp_text_json(result),
        require_confirmation=_require_confirmation,
        undo_sheet_append=lambda entry: _undo_sheet_append(entry),
        undo_list=_google_calendar_undo_list,
        undo_pop_last=_google_calendar_undo_pop_last,
    )
)


def _mcp_tool_declarations() -> list[dict[str, Any]]:
    sys_kv = _sys_kv_snapshot()
    decls: list[dict[str, Any]] = []
    for name, meta in MCP_TOOL_MAP.items():
        if str(meta.get("mcp_base") or "").strip().lower() == "aim" and not AIM_MCP_BASE_URL:
            continue
        decls.append(
            {
                "name": name,
                "description": str(meta.get("description") or ""),
                "parameters": meta.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    decls.append(
        {
            "name": "time_now",
            "description": "Return the authoritative current server time (UTC + local timezone).",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {"type": "string", "description": "IANA timezone name (e.g. Asia/Bangkok)."},
                },
            },
        }
    )

    decls.append(
        {
            "name": "session_last_get",
            "description": "Get the last created/modified item for this voice session (task or calendar_event).",
            "parameters": {
                "type": "object",
                "properties": {
                    "slot": {"type": "string", "enum": ["last_created", "last_modified"]},
                },
                "required": ["slot"],
            },
        }
    )

    if feature_enabled("memory", sys_kv=sys_kv, default=True):
        decls.append(
            {
                "name": "memory_add",
                "description": "Create or update an authoritative memory item in the memory sheet (hybrid mode).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Stable memory key (optional; autogenerated if omitted)."},
                        "value": {"type": "string", "description": "Memory value/body."},
                        "scope": {"type": "string", "description": "session|user|global (default global)."},
                        "priority": {"type": "integer", "description": "Higher wins when multiple scopes overlap (default 0)."},
                    },
                    "required": ["value"],
                },
            }
        )

    if feature_enabled("memo", sys_kv=sys_kv, default=True):
        decls.append(
            {
                "name": "memo_add",
                "description": "Append a memo entry to the memo sheet (Google Sheets).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memo": {"type": "string", "description": "Memo text/body."},
                        "group": {"type": "string", "description": "Optional group label."},
                        "subject": {"type": "string", "description": "Optional subject label."},
                        "status": {"type": "string", "description": "Optional status (default new)."},
                        "v": {"type": "string", "description": "Optional version tag."},
                        "result": {"type": "string", "description": "Optional result/notes."},
                        "active": {"type": "boolean", "description": "Optional active flag (default true)."},
                    },
                    "required": ["memo"],
                },
            }
        )

        decls.append(
            {
                "name": "memo_get",
                "description": "Get a memo by stable numeric id (sheet-backed).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "Memo id."},
                    },
                    "required": ["id"],
                },
            }
        )

        decls.append(
            {
                "name": "memo_list",
                "description": "List recent memos (sheet-backed).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Max items (default 20)."},
                    },
                },
            }
        )

    if feature_enabled("memory", sys_kv=sys_kv, default=True):
        decls.append(
            {
                "name": "memory_search",
                "description": "Search authoritative memory items (sheet-backed).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            }
        )

        decls.append(
            {
                "name": "memory_list",
                "description": "List loaded memory keys (sheet-backed).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                    },
                },
            }
        )

    decls.append({"name": "pending_list", "description": "List queued pending actions waiting for confirmation."})
    decls.append(
        {
            "name": "pending_confirm",
            "description": "Confirm and execute a queued pending action.",
            "parameters": {
                "type": "object",
                "properties": {"confirmation_id": {"type": "string"}},
                "required": ["confirmation_id"],
            },
        }
    )
    decls.append(
        {
            "name": "pending_cancel",
            "description": "Cancel a queued pending action.",
            "parameters": {
                "type": "object",
                "properties": {"confirmation_id": {"type": "string"}},
                "required": ["confirmation_id"],
            },
        }
    )

    return decls


async def _handle_mcp_tool_call(session_id: Optional[str], tool_name: str, args: dict[str, Any]) -> Any:
    deps: dict[str, Any] = {
        "HTTPException": HTTPException,
        "ZoneInfo": ZoneInfo,
        "datetime": datetime,
        "timezone": timezone,
        "time": time,
        "logger": logger,
        "DEFAULT_USER_ID": DEFAULT_USER_ID,
        "AGENT_CONTINUE_WINDOW_SECONDS": AGENT_CONTINUE_WINDOW_SECONDS,
        "SESSION_WS": _SESSION_WS,
        "MCP_TOOL_MAP": MCP_TOOL_MAP,
        "feature_enabled": feature_enabled,
        "sys_kv_bool": _sys_kv_bool,
        "safe_int": _safe_int,
        "get_user_timezone": _get_user_timezone,
        "get_session_last_item": _get_session_last_item,
        "set_session_last_item": _set_session_last_item,
        "memory_sheet_upsert": _memory_sheet_upsert,
        "load_ws_sheet_memory": _load_ws_sheet_memory,
        "memo_sheet_cfg_from_sys_kv": _memo_sheet_cfg_from_sys_kv,
        "sheet_name_to_a1": _sheet_name_to_a1,
        "sheet_get_header_row": _sheet_get_header_row,
        "idx_from_header": _idx_from_header,
        "memo_ensure_header": _memo_ensure_header,
        "pick_sheets_tool_name": _pick_sheets_tool_name,
        "mcp_tools_call": _mcp_tools_call,
        "mcp_text_json": _mcp_text_json,
        "memo_prompt_cfg": _memo_prompt_cfg,
        "memo_needs_enrich": _memo_needs_enrich,
        "memo_enrich_prompt": _memo_enrich_prompt,
        "list_pending_writes": _list_pending_writes,
        "create_pending_write": _create_pending_write,
        "pop_pending_write": _pop_pending_write,
        "cancel_pending_write": _cancel_pending_write,
        "adapt_aim_tool_args": _adapt_aim_tool_args,
        "aim_mcp_tools_call": _aim_mcp_tools_call,
        "parse_time_from_text": _parse_time_from_text,
        "google_calendar_create_reminder_event": _google_calendar_create_reminder_event,
        "google_calendar_fetch_event": _google_calendar_fetch_event,
        "google_tasks_fetch_task": _google_tasks_fetch_task,
        "undo_sheet_append": _undo_sheet_append,
        "google_calendar_undo_log": _google_calendar_undo_log,
        "google_tasks_undo_log": _google_tasks_undo_log,
        "adapt_playwright_tool_args": _adapt_playwright_tool_args,
    }
    return await tools_router.handle_mcp_tool_call(session_id, tool_name, args, deps=deps)


def _fc_args(fc: Any) -> dict[str, Any]:
    args = getattr(fc, "args", None)
    if isinstance(args, dict):
        return args
    args = getattr(fc, "arguments", None)
    if isinstance(args, dict):
        return args
    # Fallback: try model_dump if present
    try:
        dumped = fc.model_dump()  # type: ignore[attr-defined]
        for k in ("args", "arguments"):
            if isinstance(dumped.get(k), dict):
                return dumped[k]
    except Exception:
        pass
    return {}


async def _ws_to_gemini_loop(ws: WebSocket, session: Any) -> None:
    audio_frames = 0
    gemini_available = True
    pending_first = getattr(ws.state, "prefetched_client_msgs", None)
    if not isinstance(pending_first, list):
        pending_first = []
    while True:
        if pending_first:
            msg = pending_first.pop(0)
        else:
            msg = await ws.receive_json()
        trace_id = _ws_capture_trace_id(ws, msg)
        try:
            await _ws_record(ws, "in", msg)
        except Exception:
            pass
        msg_type = msg.get("type")

        # Deterministic backend tools (never forwarded to Gemini)
        if isinstance(msg, dict):
            handled_local = await _handle_local_tools_message(ws, msg, trace_id=trace_id)
            if handled_local:
                continue

        if msg_type == "cars_ingest_image":
            await _handle_cars_ingest_image(ws, msg if isinstance(msg, dict) else {})
            await _ws_voice_job_done(ws, trace_id2)
            continue

        if msg_type == "audio":
            if not gemini_available:
                continue
            data_b64 = str(msg.get("data") or "")
            mime_type = str(msg.get("mimeType") or "audio/pcm;rate=16000")
            if not data_b64:
                continue
            try:
                audio_bytes = base64.b64decode(data_b64)
                await session.send_realtime_input(audio=types.Blob(data=audio_bytes, mime_type=mime_type))
            except Exception as e:
                gemini_available = False
                logger.warning("gemini_send_audio_failed error=%s", str(e))
                try:
                    await _ws_send_json(ws, {"type": "error", "message": "gemini_unavailable", "detail": str(e)}, trace_id=trace_id)
                except Exception:
                    pass
                continue
            audio_frames += 1
            if audio_frames % 50 == 0:
                logger.info("forwarded_audio_frames=%s", audio_frames)
            continue

        if msg_type == "text":
            text = str(msg.get("text") or "")
            if not text:
                continue
            logger.info("ws_in_text trace_id=%s len=%s head=%s", trace_id, len(text), text[:120])

            # Frontend reconnect-resume support: the UI may send a synthetic RESUME_CONTEXT
            # message after reconnect to rehydrate conversational context.
            # Do NOT forward this to Gemini as a normal user message (it can trigger a fresh greeting).
            # Instead, store it and prepend it once to the next real user message.
            try:
                head = str(text).lstrip()
                if head.startswith("RESUME_CONTEXT (recent dialog"):
                    try:
                        ws.state.resume_context_text = str(text)
                        ws.state.resume_context_pending = True
                    except Exception:
                        pass
                    continue
            except Exception:
                pass

            # Intercept local slash commands (typed) so they never go to Gemini.
            # This avoids confusing model replies like "task not found" for /sys commands.
            try:
                s0 = str(text or "").strip()
                # Normalize common copy/paste oddities.
                s = re.sub(r"[\u00A0\u200B-\u200D\uFEFF]+", "", s0)
                s = " ".join(s.split())
            except Exception:
                s = str(text or "").strip()

            if s.startswith("/"):
                m = re.match(r"^/(?:sys|system)\s+(set|dry)\s+(.+)$", s, flags=re.IGNORECASE)
                if m:
                    dry_run = str(m.group(1) or "").strip().lower() == "dry"
                    rest = str(m.group(2) or "").strip()
                    eq = rest.find("=")
                    if eq > 0:
                        key = rest[:eq].strip()
                        value = rest[eq + 1 :].strip()
                        # Route via deterministic local tools.
                        await _handle_local_tools_message(
                            ws,
                            {
                                "type": "system",
                                "action": "sys_kv_set",
                                "key": key,
                                "value": value,
                                "dry_run": dry_run,
                                "trace_id": trace_id2,
                            },
                            trace_id=trace_id2,
                        )
                        continue
                    await _ws_send_json(
                        ws,
                        {
                            "type": "error",
                            "kind": "invalid_sys_command",
                            "message": "invalid_sys_command",
                            "detail": "Expected /sys set <key>=<value>",
                            "instance_id": INSTANCE_ID,
                        },
                        trace_id=trace_id2,
                    )
                    continue

                # Unknown slash command: handle locally (do not forward to Gemini).
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "unknown_command",
                        "message": "unknown_command",
                        "detail": s,
                        "instance_id": INSTANCE_ID,
                    },
                    trace_id=trace_id2,
                )
                continue

            handled = await _dispatch_sub_agents(ws, text)
            logger.info("ws_in_text_dispatched handled=%s active_agent_id=%s", handled, getattr(ws.state, "active_agent_id", None))
            if handled:
                continue
            if not gemini_available:
                try:
                    await _ws_send_json(ws, {"type": "error", "message": "gemini_unavailable"}, trace_id=trace_id)
                except Exception:
                    pass
                continue
            try:
                resume_pending = False
                resume_text = ""
                try:
                    resume_pending = bool(getattr(ws.state, "resume_context_pending", False))
                    resume_text = str(getattr(ws.state, "resume_context_text", "") or "").strip()
                except Exception:
                    resume_pending = False
                    resume_text = ""

                if resume_pending and resume_text:
                    combined = (resume_text + "\n\n" + "USER_MESSAGE:\n" + str(text)).strip()
                    try:
                        ws.state.resume_context_pending = False
                    except Exception:
                        pass
                    await session.send_client_content(turns={"parts": [{"text": combined}]}, turn_complete=True)
                else:
                    await session.send_client_content(turns={"parts": [{"text": text}]}, turn_complete=True)
            except Exception as e:
                gemini_available = False
                logger.warning("gemini_send_text_failed error=%s", str(e))
                try:
                    await _ws_send_json(ws, {"type": "error", "message": "gemini_unavailable", "detail": str(e)}, trace_id=trace_id)
                except Exception:
                    pass
            continue

        if msg_type == "audio_stream_end":
            if not gemini_available:
                continue
            try:
                await session.send_realtime_input(audio_stream_end=True)
            except Exception as e:
                gemini_available = False
                logger.warning("gemini_send_audio_end_failed error=%s", str(e))
                try:
                    await _ws_send_json(ws, {"type": "error", "message": "gemini_unavailable", "detail": str(e)}, trace_id=trace_id)
                except Exception:
                    pass
            continue

        if msg_type == "close":
            return


async def _live_say(ws: WebSocket, text: str) -> None:
    s = str(text or "").strip()
    if not s:
        return
    session = getattr(ws.state, "gemini_live_session", None)
    if session is None:
        return
    try:
        await session.send_client_content(turns={"parts": [{"text": s}]}, turn_complete=True)
    except Exception:
        return


async def _ws_local_only_loop(ws: WebSocket) -> None:
    while True:
        msg = await ws.receive_json()
        trace_id = _ws_capture_trace_id(ws, msg)
        trace_id2 = _ws_ensure_trace_id(ws, trace_id)
        try:
            await _ws_record(ws, "in", msg)
        except Exception:
            pass
        msg_type = msg.get("type")

        # Deterministic backend tools (works even in local-only mode)
        if isinstance(msg, dict):
            handled_local = await _handle_local_tools_message(ws, msg, trace_id=trace_id2)
            if handled_local:
                continue

        if msg_type == "cars_ingest_image":
            await _handle_cars_ingest_image(ws, msg if isinstance(msg, dict) else {})
            continue

        if msg_type == "audio":
            # Local-only mode: ignore audio frames (no Gemini Live session).
            continue

        if msg_type == "audio_stream_end":
            continue

        if msg_type == "text":
            text = str(msg.get("text") or "")
            if not text:
                continue
            logger.info("ws_in_text_local_only trace_id=%s len=%s head=%s", trace_id, len(text), text[:120])
            handled = await _dispatch_sub_agents(ws, text)
            logger.info(
                "ws_in_text_local_only_dispatched handled=%s active_agent_id=%s",
                handled,
                getattr(ws.state, "active_agent_id", None),
            )
            if handled:
                continue
            await _ws_send_json(ws, {"type": "error", "message": "gemini_unavailable"}, trace_id=trace_id)
            continue

        if msg_type == "close":
            return


def _extract_audio_b64(server_msg: Any) -> Optional[str]:
    try:
        server_content = getattr(server_msg, "server_content", None)
        if not server_content:
            return None
        model_turn = getattr(server_content, "model_turn", None)
        if not model_turn:
            return None
        parts = getattr(model_turn, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if not inline_data:
                continue
            data = getattr(inline_data, "data", None)
            if not data:
                continue
            if isinstance(data, (bytes, bytearray)):
                return base64.b64encode(bytes(data)).decode("ascii")
            if isinstance(data, str):
                return data
            try:
                as_bytes = bytes(data)
                return base64.b64encode(as_bytes).decode("ascii")
            except Exception:
                return str(data)
    except Exception:
        return None
    return None


async def _gemini_to_ws_loop(ws: WebSocket, session: Any) -> None:
    audio_out_frames = 0
    logged_shape = False
    logged_server_content_shape = False
    while True:
        async for server_msg in session.receive():
            tool_call = getattr(server_msg, "tool_call", None)
            if tool_call is not None:
                function_calls = getattr(tool_call, "function_calls", None) or []
                logger.info("gemini_tool_call count=%s", len(function_calls))
                function_responses: list[Any] = []
                for fc in function_calls:
                    fc_id = getattr(fc, "id", None)
                    fc_name = str(getattr(fc, "name", "") or "")
                    fc_args = _fc_args(fc)
                    logger.info("gemini_tool_call_item name=%s args_keys=%s", fc_name, list(fc_args.keys()))
                    try:
                        session_id = getattr(ws.state, "session_id", None)
                        try:
                            await _ws_progress(
                                ws,
                                f"Running {fc_name} ({len(function_responses) + 1}/{len(function_calls)})",
                                phase="start",
                                tool_name=fc_name,
                                step=len(function_responses) + 1,
                                total=len(function_calls),
                            )
                        except Exception:
                            pass
                        if fc_name in MCP_TOOL_MAP or fc_name in (
                            "time_now",
                            "session_last_get",
                            "pending_list",
                            "pending_confirm",
                            "pending_cancel",
                            "memo_add",
                            "memo_get",
                            "memo_list",
                            "memory_add",
                            "memory_search",
                            "memory_list",
                        ):
                            result = await _handle_mcp_tool_call(session_id, fc_name, fc_args)
                        else:
                            raise HTTPException(status_code=400, detail={"unknown_tool": fc_name})
                        # Tool handlers may return structured failures like {"ok": False, ...}.
                        # Preserve those failures (don't wrap them as ok:true) so Gemini and the UI
                        # can surface the real error detail.
                        if isinstance(result, dict) and result.get("ok") is False:
                            err_payload = {
                                "ok": False,
                                "error": result.get("error") or "tool_failed",
                                "detail": result,
                            }
                            function_responses.append(
                                types.FunctionResponse(
                                    id=fc_id,
                                    name=fc_name,
                                    response=err_payload,
                                )
                            )
                            try:
                                await _ws_progress(
                                    ws,
                                    f"Failed {fc_name}: {result.get('detail') or result.get('error') or 'tool_failed'}",
                                    phase="error",
                                    tool_name=fc_name,
                                    step=len(function_responses),
                                    total=len(function_calls),
                                )
                            except Exception:
                                pass
                        else:
                            function_responses.append(
                                types.FunctionResponse(
                                    id=fc_id,
                                    name=fc_name,
                                    response={"ok": True, "result": result},
                                )
                            )
                            try:
                                await _ws_progress(
                                    ws,
                                    f"Done {fc_name}",
                                    phase="done",
                                    tool_name=fc_name,
                                    step=len(function_responses),
                                    total=len(function_calls),
                                )
                            except Exception:
                                pass
                    except HTTPException as e:
                        logger.info("gemini_tool_call_error name=%s status_code=%s", fc_name, e.status_code)
                        function_responses.append(
                            types.FunctionResponse(
                                id=fc_id,
                                name=fc_name,
                                response={"ok": False, "error": e.detail, "status_code": e.status_code},
                            )
                        )
                        try:
                            await _ws_progress(
                                ws,
                                f"Failed {fc_name}",
                                phase="error",
                                tool_name=fc_name,
                                step=len(function_responses) + 1,
                                total=len(function_calls),
                            )
                        except Exception:
                            pass
                    except Exception as e:
                        logger.info("gemini_tool_call_exception name=%s error=%s", fc_name, str(e))
                        function_responses.append(
                            types.FunctionResponse(
                                id=fc_id,
                                name=fc_name,
                                response={"ok": False, "error": str(e)},
                            )
                        )

                        try:
                            await _ws_progress(
                                ws,
                                f"Failed {fc_name}",
                                phase="error",
                                tool_name=fc_name,
                                step=len(function_responses) + 1,
                                total=len(function_calls),
                            )
                        except Exception:
                            pass

                if function_responses:
                    await session.send_tool_response(function_responses=function_responses)
                continue

            transcription = getattr(server_msg, "transcription", None)
            if transcription is not None:
                text = getattr(transcription, "text", None)
                if text:
                    # Some Gemini Live server messages only provide a generic transcription object.
                    # Treat it as an input transcript for voice UX fallback triggers.
                    try:
                        ws.state.user_lang = "th" if _text_is_thai(str(text)) else "en"
                    except Exception:
                        pass
                    try:
                        handled = await _dispatch_sub_agents(ws, str(text))
                        if handled:
                            logger.info("live_transcription_dispatched handled=true")
                            continue
                    except Exception as e:
                        logger.info("live_transcription_dispatch_failed error=%s", str(e))
                    await ws.send_json({"type": "transcript", "text": str(text), "source": "input"})
                    continue
            elif not logged_shape:
                # One-time debug to understand server message fields.
                try:
                    keys = list(getattr(server_msg, "__dict__", {}).keys())
                    logger.info("live_msg_fields=%s", keys)
                except Exception:
                    logger.info("live_msg_type=%s", type(server_msg))
                logged_shape = True

            server_content = getattr(server_msg, "server_content", None)
            if server_content is not None:
                if not logged_server_content_shape:
                    try:
                        keys = list(getattr(server_content, "__dict__", {}).keys())
                        logger.info("live_server_content_fields=%s", keys)
                    except Exception:
                        logger.info("live_server_content_type=%s", type(server_content))
                    logged_server_content_shape = True

                input_tr = getattr(server_content, "input_transcription", None)
                if input_tr is not None:
                    text = getattr(input_tr, "text", None)
                    if text:
                        logger.info("live_input_transcript text=%s", str(text)[:300])
                        try:
                            ws.state.user_lang = "th" if _text_is_thai(str(text)) else "en"
                        except Exception:
                            pass
                        # Voice UX: allow local sub-agents (e.g., reminders) to trigger from
                        # input transcription even if Gemini doesn't emit a tool_call.
                        try:
                            handled = await _dispatch_sub_agents(ws, str(text))
                            if handled:
                                logger.info("live_input_transcript_dispatched handled=true")
                                continue
                        except Exception as e:
                            logger.info("input_transcript_dispatch_failed error=%s", str(e))
                        await ws.send_json({"type": "transcript", "text": str(text), "source": "input"})
                        continue

                output_tr = getattr(server_content, "output_transcription", None)
                if output_tr is not None:
                    text = getattr(output_tr, "text", None)
                    if text:
                        await ws.send_json({"type": "transcript", "text": str(text), "source": "output"})
                        continue

                model_turn = getattr(server_content, "model_turn", None)
                if model_turn is not None:
                    parts = getattr(model_turn, "parts", None) or []
                    for part in parts:
                        part_text = getattr(part, "text", None)
                        if part_text:
                            await ws.send_json({"type": "text", "text": str(part_text)})
                            break

            audio_b64 = _extract_audio_b64(server_msg)
            if audio_b64:
                await _ws_send_json(ws, {"type": "audio", "data": audio_b64, "sampleRate": 24000})
                audio_out_frames += 1
                if audio_out_frames % 10 == 0:
                    logger.info("sent_audio_frames=%s", audio_out_frames)
                continue

            # Send text if present (useful for debugging / future UI)
            text = getattr(server_msg, "text", None)
            if text:
                await _ws_send_json(ws, {"type": "text", "text": str(text)})


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await ws.accept()

    user_id = DEFAULT_USER_ID
    _ws_by_user.setdefault(user_id, set()).add(ws)

    # Sticky session support: the frontend provides ?session_id=... so we can persist
    # per-session state across reconnects.
    session_id = str(ws.query_params.get("session_id") or "").strip() or None
    ws.state.session_id = session_id

    if session_id:
        try:
            _SESSION_WS[str(session_id)] = ws
        except Exception:
            pass

    # Optional client tagging for multi-device debugging.
    try:
        ws.state.client_id = str(ws.query_params.get("client_id") or "").strip() or None
        ws.state.client_tag = str(ws.query_params.get("client_tag") or "").strip() or None
    except Exception:
        pass

    connected_sent = False
    ws.state.notes_board_task = None
    try:
        try:
            ws.state.user_lang = _lang_from_ws(ws)
        except Exception:
            pass

        # Fail-closed: system sheet is authoritative configuration.
        # If it cannot be loaded, do not proceed with a live session.
        try:
            sys_kv = await _load_ws_system_kv(ws)
        except Exception as e:
            detail = {
                "error": str(e),
                "spreadsheet_id_env": "CHABA_SYSTEM_SPREADSHEET_ID",
                "sheet_name_env": "CHABA_SYSTEM_SHEET_NAME",
                "mcp_base_url": str(os.getenv("MCP_BASE_URL") or "http://mcp-bundle:3050").strip() or "http://mcp-bundle:3050",
            }
            try:
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "system_sheet_unavailable",
                        "message": "system_sheet_unavailable",
                        "detail": detail,
                        "instance_id": INSTANCE_ID,
                    },
                )
            except Exception:
                pass
            try:
                await ws.close(code=1011)
            except Exception:
                pass
            return

        try:
            err = _validate_system_sheets_plan(sys_kv)
        except Exception as e:
            err = f"system_sheets_validation_failed: {str(e)}"
        if err:
            detail = {
                "error": str(err),
                "hint": "system.sheets supports only memory/knowledge. Configure notes separately via notes_ss + notes.sheet_name/notes_sh.",
                "system_sheets": str((sys_kv or {}).get("system.sheets") or "").strip(),
            }
            try:
                await _ws_send_json(
                    ws,
                    {
                        "type": "error",
                        "kind": "system_sheet_invalid",
                        "message": "system_sheet_invalid",
                        "detail": detail,
                        "instance_id": INSTANCE_ID,
                    },
                )
            except Exception:
                pass
            try:
                await ws.close(code=1011)
            except Exception:
                pass
            return

        tz = _get_user_timezone(DEFAULT_USER_ID)
        now_local = datetime.now(tz=timezone.utc).astimezone(tz)
        lang = str(getattr(ws.state, "user_lang", "") or "").strip() or _lang_from_ws(ws)
        try:
            await _ws_send_json(ws, {"type": "text", "text": _short_datetime_line(lang, now_local), "instance_id": INSTANCE_ID})
        except Exception:
            pass

        cached = _get_cached_sheet_memory()
        if isinstance(cached, dict):
            _apply_cached_sheet_memory_to_ws(ws, cached)

        cached_k = _get_cached_sheet_knowledge()
        if isinstance(cached_k, dict):
            _apply_cached_sheet_knowledge_to_ws(ws, cached_k)

        # Cache-first mode: do not auto-load sheets here. Use `Reload System`.
        # Emit status based on cache only, but suppress duplicates on rapid reconnects.
        should_emit_sheet_status = True
        try:
            sid = str(getattr(ws.state, "session_id", None) or "").strip()
            cid = str(getattr(ws.state, "client_id", None) or "").strip()
            key = sid or cid or str(id(ws))
            now_ts = time.time()
            async with _initial_sheet_status_lock:
                last = float(_initial_sheet_status_last_sent.get(key) or 0.0)
                if last and (now_ts - last) < INITIAL_SHEET_STATUS_DEDUPE_SECONDS:
                    should_emit_sheet_status = False
                else:
                    _initial_sheet_status_last_sent[key] = now_ts
        except Exception:
            should_emit_sheet_status = True

        if should_emit_sheet_status:
            try:
                mem_line = _memory_load_status_line(ws, lang)
                await _ws_send_json(ws, {"type": "text", "text": mem_line, "instance_id": INSTANCE_ID})
                try:
                    await _maybe_capture_to_memory(ws, key="runtime.connect.memory_load_status", value=mem_line, source="connect")
                except Exception:
                    pass
            except Exception:
                pass

            try:
                prewarm_line = _startup_prewarm_status_line(lang)
                await _ws_send_json(ws, {"type": "text", "text": prewarm_line, "instance_id": INSTANCE_ID})
                try:
                    await _maybe_capture_to_memory(ws, key="runtime.connect.startup_prewarm_status", value=prewarm_line, source="connect")
                except Exception:
                    pass
            except Exception:
                pass
        api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
        if not api_key:
            await _ws_send_json(
                ws,
                {
                    "type": "error",
                    "kind": "missing_api_key",
                    "message": "missing_api_key",
                    "detail": "Missing required env var: API_KEY (or GEMINI_API_KEY)",
                }
            )
            await _ws_local_only_loop(ws)
            return
        client = genai.Client(api_key=api_key)

        class _GeminiLiveModelNotFound(Exception):
            def __init__(self, detail: str) -> None:
                super().__init__(detail)
                self.detail = detail

        class _GeminiLiveSessionFailed(Exception):
            def __init__(self, detail: str) -> None:
                super().__init__(detail)
                self.detail = detail

        def _classify_gemini_live_error(err: Exception, model: str) -> dict[str, Any]:
            msg = str(err)
            status_code = getattr(err, "status_code", None)
            if status_code == 1008 or "requested entity was not found" in msg.lower():
                return {
                    "kind": "gemini_model_not_found",
                    "message": "gemini_live_model_not_found",
                    "model": model,
                    "hint": "Set GEMINI_LIVE_MODEL to a model your API key can access.",
                    "detail": msg,
                }
            return {
                "kind": "gemini_session_failed",
                "message": "gemini_session_failed",
                "model": model,
                "detail": msg,
            }

        tz = _get_user_timezone(DEFAULT_USER_ID)
        now_utc = datetime.now(tz=timezone.utc)
        now_local = now_utc.astimezone(tz)
        gem_q = str(ws.query_params.get("gem") or "").strip() or None

        sys_kv = getattr(ws.state, "sys_kv", None)
        gem_extra, _gem_model = await _resolve_gem_instruction_and_model(gem_name=gem_q, sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
        system_instruction = (
            "You are Jarvis. Respond to the user with ONLY the final answer. "
            "Do NOT reveal internal reasoning, planning, debugging, tool selection, or step-by-step thoughts. "
            "Do NOT output work logs or messages like 'I am now', 'My next step', 'Filtering', 'Calculating'. "
            "Be concise. Match the user's language (Thai stays Thai). "
            "When answering questions about the current time/date, speak casually and do NOT mention the timezone unless the user asks. "
            "If you are unsure, ask a short clarifying question. "
            "\n\n"
            "TIME_CONTEXT (internal; do NOT repeat verbatim to the user)\n"
            f"TIMEZONE: {tz.key}\n"
            f"NOW_UTC: {now_utc.replace(tzinfo=timezone.utc).isoformat()}\n"
            f"NOW_LOCAL: {now_local.isoformat()}\n"
            "Use this as the reference for all relative time calculations."
        )

        notes_policy = _notes_policy_text_from_sys_kv(sys_kv)
        if notes_policy:
            system_instruction = system_instruction + "\n\nNOTES_POLICY (internal)\n" + notes_policy

        # Inject memory sheet context (best-effort). Keep compact to avoid token blowups.
        mem_ctx = str(getattr(ws.state, "memory_context_text", "") or "").strip()
        if mem_ctx:
            system_instruction = (
                system_instruction
                + "\n\n"
                + "SHEET_MEMORY_CONTEXT (internal; do NOT repeat verbatim to the user)\n"
                + mem_ctx
            )

        know_ctx = str(getattr(ws.state, "knowledge_context_text", "") or "").strip()
        if know_ctx:
            system_instruction = (
                system_instruction
                + "\n\n"
                + "SHEET_KNOWLEDGE_CONTEXT (internal; do NOT repeat verbatim to the user)\n"
                + know_ctx
            )

        mem_info = str(getattr(ws.state, "memory_info", "") or "").strip()
        know_info = str(getattr(ws.state, "knowledge_info", "") or "").strip()
        mem_inst = str(getattr(ws.state, "memory_instruction", "") or "").strip()
        know_inst = str(getattr(ws.state, "knowledge_instruction", "") or "").strip()
        if mem_info:
            system_instruction = system_instruction + "\n\n" + "MEMORY_INFO (from system sheet; internal)\n" + mem_info
        if know_info:
            system_instruction = system_instruction + "\n\n" + "KNOWLEDGE_INFO (from system sheet; internal)\n" + know_info
        if mem_inst:
            system_instruction = system_instruction + "\n\n" + "MEMORY_INSTRUCTION (from system sheet; internal)\n" + mem_inst
        if know_inst:
            system_instruction = system_instruction + "\n\n" + "KNOWLEDGE_INSTRUCTION (from system sheet; internal)\n" + know_inst

        extra_sys = str(getattr(ws.state, "system_instruction_extra", "") or "").strip()
        if extra_sys:
            system_instruction = (
                system_instruction
                + "\n\n"
                + "SYSTEM_INSTRUCTION (from system sheet; internal)\n"
                + extra_sys
            )

        try:
            mem_items = getattr(ws.state, "memory_items", None)
            know_items = getattr(ws.state, "knowledge_items", None)
            mem_n = len(mem_items) if isinstance(mem_items, list) else 0
            know_n = len(know_items) if isinstance(know_items, list) else 0
        except Exception:
            mem_n = 0
            know_n = 0
        system_instruction = (
            system_instruction
            + "\n\n"
            + "RUNTIME_COUNTS (internal)\n"
            + f"memory_count={mem_n} knowledge_count={know_n}"
        )

        if gem_extra:
            system_instruction = system_instruction + "\n\n" + gem_extra

        try:
            cached_gems = _get_cached_sheet_gems()
            loaded_at = int((cached_gems or {}).get("loaded_at") or 0) if isinstance(cached_gems, dict) else 0
        except Exception:
            loaded_at = 0
        ttl_g = _gems_cache_ttl_seconds()
        should_refresh_gems = not isinstance(_get_cached_sheet_gems(), dict) or (loaded_at and (int(time.time()) - loaded_at) > max(10, ttl_g // 2))
        if should_refresh_gems:
            try:
                asyncio.create_task(_refresh_sheet_gems_background(ws, str(getattr(ws.state, "user_lang", "") or "")), name="refresh_sheet_gems")
            except Exception:
                pass

        base_config = {
            "response_modalities": ["AUDIO", "TEXT"],
            "input_audio_transcription": {},
            "output_audio_transcription": {},
            "system_instruction": system_instruction,
            "tools": [
                {"function_declarations": _mcp_tool_declarations()},
            ],
        }

        base_candidates = [
            "gemini-2.0-flash-live-001",
            "gemini-2.5-flash-native-audio-preview-12-2025",
            "gemini-2.5-flash-native-audio-preview-09-2025",
            "gemini-2.5-flash-native-audio-latest",
        ]

        raw_candidates = [
            GEMINI_LIVE_MODEL_OVERRIDE,
            *(base_candidates if GEMINI_LIVE_MODEL_OVERRIDE else [GEMINI_LIVE_MODEL_DEFAULT, *base_candidates]),
        ]

        # Gemini Live model naming can vary by endpoint/version. Be permissive:
        # - accept both with and without the `models/` prefix
        # - try `models/<id>` first to match `models.list()` output
        expanded: list[str] = []
        for m in raw_candidates:
            m = str(m or "").strip()
            if not m:
                continue
            # Prefer unprefixed names first. Some endpoints reject the `models/` prefix.
            expanded.append(_normalize_model_name(m))
            expanded.append(_normalize_models_prefix(m))

        seen: set[str] = set()
        model_candidates = [m for m in expanded if m and not (m in seen or seen.add(m))]

        logger.info(
            "gemini_live_connect model=%s",
            model_candidates[0] if model_candidates else (GEMINI_LIVE_MODEL_OVERRIDE or GEMINI_LIVE_MODEL_DEFAULT),
        )

        # Resilient supervision: keep the client WS open even if Gemini fails.
        gemini_failed_event: asyncio.Event = asyncio.Event()
        gemini_failed_error: dict[str, Any] | None = None

        async def _safe_gemini_to_ws_loop(ws2: WebSocket, session2: Any) -> None:
            try:
                await _gemini_to_ws_loop(ws2, session2)
            except Exception as e:
                model_used = getattr(ws2.state, "gemini_live_model", None) or (GEMINI_LIVE_MODEL_OVERRIDE or GEMINI_LIVE_MODEL_DEFAULT)
                classified = _classify_gemini_live_error(e, _normalize_model_name(str(model_used)))
                if classified.get("kind") == "gemini_model_not_found":
                    logger.warning(
                        "gemini_to_ws_failed_model_not_found model=%s error=%s",
                        _normalize_model_name(str(model_used)),
                        classified.get("detail"),
                    )
                else:
                    logger.exception("gemini_to_ws_failed error=%s", str(e))

                logger.info(
                    "gemini_to_ws_failed_meta model=%s exc_type=%s status_code=%s",
                    model_used,
                    type(e).__name__,
                    getattr(e, "status_code", None),
                )
                try:
                    await _ws_send_json(ws2, {"type": "error", **classified})
                except Exception:
                    pass

                # Signal the session runner so it can tear down and retry with the
                # next candidate model.
                nonlocal gemini_failed_error
                gemini_failed_error = classified
                gemini_failed_event.set()

        async def _run_with_config(model: str, cfg: dict[str, Any]) -> None:
            nonlocal gemini_failed_error, connected_sent
            gemini_failed_error = None
            try:
                gemini_failed_event.clear()
            except Exception:
                pass
            ws.state.gemini_live_model = model
            session_cm = client.aio.live.connect(model=model, config=cfg)
            try:
                async with session_cm as session:
                    logger.info("gemini_live_connected model=%s", model)
                    ws.state.gemini_live_session = session
                    await _ws_send_json(ws, {"type": "state", "state": "connected", "instance_id": INSTANCE_ID})
                    connected_sent = True
                    try:
                        await _emit_live_connect_greeting(ws)
                    except Exception:
                        pass

                    to_gemini = asyncio.create_task(_ws_to_gemini_loop(ws, session), name="ws_to_gemini")
                    to_ws = asyncio.create_task(_safe_gemini_to_ws_loop(ws, session), name="gemini_to_ws")
                    wait_failed: asyncio.Task[bool] | None = None

                    try:
                        # Either the client disconnects (ws_to_gemini finishes) or Gemini fails.
                        wait_failed = asyncio.create_task(gemini_failed_event.wait(), name="gemini_failed_wait")
                        done, pending = await asyncio.wait(
                            {to_gemini, wait_failed},
                            return_when=asyncio.FIRST_COMPLETED,
                        )

                        if wait_failed in done and gemini_failed_event.is_set():
                            # Gemini failed; tear down this session to allow outer retry.
                            if not to_gemini.done():
                                to_gemini.cancel()
                                try:
                                    await to_gemini
                                except asyncio.CancelledError:
                                    pass
                                except Exception:
                                    pass
                            if not to_ws.done():
                                to_ws.cancel()
                                try:
                                    await to_ws
                                except asyncio.CancelledError:
                                    pass
                                except Exception:
                                    pass

                            detail = (gemini_failed_error or {}).get("detail") or "gemini_failed"
                            kind = (gemini_failed_error or {}).get("kind")
                            if kind == "gemini_model_not_found":
                                raise _GeminiLiveModelNotFound(str(detail))
                            raise _GeminiLiveSessionFailed(str(detail))

                        # Client disconnected or finished.
                        await to_gemini
                    except WebSocketDisconnect:
                        return
                    finally:
                        try:
                            if wait_failed is not None and not wait_failed.done():
                                wait_failed.cancel()
                        except Exception:
                            pass

                        if not to_ws.done():
                            to_ws.cancel()
                            try:
                                await to_ws
                            except asyncio.CancelledError:
                                pass
                            except Exception:
                                pass
            finally:
                try:
                    ws.state.gemini_live_session = None
                except Exception:
                    pass

        last_error: Exception | None = None
        candidates = model_candidates or [GEMINI_LIVE_MODEL_OVERRIDE or GEMINI_LIVE_MODEL_DEFAULT]
        for cand in candidates:
            try:
                await _run_with_config(str(cand), dict(base_config))
                return
            except _GeminiLiveModelNotFound as e:
                last_error = e
                continue
            except _GeminiLiveSessionFailed as e:
                last_error = e
                break
            except Exception as e:
                last_error = e
                break

        if last_error is not None:
            msg = str(last_error)
            model_used = getattr(ws.state, "gemini_live_model", None) or (GEMINI_LIVE_MODEL_OVERRIDE or GEMINI_LIVE_MODEL_DEFAULT)
            model_used_norm = _normalize_model_name(str(model_used))

            if "invalid argument" in msg.lower():
                cfg = dict(base_config)
                cfg["response_modalities"] = ["AUDIO"]
                logger.warning(
                    "gemini_live_connect_retry_invalid_argument model=%s before=%s after=%s error=%s",
                    model_used_norm,
                    base_config.get("response_modalities"),
                    cfg.get("response_modalities"),
                    msg,
                )
                await _run_with_config(str(model_used_norm), cfg)
                return

            classified = _classify_gemini_live_error(last_error, model_used_norm)
            if classified.get("kind") == "gemini_model_not_found":
                logger.warning(
                    "gemini_live_connect_failed_model_not_found model=%s error=%s",
                    model_used_norm,
                    classified.get("detail"),
                )
            else:
                logger.exception("gemini_live_session_failed model=%s error=%s", model_used_norm, msg)

            try:
                await _ws_send_json(ws, {"type": "error", **classified})
            except Exception:
                pass

            # Keep the client ws connected even if Gemini is unavailable.
            if not connected_sent:
                try:
                    await _ws_send_json(ws, {"type": "state", "state": "connected", "instance_id": INSTANCE_ID})
                except Exception:
                    pass
            try:
                await _ws_local_only_loop(ws)
            except Exception:
                pass
            return

        # No candidates worked and no error captured: keep the client alive.
        try:
            if not connected_sent:
                await _ws_send_json(ws, {"type": "state", "state": "connected", "instance_id": INSTANCE_ID})
                try:
                    await _emit_live_connect_greeting(ws)
                except Exception:
                    pass
            await _ws_local_only_loop(ws)
        except Exception:
            pass
        return
    finally:
        notes_board_task = getattr(ws.state, "notes_board_task", None)
        if notes_board_task is not None and hasattr(notes_board_task, "done") and not notes_board_task.done():
            try:
                notes_board_task.cancel()
                try:
                    await notes_board_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            except Exception:
                pass

        try:
            sid = str(getattr(ws.state, "session_id", None) or "").strip()
        except Exception:
            sid = ""
        if sid:
            try:
                cur = _SESSION_WS.get(sid)
                if cur is ws:
                    _SESSION_WS.pop(sid, None)
            except Exception:
                pass
        s = _ws_by_user.get(user_id)
        if s is not None:
            s.discard(ws)
