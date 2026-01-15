from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import logging
import math
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Iterable, List, Literal, Optional, Tuple
from urllib.parse import urlparse, urlunparse
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

APP_NAME = "mcp-acc"
APP_VERSION = "0.1.0"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(APP_NAME)

PORT = int(os.getenv("PORT", "8092"))

MCP_ACC_DATA_PATH = os.getenv("MCP_ACC_DATA_PATH", "/data/mcp-acc/cache.json")
MCP_ACC_CACHE_TTL_SECONDS = int(os.getenv("MCP_ACC_CACHE_TTL_SECONDS", "3600"))
MCP_ACC_TIMEOUT_SECONDS = float(os.getenv("MCP_ACC_TIMEOUT_SECONDS", "45"))

MCP_AUDIDOC_BASE_URL = (os.getenv("MCP_AUDIDOC_BASE_URL") or "").strip().rstrip("/")

MCP_ACC_LLM_BASE_URL = (os.getenv("MCP_ACC_LLM_BASE_URL") or "http://host.docker.internal:8181/v1").strip().rstrip("/")
MCP_ACC_LLM_API_KEY = (os.getenv("MCP_ACC_LLM_API_KEY") or "").strip()
MCP_ACC_LLM_MODEL = (os.getenv("MCP_ACC_LLM_MODEL") or "glama-default").strip()
MCP_ACC_LLM_TEMPERATURE = float(os.getenv("MCP_ACC_LLM_TEMPERATURE", "0.2"))
MCP_ACC_LLM_MAX_TOKENS = int(os.getenv("MCP_ACC_LLM_MAX_TOKENS", "300"))
MCP_ACC_LLM_TIMEOUT_SECONDS = float(os.getenv("MCP_ACC_LLM_TIMEOUT_SECONDS", "120"))

DEFAULT_SHEET_INCOME_URL = os.getenv(
    "MCP_ACC_SHEET_INCOME_URL",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRz4D64DEUgKWHCr2jOqu7SMbg4j-PYODnVTfsxqOBrdllbtU3TgctOxFSnXBbge-c2K_FuTDp6OuLo/pubhtml/sheet?headers=false&gid=2136721077",
)
DEFAULT_SHEET_EXPENSE_URL = os.getenv(
    "MCP_ACC_SHEET_EXPENSE_URL",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRz4D64DEUgKWHCr2jOqu7SMbg4j-PYODnVTfsxqOBrdllbtU3TgctOxFSnXBbge-c2K_FuTDp6OuLo/pubhtml/sheet?headers=false&gid=2097719843",
)


def _utc_ms() -> int:
    return int(time.time() * 1000)


def _ensure_dir_for_file(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _read_json_file(path: str) -> Optional[Dict[str, Any]]:
    try:
        p = Path(path)
        if not p.exists():
            return None
        raw = p.read_text(encoding="utf-8")
        return json.loads(raw)
    except Exception:
        return None


def _write_json_file(path: str, obj: Dict[str, Any]) -> None:
    _ensure_dir_for_file(path)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_is_fresh(cache: Dict[str, Any]) -> bool:
    try:
        fetched_ms = int(cache.get("fetchedAtMs") or 0)
    except Exception:
        fetched_ms = 0
    if fetched_ms <= 0:
        return False
    return (_utc_ms() - fetched_ms) < (MCP_ACC_CACHE_TTL_SECONDS * 1000)


def _safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"


def _sum_amounts(records: List[Dict[str, Any]]) -> float:
    total = 0.0
    for r in records:
        if not isinstance(r, dict):
            continue
        a = _pick_amount_from_record(r)
        if a is None:
            continue
        total += float(a)
    return float(total)


def _group_sum_by_yy_mm(records: List[Dict[str, Any]], *, max_keys: int = 12) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        a = _pick_amount_from_record(r)
        if a is None:
            continue
        yy_mm = str(r.get("yy_mm") or r.get("หมายเหตุ") or "").strip()
        if not yy_mm:
            yy_mm = "(unknown)"
        out[yy_mm] = float(out.get(yy_mm) or 0.0) + float(a)

    # Keep context bounded.
    items = sorted(out.items(), key=lambda kv: float(kv[1]), reverse=True)
    trimmed = dict(items[: max(1, int(max_keys))])
    return trimmed


def _maybe_extract_filter_from_message(message: str) -> Dict[str, str]:
    msg = str(message or "")
    out: Dict[str, str] = {}
    m = re.search(r"\b(\d{2}_\d{2})\b", msg)
    if m:
        out["yy_mm"] = m.group(1)
    m = re.search(r"\b(\d{4}-\d{2})\b", msg)
    if m:
        out["period"] = m.group(1)
    m = re.search(r"\b([A-Z]-\d{1,4})\b", msg)
    if m:
        out["unit"] = m.group(1)
    m = re.search(r"\b(\d{3,4}/\d{3,6}(?:-\d+)?)\b", msg)
    if m:
        out["receipt"] = m.group(1)
    return out


def _parse_query_args_from_message(message: str) -> Optional[AccQueryArgs]:
    msg = str(message or "").strip()
    if not msg:
        return None

    lower = msg.lower()
    sheet: Literal["income", "expense", "both"] = "both"
    if "income" in lower or "รายรับ" in msg:
        sheet = "income"
    if "expense" in lower or "รายจ่าย" in msg:
        sheet = "expense" if sheet == "both" else sheet
    if "both" in lower or "ทั้ง" in msg:
        sheet = "both"

    yy_mm = ""
    m = re.search(r"\b\d{2}_\d{2}\b", msg)
    if m:
        yy_mm = m.group(0)
    else:
        m2 = re.search(r"yy_mm\s*[:=]\s*([0-9]{2}_[0-9]{2})", lower)
        if m2:
            yy_mm = m2.group(1)

    unit = ""
    m = re.search(r"\b[a-zA-Z]\s*[-_ ]?\s*\d{1,4}\b", msg)
    if m:
        unit = m.group(0)
    else:
        m2 = re.search(r"unit\s*[:=]\s*([a-zA-Z]-\d{1,4})", msg)
        if m2:
            unit = m2.group(1)

    receipt = ""
    # Common formats: 2029/1465, NAI2568.009, NAC2567.001
    m = re.search(r"\b\d{3,5}/\d{2,6}\b", msg)
    if m:
        receipt = m.group(0)
    else:
        m3 = re.search(r"\b[A-Z]{2,4}\d{4}\.\d{3}\b", msg)
        if m3:
            receipt = m3.group(0)
        else:
            m2 = re.search(r"receipt\s*[:=]\s*([^\s]+)", lower)
            if m2:
                receipt = m2.group(1)

    if unit:
        unit = unit.replace(" ", "").replace("_", "-")
        m_unit = re.match(r"^([A-Za-z])(\d{1,4})$", unit)
        if m_unit:
            unit = f"{m_unit.group(1)}-{m_unit.group(2)}"

    pv = ""
    m = re.search(r"\bpv\s*[:=]\s*([^\s]+)", msg, flags=re.IGNORECASE)
    if m:
        pv = m.group(1)

    contains = ""
    m = re.search(r"contains\s*[:=]\s*(.+)$", msg, flags=re.IGNORECASE)
    if m:
        contains = m.group(1).strip()

    should_query = False
    if yy_mm or unit or receipt or pv or contains:
        should_query = True
    if lower.startswith("list") or lower.startswith("show") or "หา" in msg or "ค้น" in msg:
        should_query = True

    if not should_query:
        return None

    return AccQueryArgs(sheet=sheet, contains=contains, receipt=receipt, pv=pv, unit=unit, yy_mm=yy_mm, limit=50)


def _parse_query_intent_from_message(message: str) -> Tuple[str, Optional[AccQueryArgs], Optional[int]]:
    # Returns (mode, args, top_n). mode in: table|sum|top|none
    msg = str(message or "").strip()
    if not msg:
        return ("none", None, None)
    lower = msg.lower()

    qargs = _parse_query_args_from_message(msg)
    if qargs is None:
        return ("none", None, None)

    if (
        lower.startswith("sum")
        or "รวม" in msg
        or "ยอดรวม" in msg
        or "สรุป" in msg
        or "สรุปยอด" in msg
        or "total" in lower
    ):
        return ("sum", qargs, None)

    m = re.search(r"\btop\s*(\d{1,2})\b", lower)
    if m:
        return ("top", qargs, int(m.group(1)))
    if lower.startswith("top"):
        return ("top", qargs, 10)

    # Thai top-N patterns
    m = re.search(r"(?:ท็อป|ทอป|top)\s*(\d{1,2})", msg, flags=re.IGNORECASE)
    if m:
        return ("top", qargs, int(m.group(1)))
    m = re.search(r"\b(\d{1,2})\s*(?:อันดับ|รายการ)\b", msg)
    if m:
        return ("top", qargs, int(m.group(1)))
    if "มากที่สุด" in msg or "สูงสุด" in msg:
        # Default to top 10 for 'most' queries
        return ("top", qargs, 10)

    return ("table", qargs, None)


def _iter_matching_records(records: List[Dict[str, Any]], args: AccQueryArgs) -> Iterable[Dict[str, Any]]:
    for r in records:
        if not isinstance(r, dict):
            continue
        if _record_matches_query(r, args):
            yield r


def _extract_amount_for_summary(r: Dict[str, Any]) -> Optional[float]:
    for k in ("ยอดเงิน", "จำนวนเงิน", "amount", "total", "TOTAL"):
        v = _parse_amount(r.get(k))
        if v is not None:
            return float(v)
    v2 = _pick_amount_from_record(r)
    return float(v2) if v2 is not None else None


def _render_query_summary(results: Dict[str, Any], args: AccQueryArgs) -> str:
    def _sum_rows(rows: List[Dict[str, Any]]) -> Tuple[int, float]:
        c = 0
        s = 0.0
        for r in rows:
            amt = _extract_amount_for_summary(r)
            if amt is None:
                continue
            c += 1
            s += float(amt)
        return c, s

    income_rows = (results.get("income") or []) if isinstance(results, dict) else []
    expense_rows = (results.get("expense") or []) if isinstance(results, dict) else []
    ic, isum = _sum_rows(income_rows if isinstance(income_rows, list) else [])
    ec, esum = _sum_rows(expense_rows if isinstance(expense_rows, list) else [])
    lines: List[str] = []
    lines.append("สรุปยอด (query)")
    lines.append(f"- sheet: {args.sheet}")
    if args.yy_mm:
        lines.append(f"- yy_mm: {args.yy_mm}")
    if args.unit:
        lines.append(f"- unit: {args.unit}")
    if args.receipt:
        lines.append(f"- receipt: {args.receipt}")
    if args.contains:
        lines.append(f"- contains: {args.contains}")
    lines.append("")
    if args.sheet in ("income", "both"):
        lines.append(f"income: {ic} rows, total={_fmt_money(isum)}")
    if args.sheet in ("expense", "both"):
        lines.append(f"expense: {ec} rows, total={_fmt_money(esum)}")
    return "\n".join(lines).strip() + "\n"


def _query_results_from_cache(cache: Dict[str, Any], args: AccQueryArgs) -> Dict[str, Any]:
    sheets = (cache.get("sheets") or {}) if isinstance(cache, dict) else {}
    income_records = ((sheets.get("income") or {}).get("records") or [])
    expense_records = ((sheets.get("expense") or {}).get("records") or [])
    results: Dict[str, Any] = {"income": [], "expense": []}
    if args.sheet in ("income", "both"):
        results["income"] = _query_records(income_records, args)
    if args.sheet in ("expense", "both"):
        results["expense"] = _query_records(expense_records, args)
    return results


def _render_query_intent(cache: Dict[str, Any], mode: str, args: AccQueryArgs, top_n: Optional[int]) -> str:
    results = _query_results_from_cache(cache, args)
    if mode == "sum":
        return _render_query_summary(results, args)
    if mode == "top":
        n = int(top_n or 10)
        return _render_query_top(results, args, n)
    return _render_query_results(results, args)


def _render_query_top(results: Dict[str, Any], args: AccQueryArgs, top_n: int) -> str:
    def _decorate(rows: List[Dict[str, Any]]) -> List[Tuple[float, Dict[str, Any]]]:
        out: List[Tuple[float, Dict[str, Any]]] = []
        for r in rows:
            amt = _extract_amount_for_summary(r)
            if amt is None:
                continue
            out.append((float(amt), r))
        out.sort(key=lambda x: x[0], reverse=True)
        return out

    income_rows = (results.get("income") or []) if isinstance(results, dict) else []
    expense_rows = (results.get("expense") or []) if isinstance(results, dict) else []

    lines: List[str] = []
    lines.append(f"Top {top_n} (query)")
    lines.append(f"- sheet: {args.sheet}")
    if args.yy_mm:
        lines.append(f"- yy_mm: {args.yy_mm}")
    if args.unit:
        lines.append(f"- unit: {args.unit}")
    if args.contains:
        lines.append(f"- contains: {args.contains}")
    lines.append("")

    def _emit(title: str, decorated: List[Tuple[float, Dict[str, Any]]]):
        lines.append(f"{title}: {min(top_n, len(decorated))}/{len(decorated)}")
        if not decorated:
            lines.append("")
            return
        lines.append("amount | date | unit | receipt | item")
        lines.append("---:|---|---|---|---")
        for amt, r in decorated[:top_n]:
            dt = str(r.get("วันที่") or r.get("วันที") or r.get("date") or "")
            un = str(r.get("ยูนิต") or r.get("unit") or "")
            rc = str(r.get("ใบเสร็จ") or r.get("receipt") or "")
            desc = str(r.get("รายการ") or r.get("รายละเอียด") or r.get("desc") or "")
            desc = desc.replace("\n", " ").strip()
            if len(desc) > 80:
                desc = desc[:80] + "…"
            lines.append(f"{_fmt_money(amt)} | {dt} | {un} | {rc} | {desc}")
        lines.append("")

    if args.sheet in ("income", "both"):
        _emit("income", _decorate(income_rows if isinstance(income_rows, list) else []))
    if args.sheet in ("expense", "both"):
        _emit("expense", _decorate(expense_rows if isinstance(expense_rows, list) else []))

    return "\n".join(lines).strip() + "\n"


def _render_query_results(results: Dict[str, Any], args: AccQueryArgs) -> str:
    def _pick_amount(r: Dict[str, Any]) -> Optional[float]:
        if not isinstance(r, dict):
            return None
        for k in ("ยอดเงิน", "จำนวนเงิน", "amount", "total", "TOTAL"):
            v = _parse_amount(r.get(k))
            if v is not None:
                return float(v)
        v2 = _pick_amount_from_record(r)
        return float(v2) if v2 is not None else None

    def _pick_date(r: Dict[str, Any]) -> str:
        for k in ("วันที่", "วันที", "date"):
            v = r.get(k)
            if v:
                return str(v)
        return ""

    def _pick_desc(r: Dict[str, Any]) -> str:
        for k in ("รายการ", "รายละเอียด", "desc", "description"):
            v = r.get(k)
            if v:
                return str(v)
        return ""

    def _pick_receipt(r: Dict[str, Any]) -> str:
        for k in ("ใบเสร็จ", "receipt"):
            v = r.get(k)
            if v:
                return str(v)
        return ""

    def _pick_unit(r: Dict[str, Any]) -> str:
        for k in ("ยูนิต", "unit"):
            v = r.get(k)
            if v:
                return str(v)
        return ""

    lines: List[str] = []
    lines.append("ผลลัพธ์จากชีท (query)")
    lines.append("")
    lines.append(f"- sheet: {args.sheet}")
    if args.yy_mm:
        lines.append(f"- yy_mm: {args.yy_mm}")
    if args.unit:
        lines.append(f"- unit: {args.unit}")
    if args.receipt:
        lines.append(f"- receipt: {args.receipt}")
    if args.pv:
        lines.append(f"- pv: {args.pv}")
    if args.contains:
        lines.append(f"- contains: {args.contains}")
    lines.append("")

    income = results.get("income") if isinstance(results, dict) else None
    expense = results.get("expense") if isinstance(results, dict) else None
    income_rows = income if isinstance(income, list) else []
    expense_rows = expense if isinstance(expense, list) else []

    def _emit_block(title: str, rows: List[Dict[str, Any]]):
        lines.append(f"{title}: {len(rows)}")
        if not rows:
            lines.append("")
            return
        lines.append("date | unit | receipt | amount | item")
        lines.append("---|---|---|---:|---")
        for r in rows[: min(len(rows), 25)]:
            dt = _pick_date(r)
            un = _pick_unit(r)
            rc = _pick_receipt(r)
            am = _pick_amount(r)
            desc = _pick_desc(r)
            desc = desc.replace("\n", " ").strip()
            if len(desc) > 80:
                desc = desc[:80] + "…"
            lines.append(f"{dt} | {un} | {rc} | {_fmt_money(am) if am is not None else ''} | {desc}")
        lines.append("")

    if args.sheet in ("income", "both"):
        _emit_block("income", income_rows)
    if args.sheet in ("expense", "both"):
        _emit_block("expense", expense_rows)

    return "\n".join(lines).strip() + "\n"


def _build_llm_context(cache: Dict[str, Any], message: str, *, max_rows: int = 3) -> Dict[str, Any]:
    sheets = (cache.get("sheets") or {}) if isinstance(cache, dict) else {}
    income_records = ((sheets.get("income") or {}).get("records") or [])
    expense_records = ((sheets.get("expense") or {}).get("records") or [])

    filters = _maybe_extract_filter_from_message(message)
    yy_mm = filters.get("yy_mm") or ""
    if yy_mm:
        income_records = [r for r in income_records if isinstance(r, dict) and _record_matches_yy_mm(r, yy_mm)]
        expense_records = [r for r in expense_records if isinstance(r, dict) and _record_matches_yy_mm(r, yy_mm)]

    receipt = (filters.get("receipt") or "").strip()
    unit = (filters.get("unit") or "").strip()
    if receipt or unit:
        def _match_row(r: Dict[str, Any]) -> bool:
            blob = " ".join(str(v or "") for v in r.values())
            if receipt and receipt not in blob:
                return False
            if unit and unit not in blob:
                return False
            return True

        income_records = [r for r in income_records if isinstance(r, dict) and _match_row(r)]
        expense_records = [r for r in expense_records if isinstance(r, dict) and _match_row(r)]

    # If the user didn't specify any narrowing filters and the prompt is short,
    # avoid sending raw row samples (keeps the LLM call fast and stable).
    want_rows = bool(filters) or len((message or "").strip()) >= 40
    n_rows = max_rows if want_rows else 0
    income_rows = [r for r in income_records[:n_rows] if isinstance(r, dict)]
    expense_rows = [r for r in expense_records[:n_rows] if isinstance(r, dict)]

    return {
        "cache": {
            "fetchedAtMs": int(cache.get("fetchedAtMs") or 0) if isinstance(cache, dict) else 0,
            "sources": cache.get("sources") if isinstance(cache, dict) else {},
        },
        "filters": filters,
        "income": {
            "count": len(income_records),
            "total": _sum_amounts(income_records),
            "by_yy_mm": _group_sum_by_yy_mm(income_records, max_keys=12),
            "rows": income_rows,
        },
        "expense": {
            "count": len(expense_records),
            "total": _sum_amounts(expense_records),
            "by_yy_mm": _group_sum_by_yy_mm(expense_records, max_keys=12),
            "rows": expense_rows,
        },
    }


async def _llm_chat(messages: List[Dict[str, Any]]) -> str:
    base = MCP_ACC_LLM_BASE_URL
    parsed = urlparse(base)
    host = parsed.hostname or ""
    resolved_host = host
    host_header = ""
    if host:
        try:
            resolved_host = socket.gethostbyname(host)
            if resolved_host and resolved_host != host:
                host_header = host
        except Exception:
            resolved_host = host

    netloc = resolved_host
    if parsed.port:
        netloc = f"{resolved_host}:{parsed.port}"
    resolved_base = urlunparse((parsed.scheme, netloc, parsed.path.rstrip("/"), "", "", ""))

    url = f"{resolved_base}/chat/completions"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if MCP_ACC_LLM_API_KEY:
        headers["Authorization"] = f"Bearer {MCP_ACC_LLM_API_KEY}"
    if host_header:
        headers["Host"] = host_header

    payload: Dict[str, Any] = {
        "model": MCP_ACC_LLM_MODEL,
        "messages": messages,
        "temperature": MCP_ACC_LLM_TEMPERATURE,
        "max_tokens": MCP_ACC_LLM_MAX_TOKENS,
        "stream": False,
    }

    def _do() -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        cmd = [
            "curl",
            "-sS",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
        ]
        if MCP_ACC_LLM_API_KEY:
            cmd.extend(["-H", f"Authorization: Bearer {MCP_ACC_LLM_API_KEY}"])
        if host_header:
            cmd.extend(["-H", f"Host: {host_header}"])
        cmd.extend(["--data-binary", "@-", url])

        try:
            r = subprocess.run(
                cmd,
                input=body,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=MCP_ACC_LLM_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("llm_timeout") from exc

        out = (r.stdout or b"").decode("utf-8", errors="replace")
        err = (r.stderr or b"").decode("utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"llm_curl_failed: {err[:1000]}")

        try:
            return json.loads(out)
        except Exception as exc:
            raise RuntimeError(f"llm_invalid_json: {out[:1000]}") from exc

    data = await asyncio.to_thread(_do)

    try:
        return str((((data.get("choices") or [])[0] or {}).get("message") or {}).get("content") or "").strip()
    except Exception:
        return ""


def _openai_stream_text_events_from_bytes(chunks: List[bytes]) -> str:
    # Helper for tests/debug (not used in production streaming).
    text = b"".join(chunks).decode("utf-8", errors="replace")
    out: List[str] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            break
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        delta = ((((obj.get("choices") or [])[0] or {}).get("delta") or {}).get("content") or "")
        if delta:
            out.append(str(delta))
    return "".join(out)


async def _llm_chat_stream(messages: List[Dict[str, Any]]):
    # Streams plain text chunks (not SSE) back to the caller.
    url = f"{MCP_ACC_LLM_BASE_URL}/chat/completions"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if MCP_ACC_LLM_API_KEY:
        headers["Authorization"] = f"Bearer {MCP_ACC_LLM_API_KEY}"

    def _extract_delta(obj: Any) -> str:
        if not isinstance(obj, dict):
            return ""
        choices = obj.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        c0 = choices[0]
        if not isinstance(c0, dict):
            return ""
        delta = c0.get("delta")
        if not isinstance(delta, dict):
            return ""
        content = delta.get("content")
        return content if isinstance(content, str) else ""

    payload: Dict[str, Any] = {
        "model": MCP_ACC_LLM_MODEL,
        "messages": messages,
        "temperature": MCP_ACC_LLM_TEMPERATURE,
        "max_tokens": MCP_ACC_LLM_MAX_TOKENS,
        "stream": True,
    }

    timeout = httpx.Timeout(
        connect=min(10.0, MCP_ACC_LLM_TIMEOUT_SECONDS),
        read=MCP_ACC_LLM_TIMEOUT_SECONDS,
        write=min(30.0, MCP_ACC_LLM_TIMEOUT_SECONDS),
        pool=MCP_ACC_LLM_TIMEOUT_SECONDS,
    )

    async def _httpx_stream():
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=False) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    body = ""
                    try:
                        body = (await resp.aread()).decode("utf-8", errors="replace")[:1000]
                    except Exception:
                        body = ""
                    raise httpx.HTTPStatusError(
                        message=f"llm_http_{resp.status_code}: {body}",
                        request=exc.request,
                        response=exc.response,
                    ) from exc

                lines = resp.aiter_lines()
                line_idle_timeout = min(10.0, MCP_ACC_LLM_TIMEOUT_SECONDS)
                while True:
                    try:
                        line = await asyncio.wait_for(lines.__anext__(), timeout=line_idle_timeout)
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError as exc:
                        # Treat "no streamed output" as a read timeout so callers can fall back.
                        raise httpx.ReadTimeout("llm_stream_idle_timeout", request=resp.request) from exc

                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    payload_line = line[len("data:") :].strip()
                    if payload_line == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload_line)
                    except Exception:
                        continue
                    delta_txt = _extract_delta(obj)
                    if delta_txt:
                        yield delta_txt

    async def _curl_stream():
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        cmd: List[str] = [
            "curl",
            "-sS",
            "-N",
            "--no-buffer",
            "--http1.1",
            "-X",
            "POST",
            "-H",
            "content-type: application/json",
            "-H",
            "accept: text/event-stream",
        ]
        if MCP_ACC_LLM_API_KEY:
            cmd += ["-H", f"authorization: Bearer {MCP_ACC_LLM_API_KEY}"]
        cmd += ["--data-binary", "@-", url]

        # Timeout should behave like a "no data received" timeout (idle timeout), not a total
        # request duration timeout. Reset the clock on every received bytes chunk.
        last_data_ts = time.time()
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            assert proc.stdin is not None
            assert proc.stdout is not None
            proc.stdin.write(body)
            proc.stdin.close()

            buf = b""

            while True:
                idle_for = time.time() - last_data_ts
                if idle_for > MCP_ACC_LLM_TIMEOUT_SECONDS:
                    raise RuntimeError("llm_timeout")

                # Read raw bytes so we don't block waiting for a newline.
                wait_s = max(0.5, MCP_ACC_LLM_TIMEOUT_SECONDS - idle_for)
                try:
                    fd = proc.stdout.fileno()
                    chunk = await asyncio.wait_for(asyncio.to_thread(os.read, fd, 4096), timeout=wait_s)
                except asyncio.TimeoutError as exc:
                    raise RuntimeError("llm_timeout") from exc

                if not chunk:
                    break

                last_data_ts = time.time()
                buf += chunk

                # Parse incrementally by newline. This is robust even if the upstream doesn't emit
                # blank-line delimiters promptly.
                while True:
                    nl = buf.find(b"\n")
                    if nl < 0:
                        break

                    raw_line = buf[:nl + 1]
                    buf = buf[nl + 1 :]

                    try:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                    except Exception:
                        continue

                    if not line.startswith("data:"):
                        continue

                    payload_line = line[len("data:") :].strip()
                    if payload_line == "[DONE]":
                        return

                    try:
                        obj = json.loads(payload_line)
                    except Exception:
                        continue

                    delta_txt = _extract_delta(obj)
                    if delta_txt:
                        yield delta_txt

            rc = proc.wait(timeout=1)
            if rc != 0:
                err = (proc.stderr.read() if proc.stderr else b"")
                err_txt = (err or b"").decode("utf-8", errors="replace")[:1000]
                raise RuntimeError(f"llm_curl_failed: {err_txt}")
        finally:
            try:
                proc.kill()
            except Exception:
                pass

    try:
        async for chunk in _httpx_stream():
            yield chunk
    except httpx.HTTPError:
        async for chunk in _curl_stream():
            yield chunk


def _extract_table_rows_from_pubhtml(html: str) -> List[List[str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find("table", {"class": "waffle"})
    if not table:
        return []

    rows: List[List[str]] = []
    tbody = table.find("tbody")
    if not tbody:
        return []

    for tr in tbody.find_all("tr"):
        # skip freeze bar rows (they have freezebar-cell)
        if tr.find("td", {"class": "freezebar-cell"}):
            continue
        tds = tr.find_all("td")
        if not tds:
            continue
        row: List[str] = []
        for td in tds:
            txt = td.get_text(" ", strip=True)
            row.append(txt)
        rows.append(row)

    return rows


def _rows_to_records(rows: List[List[str]]) -> Dict[str, Any]:
    if not rows:
        return {"headers": [], "records": []}

    headers = [h.strip() for h in (rows[0] or [])]
    records: List[Dict[str, Any]] = []
    for r in rows[1:]:
        rec: Dict[str, Any] = {}
        for i, h in enumerate(headers):
            key = h or f"col_{i}"
            rec[key] = (r[i] if i < len(r) else "")
        records.append(rec)

    return {"headers": headers, "records": records}


async def _fetch_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=MCP_ACC_TIMEOUT_SECONDS, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


async def _refresh_cache(
    income_url: str,
    expense_url: str,
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=MCP_ACC_TIMEOUT_SECONDS, follow_redirects=True) as client:
        income_task = client.get(income_url)
        expense_task = client.get(expense_url)
        income_resp, expense_resp = await asyncio.gather(income_task, expense_task)

    income_resp.raise_for_status()
    expense_resp.raise_for_status()

    # Google Sheets pubhtml is UTF-8; force decode to avoid mojibake headers/values.
    income_html = income_resp.content.decode("utf-8", errors="replace")
    expense_html = expense_resp.content.decode("utf-8", errors="replace")

    income_rows = _extract_table_rows_from_pubhtml(income_html)
    expense_rows = _extract_table_rows_from_pubhtml(expense_html)

    income = _rows_to_records(income_rows)
    expense = _rows_to_records(expense_rows)

    out: Dict[str, Any] = {
        "ok": True,
        "fetchedAtMs": _utc_ms(),
        "sources": {
            "income": {"url": income_url, "rows": len(income.get("records") or [])},
            "expense": {"url": expense_url, "rows": len(expense.get("records") or [])},
        },
        "sheets": {
            "income": income,
            "expense": expense,
        },
    }

    _write_json_file(MCP_ACC_DATA_PATH, out)
    return out


def _build_amount_index(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            continue
        amt = _pick_amount_from_record(r)
        if amt is None:
            continue
        out.append({"index": i, "amount": float(amt), "record": r})
    return out


def _score_amount_match(pdf_amount: float, sheet_amount: float, *, abs_tol: float, pct_tol: float) -> Optional[float]:
    diff = abs(float(pdf_amount) - float(sheet_amount))
    tol = max(float(abs_tol), abs(float(sheet_amount)) * float(pct_tol))
    if diff > tol:
        return None
    return 1.0 - (diff / max(tol, 1e-9))


def _best_sheet_matches(
    pdf_amount: float,
    items: List[Dict[str, Any]],
    *,
    abs_tol: float,
    pct_tol: float,
    limit: int,
) -> List[Dict[str, Any]]:
    scored: List[Dict[str, Any]] = []
    for it in items:
        try:
            amt = float(it.get("amount"))
        except Exception:
            continue
        score = _score_amount_match(pdf_amount, amt, abs_tol=abs_tol, pct_tol=pct_tol)
        if score is None:
            continue
        scored.append(
            {
                "score": float(score),
                "sheet_index": int(it.get("index") or 0),
                "sheet_amount": amt,
                "sheet_record": it.get("record") or {},
            }
        )
    scored.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return scored[: max(1, int(limit))]


def _extract_hints_from_text(text: Any) -> Dict[str, str]:
    s = str(text or "")
    out: Dict[str, str] = {}

    m = re.search(r"\b([A-Z]-\d{1,4})\b", s)
    if m:
        out["unit"] = m.group(1)

    m = re.search(r"\b(\d{3,4}/\d{3,6}(?:-\d+)?)\b", s)
    if m:
        out["receipt"] = m.group(1)
    else:
        m = re.search(r"\b(NAI\d{4}\.\d{3,})\b", s)
        if m:
            out["receipt"] = m.group(1)

    m = re.search(r"\b(\d{2}-\d{2}-\d{2})\b", s)
    if m:
        out["date_ddmmyy"] = m.group(1)

    return out


def _normalize_unit(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def _derive_yy_mm_from_period(period: str) -> str:
    p = str(period or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})$", p)
    if not m:
        return ""
    year = int(m.group(1))
    mm = m.group(2)
    yy = year % 100
    return f"{yy:02d}_{mm}"


def _record_matches_yy_mm(record: Dict[str, Any], yy_mm: str) -> bool:
    y = str(yy_mm or "").strip()
    if not y:
        return True
    v1 = str(record.get("yy_mm") or "")
    v2 = str(record.get("หมายเหตุ") or "")
    return (y in v1) or (y in v2)


def _boost_score_with_hints(score: float, sheet_record: Dict[str, Any], hints: Dict[str, str]) -> float:
    s = float(score)
    if not hints:
        return s

    hint_unit = _normalize_unit(hints.get("unit"))
    if hint_unit:
        sheet_unit = _normalize_unit(sheet_record.get("ยูนิต") or sheet_record.get("unit"))
        if sheet_unit and sheet_unit == hint_unit:
            s += 0.15

    hint_receipt = str(hints.get("receipt") or "").strip()
    if hint_receipt:
        sheet_receipt = str(sheet_record.get("ใบเสร็จ") or "").strip()
        if sheet_receipt and hint_receipt in sheet_receipt:
            s += 0.1

    return min(1.2, s)


def _parse_amount(value: Any) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return None


def _pick_amount_from_record(record: Dict[str, Any]) -> Optional[float]:
    preferred_keys = ["จำนวนเงิน", "ยอดเงิน", "amount", "total", "Amount", "Total"]
    for k in preferred_keys:
        if k in record:
            v = _parse_amount(record.get(k))
            if v is not None:
                return v

    # Common mojibake headers show up when viewing UTF-8 in a non-UTF8 console.
    for k, v_raw in record.items():
        if not isinstance(k, str):
            continue
        k2 = k.replace(" ", "")
        if "จำนวนเงิน" in k2 or "ยอดเงิน" in k2:
            v = _parse_amount(v_raw)
            if v is not None:
                return v

    # Fallback: pick the largest parsable numeric amount in the row.
    best: Optional[float] = None
    for v in record.values():
        x = _parse_amount(v)
        if x is None:
            continue
        if best is None or x > best:
            best = x
    return best


async def _audidoc_invoke(tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if not MCP_AUDIDOC_BASE_URL:
        raise HTTPException(status_code=500, detail="MCP_AUDIDOC_BASE_URL_not_set")

    url = f"{MCP_AUDIDOC_BASE_URL}/invoke"
    payload = {"tool": tool, "arguments": arguments}
    async with httpx.AsyncClient(timeout=MCP_ACC_TIMEOUT_SECONDS, follow_redirects=True) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="audidoc_invalid_response")
    return data


class AccRefreshCacheArgs(BaseModel):
    force: bool = Field(default=False)
    income_url: str = Field(default=DEFAULT_SHEET_INCOME_URL)
    expense_url: str = Field(default=DEFAULT_SHEET_EXPENSE_URL)


class AccGetCacheArgs(BaseModel):
    include_records: bool = Field(default=True)


class AccQueryArgs(BaseModel):
    sheet: Literal["income", "expense", "both"] = Field(default="both")
    contains: str = Field(default="")
    receipt: str = Field(default="")
    pv: str = Field(default="")
    unit: str = Field(default="")
    yy_mm: str = Field(default="")
    limit: int = Field(default=50, ge=1, le=500)


class AccReconcilePdfsArgs(BaseModel):
    force_refresh_cache: bool = Field(default=False)
    sheet: Literal["income", "expense", "both"] = Field(default="both")
    paths: List[str] = Field(default_factory=list)
    auto_discover: bool = Field(default=True)
    period_filter: str = Field(default="")
    yy_mm_filter: str = Field(default="")
    amount_max_pages: int = Field(default=2, ge=1, le=10)
    amount_tolerance_abs: float = Field(default=1.0, ge=0)
    amount_tolerance_pct: float = Field(default=0.001, ge=0)
    max_candidates: int = Field(default=3, ge=1, le=10)


class AccReconcileReportArgs(AccReconcilePdfsArgs):
    top_n: int = Field(default=10, ge=1, le=50)
    include_unmatched_sheet_samples: int = Field(default=5, ge=0, le=30)
    include_reconcile: bool = Field(default=False)


def _fmt_money(n: Any) -> str:
    try:
        v = float(n)
    except Exception:
        return str(n)
    return f"{v:,.2f}"


def _reconcile_report_text(result: Dict[str, Any], *, top_n: int, include_unmatched_sheet_samples: int) -> str:
    filters = (result.get("filters") or {}) if isinstance(result, dict) else {}
    summary = (result.get("summary") or {}) if isinstance(result, dict) else {}
    pdfs = (result.get("pdfs") or []) if isinstance(result, dict) else []
    unmatched_sheet = (result.get("unmatched_sheet") or {}) if isinstance(result, dict) else {}

    lines: List[str] = []
    lines.append("รายงานตรวจยอด (PDF vs ชีท)")
    lines.append("")

    period = str(filters.get("period") or "").strip()
    yy_mm = str(filters.get("yy_mm") or "").strip()
    warning = str(filters.get("warning") or "").strip()
    if period or yy_mm or warning:
        lines.append("ตัวกรอง")
        if period:
            lines.append(f"- period: {period}")
        if yy_mm:
            lines.append(f"- yy_mm: {yy_mm}")
        if warning:
            lines.append(f"- warning: {warning}")
        lines.append("")

    pdf_count = int(summary.get("pdf_count") or 0)
    check_count = int(summary.get("check_count") or 0)
    matched = int(summary.get("matched_check_count") or 0)
    unmatched = int(summary.get("unmatched_check_count") or 0)
    lines.append("สรุป")
    lines.append(f"- PDFs: {pdf_count}")
    lines.append(f"- checks: {matched}/{check_count} matched")
    if unmatched:
        lines.append(f"- unmatched checks: {unmatched}")
    lines.append("")

    problems: List[Dict[str, Any]] = []
    for p in pdfs:
        if not isinstance(p, dict):
            continue
        path = str(p.get("path") or "")
        claims = p.get("claims") if isinstance(p.get("claims"), dict) else {}
        for chk in (p.get("checks") or []):
            if not isinstance(chk, dict):
                continue
            matches = chk.get("matches") or []
            if matches:
                continue
            amt = chk.get("amount")
            kind = str(chk.get("kind") or "")
            text = str(chk.get("text") or "").strip()
            problems.append(
                {
                    "path": path,
                    "period": str((claims or {}).get("period") or ""),
                    "doc_type": str((claims or {}).get("doc_type") or ""),
                    "kind": kind,
                    "amount": amt,
                    "text": text,
                }
            )

    if problems:
        lines.append(f"รายการที่หา match ไม่เจอ (top {min(top_n, len(problems))})")
        for i, it in enumerate(problems[:top_n], start=1):
            head = f"{i}. {_fmt_money(it.get('amount'))}"
            meta = ""
            if it.get("doc_type") or it.get("period"):
                meta = f" [{it.get('doc_type') or ''} {it.get('period') or ''}]".strip()
            lines.append(f"- {head}{meta} :: {it.get('path')}")
            if it.get("text"):
                t = str(it.get("text") or "")
                if len(t) > 140:
                    t = t[:140] + "…"
                lines.append(f"  {t}")
        lines.append("")
    else:
        lines.append("ไม่พบรายการที่หา match ไม่เจอ")
        lines.append("")

    inc_un = (unmatched_sheet.get("income") or []) if isinstance(unmatched_sheet, dict) else []
    exp_un = (unmatched_sheet.get("expense") or []) if isinstance(unmatched_sheet, dict) else []
    if isinstance(inc_un, list) and inc_un:
        lines.append(f"ชีทรายรับที่ยังไม่ถูก match: {len(inc_un)}")
        for it in inc_un[:include_unmatched_sheet_samples]:
            if not isinstance(it, dict):
                continue
            lines.append(f"- income[{it.get('sheet_index')}] amount={_fmt_money(it.get('amount'))}")
        lines.append("")
    if isinstance(exp_un, list) and exp_un:
        lines.append(f"ชีทรายจ่ายที่ยังไม่ถูก match: {len(exp_un)}")
        for it in exp_un[:include_unmatched_sheet_samples]:
            if not isinstance(it, dict):
                continue
            lines.append(f"- expense[{it.get('sheet_index')}] amount={_fmt_money(it.get('amount'))}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


class ChatArgs(BaseModel):
    message: str = Field(default="")


class AccQueryTextArgs(BaseModel):
    message: str = Field(default="")


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None


def _tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "acc_refresh_cache",
            "description": "Fetch published Google Sheets (income/expense) and cache as JSON snapshot on disk.",
            "inputSchema": AccRefreshCacheArgs.model_json_schema(),
        },
        {
            "name": "acc_get_cache",
            "description": "Read cached accounting snapshot from disk (optionally without full records).",
            "inputSchema": AccGetCacheArgs.model_json_schema(),
        },
        {
            "name": "acc_query",
            "description": "Query cached income/expense rows with simple text filters.",
            "inputSchema": AccQueryArgs.model_json_schema(),
        },
        {
            "name": "acc_query_text",
            "description": "Query cached sheets using a natural-ish message, returning deterministic text (table/sum/top) without LLM.",
            "inputSchema": AccQueryTextArgs.model_json_schema(),
        },
        {
            "name": "acc_reconcile_pdfs",
            "description": "Verify PDFs (via mcp-audidoc amount extraction) against cached sheet rows.",
            "inputSchema": AccReconcilePdfsArgs.model_json_schema(),
        },
        {
            "name": "acc_reconcile_report",
            "description": "Generate a human-readable report (Thai) on top of acc_reconcile_pdfs output.",
            "inputSchema": AccReconcileReportArgs.model_json_schema(),
        },
    ]


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    return JsonRpcResponse(id=id_value, error=JsonRpcError(code=code, message=message, data=data)).model_dump(
        exclude_none=True
    )


def _normalize(s: Any) -> str:
    return str(s or "").strip().lower()


def _normalize_unit_token(s: Any) -> str:
    # Normalize unit tokens so A43, A-43, a 43 all match.
    raw = str(s or "").strip().upper()
    raw = raw.replace(" ", "").replace("_", "").replace("/", "")
    raw = raw.replace("-", "")
    return raw


def _record_matches_query(r: Dict[str, Any], args: "AccQueryArgs") -> bool:
    q_contains = _normalize(args.contains)
    q_receipt = _normalize(args.receipt)
    q_pv = _normalize(args.pv)
    q_unit = _normalize_unit_token(args.unit)
    q_yy_mm = _normalize(args.yy_mm)

    if q_receipt:
        # Receipt may appear in ใบเสร็จ or other identifiers.
        receipt_val = _normalize(r.get("ใบเสร็จ"))
        if q_receipt not in receipt_val:
            # Some rows store IDs elsewhere; fall back to searching the row blob.
            blob_receipt = " ".join(_normalize(v) for v in r.values())
            if q_receipt not in blob_receipt:
                return False

    if q_pv:
        pv_val = _normalize(r.get("PV"))
        if q_pv not in pv_val:
            return False

    if q_unit:
        unit_val = _normalize_unit_token(r.get("ยูนิต"))
        if not unit_val:
            unit_val = _normalize_unit_token(r.get("unit"))
        if q_unit not in unit_val:
            return False

    if q_yy_mm:
        yy_mm_val = _normalize(r.get("yy_mm"))
        if not yy_mm_val:
            yy_mm_val = _normalize(r.get("หมายเหตุ"))
        if q_yy_mm not in yy_mm_val:
            return False

    if q_contains:
        blob = " ".join(_normalize(v) for v in r.values())
        if q_contains not in blob:
            return False

    return True


def _query_records(records: List[Dict[str, Any]], args: AccQueryArgs) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        if not _record_matches_query(r, args):
            continue
        out.append(r)
        if len(out) >= args.limit:
            break

    return out


app = FastAPI(title=APP_NAME, version=APP_VERSION)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "timestampMs": _utc_ms(),
    }


@app.get("/www/chat", response_class=HTMLResponse)
async def www_chat() -> str:
    return """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>mcp-acc chat</title>
    <style>
      body { font-family: \"Segoe UI\", system-ui, -apple-system, sans-serif; background: #0f1115; color: #e5e7eb; margin: 0; }
      .wrap { max-width: 980px; margin: 0 auto; padding: 18px; }
      .top { display:flex; gap:10px; align-items:center; margin-bottom: 12px; }
      .top a { color: #7dd3fc; text-decoration: none; }
      .top a:hover { text-decoration: underline; }
      h1 { margin: 0; font-size: 18px; flex: 1; }
      .log { background: #151922; border: 1px solid #262b36; border-radius: 12px; padding: 12px; height: 60vh; overflow: auto; white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace; font-size: 12.5px; }
      .bar { display:flex; gap:10px; margin-top: 12px; }
      input { flex:1; background:#0b0d12; border:1px solid #262b36; color:#e5e7eb; border-radius: 10px; padding: 10px 12px; }
      button { background:#2563eb; border:none; color:white; border-radius: 10px; padding: 10px 14px; cursor:pointer; }
      button.secondary { background:#374151; }
      .hint { opacity:.8; font-size: 12px; margin-top: 10px; }
      code { background: #0b0d12; padding: 2px 6px; border-radius: 8px; }
    </style>
  </head>
  <body>
    <div class=\"wrap\">
      <div class=\"top\">
        <h1>mcp-acc · chat (LLM)</h1>
        <a href=\"/tools\">tools</a>
        <a href=\"/www/chat/examples\">examples</a>
      </div>
      <div id=\"log\" class=\"log\"></div>
      <div class=\"bar\">
        <input id=\"msg\" placeholder=\"Ask about income/expense, yy_mm (e.g. 68_12), unit (A-43), receipt...\" autocomplete=\"off\" />
        <button id=\"send\">Send</button>
        <button id=\"clear\" class=\"secondary\">Clear</button>
      </div>
      <div class=\"hint\">
        Backed by an OpenAI-compatible LLM. Tip: include <code>yy_mm</code> like <code>68_12</code>, <code>unit</code> like <code>A-43</code>, or <code>receipt</code> like <code>2029/1465</code> to narrow results.
      </div>
    </div>

    <script>
      const log = document.getElementById('log');
      const msg = document.getElementById('msg');
      const send = document.getElementById('send');
      const clear = document.getElementById('clear');

      function write(role, text) {
        const prefix = role === 'you' ? '> ' : '';
        log.textContent += `${prefix}${text}\n\n`;
        log.scrollTop = log.scrollHeight;
      }

      async function callChat(message) {
        const r = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ message })
        });
        const data = await r.json();
        if (!r.ok) {
          throw new Error(data?.detail || data?.error || 'chat_failed');
        }
        return data;
      }

      async function callChatStream(message, onToken) {
        const r = await fetch('/api/chat/stream', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ message })
        });
        if (!r.ok) {
          let detail = '';
          try {
            const data = await r.json();
            detail = data?.detail || data?.error || '';
          } catch {}
          throw new Error(detail || 'chat_stream_failed');
        }
        const reader = r.body.getReader();
        const decoder = new TextDecoder('utf-8');
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          if (chunk) onToken(chunk);
        }
      }

      async function doSend() {
        const text = (msg.value || '').trim();
        if (!text) return;
        msg.value = '';
        write('you', text);
        try {
          // Prefer streaming (Glama/OpenAI-compatible stream). Fallback to JSON.
          log.textContent += `bot: `;
          log.scrollTop = log.scrollHeight;
          let streamed = false;
          try {
            await callChatStream(text, (tok) => {
              streamed = true;
              log.textContent += tok;
              log.scrollTop = log.scrollHeight;
            });
          } catch (e) {
            if (!streamed) {
              const out = await callChat(text);
              log.textContent += (out.reply || JSON.stringify(out));
            } else {
              log.textContent += `\n(error: ${e.message})`;
            }
          }
          log.textContent += `\n\n`;
          log.scrollTop = log.scrollHeight;
        } catch (e) {
          write('bot', `error: ${e.message}`);
        }
      }

      send.addEventListener('click', doSend);
      clear.addEventListener('click', () => { log.textContent = ''; });
      msg.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doSend();
      });

      (async () => {
        write('bot', 'Ask me about income/expense. Try: "สรุปรายรับเดือน 68_12"');
      })();
    </script>
  </body>
</html>"""


@app.get("/www/chat/examples", response_class=HTMLResponse)
async def www_chat_examples() -> str:
    examples = [
        "สรุปรายรับทั้งหมด และแยกตาม yy_mm",
        "สรุปยอดรายจ่าย yy_mm 67_01",
        "ยอดรวมรายจ่าย yy_mm 67_01",
        "ท็อป 5 รายจ่าย yy_mm 67_01",
        "5 อันดับ รายจ่าย yy_mm 67_01",
        "รายจ่ายมากที่สุด yy_mm 67_01",
        "เดือน 68_12 ยูนิต A-43 มีรายรับอะไรบ้าง",
        "หาใบเสร็จ NAC2567.001",
        "หาใบเสร็จ 2029/1465 อยู่ในรายรับหรือรายจ่าย? จำนวนเท่าไร",
        "ช่วยสรุป mismatch ที่สำคัญที่สุด 10 อันดับ (PDF vs ชีท)",
        "period 2568-06 จาก PDF มีรายการไหนที่ match กับชีทไม่ได้",
    ]
    items = "\n".join(f"<li><code>{e}</code></li>" for e in examples)
    return f"""<!doctype html>
<html lang=\"en\"><head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>mcp-acc chat examples</title>
  <style>
    body {{ font-family: \"Segoe UI\", system-ui, -apple-system, sans-serif; background: #0f1115; color: #e5e7eb; margin: 0; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 18px; }}
    a {{ color: #7dd3fc; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{ background: #0b0d12; padding: 2px 6px; border-radius: 8px; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div style=\"display:flex; gap:10px; align-items:center;\">
      <h1 style=\"margin:0; font-size:18px; flex:1;\">mcp-acc · chat examples</h1>
      <a href=\"/www/chat\">back</a>
    </div>
    <ol>{items}</ol>
  </div>
</body></html>"""


@app.post("/api/chat")
async def api_chat(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        args = ChatArgs.model_validate(payload or {})
        msg = (args.message or "").strip()
        if not msg:
            raise HTTPException(status_code=400, detail="missing_message")

        cache = _read_json_file(MCP_ACC_DATA_PATH)
        if not cache:
            cache = await _refresh_cache(income_url=DEFAULT_SHEET_INCOME_URL, expense_url=DEFAULT_SHEET_EXPENSE_URL)

        mode, qargs, top_n = _parse_query_intent_from_message(msg)
        if qargs is not None and mode != "none":
            reply_txt = _render_query_intent(cache, mode, qargs, top_n)
            return {
                "reply": reply_txt,
                "meta": {
                    "mode": f"query:{mode}",
                    "query": qargs.model_dump(),
                    "top_n": top_n,
                },
            }

        # Keep context small to avoid overloading the LLM gateway. The assistant can ask follow-up questions.
        context = _build_llm_context(cache, msg, max_rows=3)

        system = (
            "You are an accounting assistant for a housing/HOA accounting sheet. "
            "Answer in Thai. Be precise with numbers. "
            "If the user asks for a list, return a compact table-like output. "
            "If the question is ambiguous, ask a clarifying question. "
            "Use only the provided DATA JSON; do not invent values."
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "system", "content": f"DATA_JSON={_safe_json_dumps(context)}"},
            {"role": "user", "content": msg},
        ]

        try:
            reply = await _llm_chat(messages)
        except httpx.HTTPError as exc:
            msg_txt = getattr(exc, "message", None) or ""
            detail = msg_txt.strip() or repr(exc)
            logger.exception("llm_call_failed: %s", detail)
            raise HTTPException(status_code=502, detail=detail) from exc

        if not reply:
            reply = "(no reply)"
        return {
            "reply": reply,
            "meta": {
                "model": MCP_ACC_LLM_MODEL,
                "base_url": MCP_ACC_LLM_BASE_URL,
                "filters": context.get("filters"),
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/chat/stream")
async def api_chat_stream(payload: Dict[str, Any] = Body(...)) -> StreamingResponse:
    try:
        args = ChatArgs.model_validate(payload or {})
        msg = (args.message or "").strip()
        if not msg:
            raise HTTPException(status_code=400, detail="missing_message")

        cache = _read_json_file(MCP_ACC_DATA_PATH)
        if not cache:
            cache = await _refresh_cache(income_url=DEFAULT_SHEET_INCOME_URL, expense_url=DEFAULT_SHEET_EXPENSE_URL)

        mode, qargs, top_n = _parse_query_intent_from_message(msg)
        if qargs is not None and mode != "none":
            reply_txt = _render_query_intent(cache, mode, qargs, top_n)

            async def gen_query():
                yield reply_txt

            return StreamingResponse(gen_query(), media_type="text/plain; charset=utf-8")

        context = _build_llm_context(cache, msg, max_rows=3)

        system = (
            "You are an accounting assistant for a housing/HOA accounting sheet. "
            "Answer in Thai. Be precise with numbers. "
            "If the user asks for a list, return a compact table-like output. "
            "If the question is ambiguous, ask a clarifying question. "
            "Use only the provided DATA JSON; do not invent values."
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "system", "content": f"DATA_JSON={_safe_json_dumps(context)}"},
            {"role": "user", "content": msg},
        ]

        async def gen():
            try:
                async for chunk in _llm_chat_stream(messages):
                    yield chunk
            except httpx.HTTPError as exc:
                msg_txt = getattr(exc, "message", None) or ""
                detail = msg_txt.strip() or repr(exc)
                logger.exception("llm_stream_failed: %s", detail)
                yield f"\n(error: {detail})\n"
            except Exception as exc:
                logger.exception("llm_stream_failed: %s", exc)
                yield f"\n(error: {str(exc)})\n"

        return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/.well-known/mcp.json")
async def well_known() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "Accounting MCP provider: cache Google Sheets and reconcile with documents.",
        "capabilities": {"tools": _tool_definitions()},
    }


@app.get("/tools")
async def tools() -> Dict[str, Any]:
    return {"tools": _tool_definitions()}


@app.post("/invoke")
async def invoke(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    tool = (payload or {}).get("tool")
    args_raw = (payload or {}).get("arguments") or (payload or {}).get("args") or {}

    if tool == "acc_refresh_cache":
        args = AccRefreshCacheArgs.model_validate(args_raw or {})
        existing = _read_json_file(MCP_ACC_DATA_PATH)
        if existing and _cache_is_fresh(existing) and not args.force:
            return {"tool": tool, "result": existing}
        out = await _refresh_cache(income_url=args.income_url, expense_url=args.expense_url)
        return {"tool": tool, "result": out}

    if tool == "acc_get_cache":
        args = AccGetCacheArgs.model_validate(args_raw or {})
        existing = _read_json_file(MCP_ACC_DATA_PATH)
        if not existing:
            raise HTTPException(status_code=404, detail="cache_not_found")
        if not args.include_records:
            thin = dict(existing)
            if isinstance(thin.get("sheets"), dict):
                for k in list((thin.get("sheets") or {}).keys()):
                    if isinstance(thin["sheets"].get(k), dict):
                        thin["sheets"][k] = {
                            "headers": thin["sheets"][k].get("headers") or [],
                            "records": [],
                            "count": len((existing.get("sheets", {}).get(k, {}) or {}).get("records") or []),
                        }
            return {"tool": tool, "result": thin}
        return {"tool": tool, "result": existing}

    if tool == "acc_query":
        args = AccQueryArgs.model_validate(args_raw or {})
        existing = _read_json_file(MCP_ACC_DATA_PATH)
        if not existing:
            raise HTTPException(status_code=404, detail="cache_not_found")
        sheets = (existing.get("sheets") or {})

        results: Dict[str, Any] = {"income": [], "expense": []}
        if args.sheet in ("income", "both"):
            income_records = ((sheets.get("income") or {}).get("records") or [])
            results["income"] = _query_records(income_records, args)
        if args.sheet in ("expense", "both"):
            expense_records = ((sheets.get("expense") or {}).get("records") or [])
            results["expense"] = _query_records(expense_records, args)

        return {"tool": tool, "result": {"ok": True, "query": args.model_dump(), "results": results}}

    if tool == "acc_query_text":
        args = AccQueryTextArgs.model_validate(args_raw or {})
        msg = (args.message or "").strip()
        if not msg:
            raise HTTPException(status_code=400, detail="missing_message")
        existing = _read_json_file(MCP_ACC_DATA_PATH)
        if not existing:
            raise HTTPException(status_code=404, detail="cache_not_found")

        mode, qargs, top_n = _parse_query_intent_from_message(msg)
        if qargs is None or mode == "none":
            return {
                "tool": tool,
                "result": {
                    "ok": True,
                    "mode": "none",
                    "text": "(no deterministic query intent detected)",
                },
            }

        text = _render_query_intent(existing, mode, qargs, top_n)
        return {
            "tool": tool,
            "result": {
                "ok": True,
                "mode": mode,
                "query": qargs.model_dump(),
                "top_n": top_n,
                "text": text,
            },
        }

    if tool == "acc_reconcile_pdfs":
        args = AccReconcilePdfsArgs.model_validate(args_raw or {})

        cache = _read_json_file(MCP_ACC_DATA_PATH)
        if not cache or args.force_refresh_cache:
            cache = await _refresh_cache(income_url=DEFAULT_SHEET_INCOME_URL, expense_url=DEFAULT_SHEET_EXPENSE_URL)

        sheets = (cache.get("sheets") or {}) if isinstance(cache, dict) else {}
        income_records = ((sheets.get("income") or {}).get("records") or [])
        expense_records = ((sheets.get("expense") or {}).get("records") or [])

        income_records_all = list(income_records)
        expense_records_all = list(expense_records)

        yy_mm_effective = (args.yy_mm_filter or "").strip()
        if not yy_mm_effective and (args.period_filter or "").strip():
            yy_mm_effective = _derive_yy_mm_from_period(args.period_filter)

        filter_warning = ""
        if yy_mm_effective:
            income_records = [r for r in income_records if isinstance(r, dict) and _record_matches_yy_mm(r, yy_mm_effective)]
            expense_records = [r for r in expense_records if isinstance(r, dict) and _record_matches_yy_mm(r, yy_mm_effective)]

        income_index = _build_amount_index(income_records) if args.sheet in ("income", "both") else []
        expense_index = _build_amount_index(expense_records) if args.sheet in ("expense", "both") else []

        if yy_mm_effective and (not income_index and not expense_index):
            filter_warning = "yy_mm_filter_yielded_zero_amount_candidates"
            income_index = _build_amount_index(income_records_all) if args.sheet in ("income", "both") else []
            expense_index = _build_amount_index(expense_records_all) if args.sheet in ("expense", "both") else []

        audidoc_args: Dict[str, Any] = {
            "paths": args.paths,
            "auto_discover": bool(args.auto_discover),
            "extract_amounts": True,
            "amount_max_pages": int(args.amount_max_pages),
            "amount_tolerance_abs": float(args.amount_tolerance_abs),
            "amount_tolerance_pct": float(args.amount_tolerance_pct),
        }
        aud = await _audidoc_invoke("audit_cross_checks", audidoc_args)
        aud_result = (aud.get("result") if isinstance(aud, dict) else None) or aud

        documents = []
        if isinstance(aud_result, dict):
            documents = aud_result.get("documents") or aud_result.get("results") or aud_result.get("items") or []
        elif isinstance(aud_result, list):
            documents = aud_result

        pdf_reports: List[Dict[str, Any]] = []
        matched_sheet_keys: Dict[str, bool] = {}

        period_filter = (args.period_filter or "").strip()
        for d in (documents or []):
            if not isinstance(d, dict):
                continue
            path = str(d.get("path") or "")
            claims = d.get("claims") if isinstance(d.get("claims"), dict) else {}

            if period_filter:
                if str(claims.get("period") or "").strip() != period_filter:
                    continue

            checks: List[Dict[str, Any]] = []

            total_amount = _parse_amount(claims.get("amount_total"))
            if total_amount is None:
                ae = claims.get("amount_evidence") if isinstance(claims.get("amount_evidence"), dict) else {}
                total_amount = _parse_amount(ae.get("value"))
            if total_amount is not None:
                checks.append({"kind": "total", "amount": float(total_amount), "text": ""})

            income_items_raw = claims.get("income_items")
            if isinstance(income_items_raw, list):
                for it in income_items_raw:
                    if not isinstance(it, dict):
                        continue
                    amt = _parse_amount(it.get("amount"))
                    if amt is None:
                        continue
                    checks.append({"kind": "income_item", "amount": float(amt), "text": str(it.get("text") or "")})

            if not checks:
                pdf_reports.append({"path": path, "checks": [], "note": "no_amount"})
                continue

            rendered_checks: List[Dict[str, Any]] = []
            for chk in checks:
                chk_amount = float(chk["amount"])
                chk_text = str(chk.get("text") or "")
                hints = _extract_hints_from_text(chk_text)

                candidates: List[Dict[str, Any]] = []

                # income_items should primarily match income sheet rows
                if args.sheet in ("income", "both") and chk.get("kind") in ("income_item", "total"):
                    base = _best_sheet_matches(
                        chk_amount,
                        income_index,
                        abs_tol=args.amount_tolerance_abs,
                        pct_tol=args.amount_tolerance_pct,
                        limit=args.max_candidates,
                    )
                    for c in base:
                        boosted = _boost_score_with_hints(float(c.get("score") or 0.0), c.get("sheet_record") or {}, hints)
                        candidates.append(dict(c, sheet="income", score=boosted, hints=hints))

                # expense matching should use totals (expense PDFs are usually one total)
                if args.sheet in ("expense", "both") and chk.get("kind") == "total":
                    base = _best_sheet_matches(
                        chk_amount,
                        expense_index,
                        abs_tol=args.amount_tolerance_abs,
                        pct_tol=args.amount_tolerance_pct,
                        limit=args.max_candidates,
                    )
                    for c in base:
                        candidates.append(dict(c, sheet="expense", hints=hints))

                candidates.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
                candidates = candidates[: args.max_candidates]
                if candidates:
                    top = candidates[0]
                    matched_sheet_keys[f"{top.get('sheet')}:{top.get('sheet_index')}"] = True

                rendered_checks.append(
                    {
                        "kind": chk.get("kind"),
                        "amount": chk_amount,
                        "text": chk_text,
                        "hints": hints,
                        "matches": candidates,
                    }
                )

            pdf_reports.append(
                {
                    "path": path,
                    "claims": {
                        "project": claims.get("project"),
                        "period": claims.get("period"),
                        "doc_type": claims.get("doc_type"),
                    },
                    "checks": rendered_checks,
                }
            )

        unmatched_sheet: Dict[str, Any] = {"income": [], "expense": []}
        if args.sheet in ("income", "both"):
            for it in income_index:
                key = f"income:{it['index']}"
                if key not in matched_sheet_keys:
                    unmatched_sheet["income"].append({"sheet_index": it["index"], "amount": it["amount"], "record": it["record"]})
        if args.sheet in ("expense", "both"):
            for it in expense_index:
                key = f"expense:{it['index']}"
                if key not in matched_sheet_keys:
                    unmatched_sheet["expense"].append({"sheet_index": it["index"], "amount": it["amount"], "record": it["record"]})

        total_checks = 0
        matched_checks = 0
        for p in pdf_reports:
            for chk in (p.get("checks") or []):
                total_checks += 1
                if (chk.get("matches") or []):
                    matched_checks += 1

        return {
            "tool": tool,
            "result": {
                "ok": True,
                "audidoc": {"base_url": MCP_AUDIDOC_BASE_URL},
                "cache": {"fetchedAtMs": (cache or {}).get("fetchedAtMs") if isinstance(cache, dict) else None},
                "filters": {
                    "period": period_filter,
                    "yy_mm": yy_mm_effective,
                    "warning": filter_warning,
                },
                "summary": {
                    "pdf_count": len(pdf_reports),
                    "check_count": total_checks,
                    "matched_check_count": matched_checks,
                    "unmatched_check_count": max(0, total_checks - matched_checks),
                    "income_sheet_candidates": len(income_index),
                    "expense_sheet_candidates": len(expense_index),
                },
                "pdfs": pdf_reports,
                "unmatched_sheet": unmatched_sheet,
            },
        }

    if tool == "acc_reconcile_report":
        args = AccReconcileReportArgs.model_validate(args_raw or {})
        pdf_args = AccReconcilePdfsArgs.model_validate(args.model_dump())
        out = await invoke({"tool": "acc_reconcile_pdfs", "arguments": pdf_args.model_dump()})
        res = (out.get("result") if isinstance(out, dict) else None) or {}
        report = _reconcile_report_text(
            res,
            top_n=int(args.top_n),
            include_unmatched_sheet_samples=int(args.include_unmatched_sheet_samples),
        )
        result_obj: Dict[str, Any] = {"ok": True, "report": report}
        if bool(args.include_reconcile):
            result_obj["reconcile"] = res
        return {"tool": tool, "result": result_obj}

    raise HTTPException(status_code=404, detail=f"unknown tool '{tool}'")


@app.post("/mcp")
async def mcp(payload: Dict[str, Any] = Body(...)) -> Any:
    request = JsonRpcRequest.model_validate(payload or {})
    if request.id is None:
        return None

    method = (request.method or "").strip()
    params = request.params or {}

    if method == "initialize":
        return JsonRpcResponse(
            id=request.id,
            result={
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                "capabilities": {"tools": {}},
            },
        ).model_dump(exclude_none=True)

    if method == "tools/list":
        return JsonRpcResponse(id=request.id, result={"tools": _tool_definitions()}).model_dump(exclude_none=True)

    if method == "tools/call":
        name = str((params or {}).get("name") or "").strip()
        args = (params or {}).get("arguments") or {}
        try:
            out = await invoke({"tool": name, "arguments": args})
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": json.dumps(out.get("result"), ensure_ascii=False)}]},
            ).model_dump(exclude_none=True)
        except HTTPException as exc:
            return _jsonrpc_error(request.id, int(exc.status_code), str(exc.detail))
        except Exception as exc:
            return _jsonrpc_error(request.id, -32000, "internal_error", data=str(exc))

    return _jsonrpc_error(request.id, -32601, "method_not_found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
