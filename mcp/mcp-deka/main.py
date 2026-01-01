from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel, Field


APP_NAME = "mcp-deka"
APP_VERSION = "0.1.0"

PORT = int(os.getenv("PORT", "8270"))

MCP_PLAYWRIGHT_BASE_URL = (os.getenv("MCP_PLAYWRIGHT_BASE_URL") or "http://mcp-playwright:8260").rstrip("/")
MCP_DEKA_DB_PATH = os.getenv("MCP_DEKA_DB_PATH", "/data/sqlite/mcp-deka.sqlite")
HTTP_TIMEOUT_SECONDS = float(os.getenv("MCP_DEKA_TIMEOUT_SECONDS", "120"))


def _utc_ts() -> int:
    return int(time.time())


def _ensure_db() -> None:
    os.makedirs(os.path.dirname(MCP_DEKA_DB_PATH), exist_ok=True)
    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
              run_id TEXT PRIMARY KEY,
              created_at INTEGER NOT NULL,
              label TEXT,
              meta_json TEXT,
              html TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discovered (
              doc_id TEXT PRIMARY KEY,
              first_seen_at INTEGER NOT NULL,
              last_seen_at INTEGER NOT NULL,
              source_year INTEGER,
              source_page INTEGER,
              source_url TEXT,
              meta_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hydrated_docs (
              doc_id TEXT PRIMARY KEY,
              hydrated_at INTEGER NOT NULL,
              run_id TEXT NOT NULL,
              source_year INTEGER,
              short_text TEXT,
              long_text TEXT,
              remark_text TEXT,
              meta_json TEXT
            )
            """
        )
        conn.commit()


async def _call_playwright_run_flow(actions: List[Dict[str, Any]], *, name: str, browser: Optional[str], timeout_ms: Optional[int]) -> Dict[str, Any]:
    timeout_s = float(HTTP_TIMEOUT_SECONDS)
    if timeout_ms is not None:
        try:
            timeout_s = max(timeout_s, float(timeout_ms) / 1000.0 + 30.0)
        except Exception:
            timeout_s = float(HTTP_TIMEOUT_SECONDS)

    timeout = httpx.Timeout(timeout=timeout_s, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{MCP_PLAYWRIGHT_BASE_URL}/invoke",
            json={
                "tool": "run_flow",
                "arguments": {
                    "name": name,
                    "browser": browser,
                    "timeout": timeout_ms,
                    "actions": actions,
                },
            },
        )

    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=r.text or f"playwright_http_{r.status_code}")

    data = r.json() or {}
    if isinstance(data, dict) and data.get("error"):
        raise HTTPException(status_code=502, detail=data.get("error"))

    outputs = (data or {}).get("outputs") or []
    texts = [c.get("text", "") for c in outputs if isinstance(c, dict) and c.get("type") == "text"]

    return {
        "raw": data,
        "content_texts": texts,
    }


def _extract_first_html(texts: List[str]) -> Optional[str]:
    # capture_html with inline=true returns HTML as a text output.
    for t in texts:
        if isinstance(t, str) and "<html" in t.lower():
            return t
    # Sometimes page.content() may start with doctype.
    for t in texts:
        if isinstance(t, str) and "<!doctype" in t.lower():
            return t
    return None


def _extract_html_texts(texts: List[str]) -> List[str]:
    out: List[str] = []
    for t in texts or []:
        if not isinstance(t, str):
            continue
        low = t.lower()
        if "<html" in low or "<!doctype" in low:
            out.append(t)
    return out


def _tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "run_search_flow",
            "description": "Run a Playwright flow (via mcp-playwright) and return captured HTML (inline capture_html).",
            "inputSchema": RunSearchFlowArgs.model_json_schema(),
        },
        {
            "name": "get_run",
            "description": "Fetch a stored run (meta + HTML) by run_id.",
            "inputSchema": GetRunArgs.model_json_schema(),
        },
        {
            "name": "list_discovered",
            "description": "List discovered doc_ids from sqlite (optionally filtered by source_year).",
            "inputSchema": ListDiscoveredArgs.model_json_schema(),
        },
        {
            "name": "hydrate_doc",
            "description": "Fetch a specific discovered doc_id page, open its short-view modal (best-effort), capture HTML, and store it as a run.",
            "inputSchema": HydrateDocArgs.model_json_schema(),
        },
        {
            "name": "discover_basic_year",
            "description": "Run DEKA basic search for a year range (and optional keyword) and upsert discovered doc_ids. Uses Playwright and can optionally fetch multiple result pages in one session.",
            "inputSchema": DiscoverBasicYearArgs.model_json_schema(),
        },
        {
            "name": "parse_search_html",
            "description": "Parse a DEKA search-result HTML page to extract doc_ids + pagination info; upsert into sqlite.",
            "inputSchema": ParseSearchHtmlArgs.model_json_schema(),
        },
        {
            "name": "parse_run",
            "description": "Parse a previously stored run (from run_search_flow) and upsert doc_ids + pagination.",
            "inputSchema": ParseRunArgs.model_json_schema(),
        },
        {
            "name": "parse_hydrated_run",
            "description": "Parse a stored hydration run HTML to extract short/long/remark text and upsert into hydrated_docs.",
            "inputSchema": ParseHydratedRunArgs.model_json_schema(),
        },
        {
            "name": "get_hydrated_doc",
            "description": "Fetch a hydrated doc text (short/long/remark) by doc_id.",
            "inputSchema": GetHydratedDocArgs.model_json_schema(),
        },
        {
            "name": "extract_links",
            "description": "Extract links from an HTML blob (helper for building doc_id/detail_url parsing).",
            "inputSchema": ExtractLinksArgs.model_json_schema(),
        },
        {
            "name": "status",
            "description": "Return basic DB/run stats.",
            "inputSchema": StatusArgs.model_json_schema(),
        },
    ]


class RunSearchFlowArgs(BaseModel):
    label: str = Field(default="deka_search")
    browser: Optional[str] = None
    timeout_ms: Optional[int] = Field(default=30000, alias="timeoutMs")
    actions: List[Dict[str, Any]]


class GetRunArgs(BaseModel):
    run_id: str = Field(..., alias="runId")
    include_html: bool = Field(default=True, alias="includeHtml")
    max_chars: int = Field(default=200000, alias="maxChars", ge=1000, le=2000000)


class ListDiscoveredArgs(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    source_year: Optional[int] = Field(default=None, alias="sourceYear")


class HydrateDocArgs(BaseModel):
    doc_id: str = Field(..., alias="docId")
    base_url: str = Field(default="https://deka.supremecourt.or.th/", alias="baseUrl")
    start_year: Optional[int] = Field(default=None, alias="startYear", description="Optional: year start to re-run the search before hydrating")
    end_year: Optional[int] = Field(default=None, alias="endYear", description="Optional: year end to re-run the search before hydrating")
    keyword: Optional[str] = Field(default=None, description="Optional: keyword to re-run the search before hydrating")
    browser: Optional[str] = None
    timeout_ms: Optional[int] = Field(default=90000, alias="timeoutMs")
    click_short: bool = Field(default=True, alias="clickShort")
    max_chars: int = Field(default=450000, alias="maxChars", ge=10000, le=2000000)


class DiscoverBasicYearArgs(BaseModel):
    start_year: int = Field(..., alias="startYear", description="ปี พ.ศ. เริ่มต้น")
    end_year: int = Field(..., alias="endYear", description="ปี พ.ศ. สิ้นสุด")
    keyword: Optional[str] = Field(default=None, description="คำค้น (optional)")
    max_pages: int = Field(default=1, alias="maxPages", ge=1, le=200)
    base_url: str = Field(default="https://deka.supremecourt.or.th/", alias="baseUrl")
    browser: Optional[str] = None
    timeout_ms: Optional[int] = Field(default=45000, alias="timeoutMs")


class ExtractLinksArgs(BaseModel):
    html: str
    base_url: Optional[str] = Field(default=None, alias="baseUrl")
    selector: Optional[str] = None
    limit: int = 50


class ParseSearchHtmlArgs(BaseModel):
    html: str
    source_year: Optional[int] = Field(default=None, alias="sourceYear")
    source_page: Optional[int] = Field(default=None, alias="sourcePage")
    source_url: Optional[str] = Field(default=None, alias="sourceUrl")


class ParseRunArgs(BaseModel):
    run_id: str = Field(..., alias="runId")
    source_year: Optional[int] = Field(default=None, alias="sourceYear")
    source_page: Optional[int] = Field(default=None, alias="sourcePage")
    source_url: Optional[str] = Field(default=None, alias="sourceUrl")


class ParseHydratedRunArgs(BaseModel):
    run_id: str = Field(..., alias="runId")
    doc_id: Optional[str] = Field(default=None, alias="docId")


class GetHydratedDocArgs(BaseModel):
    doc_id: str = Field(..., alias="docId")
    max_chars: int = Field(default=200000, alias="maxChars", ge=1000, le=2000000)


class StatusArgs(BaseModel):
    limit: int = 5


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcRequest(BaseModel):
    jsonrpc: Optional[str] = "2.0"
    id: Optional[Any] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Any
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None


app = FastAPI(title=APP_NAME, version=APP_VERSION)


@app.get("/health")
def health() -> Dict[str, Any]:
    _ensure_db()
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "playwright": MCP_PLAYWRIGHT_BASE_URL,
        "db": MCP_DEKA_DB_PATH,
        "ts": _utc_ts(),
    }


@app.get("/.well-known/mcp.json")
def well_known() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "DEKA ingestion helper that uses mcp-playwright for browser automation.",
        "capabilities": {"tools": _tool_definitions()},
    }


@app.post("/invoke")
async def invoke(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    tool = (payload or {}).get("tool")
    args_raw = (payload or {}).get("arguments") or (payload or {}).get("args") or {}

    if tool == "run_search_flow":
        args = RunSearchFlowArgs(**(args_raw or {}))
        return {"tool": tool, "result": await _handle_run_search_flow(args)}

    if tool == "get_run":
        args = GetRunArgs(**(args_raw or {}))
        return {"tool": tool, "result": _handle_get_run(args)}

    if tool == "list_discovered":
        args = ListDiscoveredArgs(**(args_raw or {}))
        return {"tool": tool, "result": _handle_list_discovered(args)}

    if tool == "hydrate_doc":
        args = HydrateDocArgs(**(args_raw or {}))
        return {"tool": tool, "result": await _handle_hydrate_doc(args)}

    if tool == "discover_basic_year":
        args = DiscoverBasicYearArgs(**(args_raw or {}))
        return {"tool": tool, "result": await _handle_discover_basic_year(args)}

    if tool == "extract_links":
        args = ExtractLinksArgs(**(args_raw or {}))
        return {"tool": tool, "result": _handle_extract_links(args)}

    if tool == "parse_search_html":
        args = ParseSearchHtmlArgs(**(args_raw or {}))
        return {"tool": tool, "result": _handle_parse_search_html(args)}

    if tool == "parse_run":
        args = ParseRunArgs(**(args_raw or {}))
        return {"tool": tool, "result": _handle_parse_run(args)}

    if tool == "parse_hydrated_run":
        args = ParseHydratedRunArgs(**(args_raw or {}))
        return {"tool": tool, "result": _handle_parse_hydrated_run(args)}

    if tool == "get_hydrated_doc":
        args = GetHydratedDocArgs(**(args_raw or {}))
        return {"tool": tool, "result": _handle_get_hydrated_doc(args)}

    if tool == "status":
        args = StatusArgs(**(args_raw or {}))
        return {"tool": tool, "result": _handle_status(args)}

    raise HTTPException(status_code=404, detail=f"unknown tool '{tool}'")


async def _handle_run_search_flow(args: RunSearchFlowArgs) -> Dict[str, Any]:
    _ensure_db()

    # Ensure the flow ends with a capture_html inline step so we can return HTML.
    actions = list(args.actions or [])
    if not actions or str(actions[-1].get("type", "")).lower() != "capture_html":
        actions.append(
            {
                "type": "capture_html",
                "inline": True,
                "maxChars": 500000,
                "description": "Captured HTML",
            }
        )
    else:
        actions[-1]["inline"] = True
        actions[-1].setdefault("maxChars", 500000)

    out = await _call_playwright_run_flow(actions, name=args.label, browser=args.browser, timeout_ms=args.timeout_ms)
    html = _extract_first_html(out.get("content_texts") or [])

    run_id = str(uuid.uuid4())
    meta = {
        "label": args.label,
        "browser": args.browser,
        "timeout_ms": args.timeout_ms,
        "actions_count": len(actions),
    }

    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO runs(run_id, created_at, label, meta_json, html) VALUES(?,?,?,?,?)",
            (run_id, _utc_ts(), args.label, json.dumps(meta, ensure_ascii=False), html),
        )
        conn.commit()

    return {
        "run_id": run_id,
        "html_len": len(html or ""),
        "meta": meta,
        "html": html,
    }


async def _handle_discover_basic_year(args: DiscoverBasicYearArgs) -> Dict[str, Any]:
    _ensure_db()

    if args.start_year > args.end_year:
        raise HTTPException(status_code=400, detail="startYear must be <= endYear")

    base_url = (args.base_url or "http://deka.supremecourt.or.th/").strip()
    if not base_url:
        base_url = "http://deka.supremecourt.or.th/"
    if not base_url.endswith('/'):
        base_url += '/'

    search_url = base_url

    max_pages = max(1, min(int(args.max_pages), 200))

    actions: List[Dict[str, Any]] = [
        {"type": "goto", "url": search_url, "waitUntil": "networkidle"},
        {"type": "delay", "ms": 4000},
        {
            "type": "capture_html",
            "inline": True,
            "maxChars": 200000,
            "description": "landing_search_html"
        },
        {
            "type": "wait_for_selector",
            "selector": "#search_deka_start_year",
            "state": "attached",
            "timeout": 90000
        },
        {
            "type": "fill",
            "selector": "#search_deka_start_year",
            "value": str(args.start_year)
        },
        {
            "type": "fill",
            "selector": "#search_deka_end_year",
            "value": str(args.end_year)
        },
    ]

    if args.keyword is not None and str(args.keyword).strip():
        actions.append({
            "type": "fill",
            "selector": "#search_word",
            "value": str(args.keyword).strip()
        })

    # Submit (JS runs /api/verify/search then submits form)
    actions.extend(
        [
            {"type": "click", "selector": "#submit_search_deka"},
            {"type": "wait_for_selector", "selector": "#pagination", "state": "attached", "timeout": 60000},
            {
                "type": "capture_html",
                "inline": True,
                "maxChars": 500000,
                "description": f"results_page_1_{args.start_year}_{args.end_year}",
            },
        ]
    )

    # Attempt to visit additional pages in the SAME session.
    # The site uses /search/index/<page> links; this usually relies on server session, so it must be same browser context.
    for page in range(2, max_pages + 1):
        actions.extend(
            [
                {"type": "goto", "url": f"{base_url}search/index/{page}", "waitUntil": "domcontentloaded"},
                {"type": "wait_for_selector", "selector": "#pagination", "state": "attached", "timeout": 60000},
                {
                    "type": "capture_html",
                    "inline": True,
                    "maxChars": 500000,
                    "description": f"results_page_{page}_{args.start_year}_{args.end_year}",
                },
            ]
        )

    out = await _call_playwright_run_flow(actions, name=f"discover_basic_year_{args.start_year}_{args.end_year}", browser=args.browser, timeout_ms=args.timeout_ms)
    html_texts = _extract_html_texts(out.get("content_texts") or [])

    inserted_total = 0
    updated_total = 0
    pages: List[Dict[str, Any]] = []

    run_id = str(uuid.uuid4())

    # Parse each captured page in order. Page numbering aligns with capture order (1..N).
    for idx, html in enumerate(html_texts):
        page_num = idx + 1
        parsed = _handle_parse_search_html(
            ParseSearchHtmlArgs(
                html=html,
                sourceYear=args.start_year if args.start_year == args.end_year else None,
                sourcePage=page_num,
                sourceUrl=f"{base_url}search/index/{page_num}" if page_num > 1 else search_url,
            )
        )
        inserted_total += int(parsed.get('inserted', 0))
        updated_total += int(parsed.get('updated', 0))
        pages.append({"page": page_num, **parsed})

    meta = {
        "start_year": args.start_year,
        "end_year": args.end_year,
        "keyword": args.keyword,
        "max_pages_requested": max_pages,
        "pages_captured": len(html_texts),
        "inserted_total": inserted_total,
        "updated_total": updated_total,
    }

    # Store a lightweight run record (avoid storing full HTML by default).
    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO runs(run_id, created_at, label, meta_json, html) VALUES(?,?,?,?,?)",
            (run_id, _utc_ts(), "discover_basic_year", json.dumps(meta, ensure_ascii=False), None),
        )
        conn.commit()

    return {
        "run_id": run_id,
        "start_year": args.start_year,
        "end_year": args.end_year,
        "keyword": args.keyword,
        "max_pages_requested": max_pages,
        "pages_captured": len(html_texts),
        "inserted_total": inserted_total,
        "updated_total": updated_total,
        "pages": pages,
    }


async def _handle_hydrate_doc(args: HydrateDocArgs) -> Dict[str, Any]:
    _ensure_db()

    doc_id = (args.doc_id or "").strip()
    if not doc_id:
        raise HTTPException(status_code=400, detail="docId is required")

    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        row = conn.execute(
            "SELECT doc_id, source_year, source_page, source_url FROM discovered WHERE doc_id=?",
            (doc_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"unknown doc_id '{doc_id}' (not in discovered)")

    source_year = row[1]
    source_page = row[2]
    source_url = row[3]

    base_url = (args.base_url or "").strip() or "http://deka.supremecourt.or.th/"
    if not base_url.endswith("/"):
        base_url = base_url + "/"

    # /search/index/<page> is POST/session dependent; do not rely on stored source_url.
    # Instead, re-run the basic search (year/keyword) to get a deterministic DOM.
    start_year = args.start_year if args.start_year is not None else source_year
    end_year = args.end_year if args.end_year is not None else source_year
    if start_year is None or end_year is None:
        raise HTTPException(status_code=400, detail="hydrate_doc requires startYear/endYear (or discovered.source_year must be set)")

    keyword = (args.keyword or "").strip() or None
    url = f"{base_url}"

    start_sel = "#search_deka_start_year"
    end_sel = "#search_deka_end_year"
    keyword_sel = "#search_word"

    async def _fetch_results_html(page_num: int) -> str:
        actions: List[Dict[str, Any]] = [
            {
                "type": "goto",
                "url": url,
                "waitUntil": "networkidle",
            },
            {"type": "delay", "ms": 2000},
            {
                "type": "wait_for_selector",
                "selector": start_sel,
                "state": "attached",
                "timeout": args.timeout_ms,
            },
            {
                "type": "fill",
                "selector": start_sel,
                "value": str(start_year),
            },
            {
                "type": "fill",
                "selector": end_sel,
                "value": str(end_year),
            },
        ]

        if keyword is not None:
            actions.append({"type": "fill", "selector": keyword_sel, "value": keyword})

        actions.extend(
            [
                {"type": "click", "selector": "#submit_search_deka"},
                {
                    "type": "wait_for_selector",
                    "selector": "#deka_result_info",
                    "state": "attached",
                    "timeout": args.timeout_ms,
                },
                {
                    "type": "wait_for_selector",
                    "selector": "#gotopage",
                    "state": "attached",
                    "timeout": args.timeout_ms,
                },
            ]
        )

        if page_num > 1:
            actions.extend(
                [
                    {"type": "fill", "selector": "#gotopage", "value": str(page_num)},
                    {"type": "click", "selector": "#btngotopage"},
                    {
                        "type": "wait_for_selector",
                        "selector": "#deka_result_info",
                        "state": "attached",
                        "timeout": args.timeout_ms,
                    },
                    {"type": "delay", "ms": 1500},
                ]
            )

        actions.append(
            {
                "type": "capture_html",
                "inline": True,
                "maxChars": int(args.max_chars),
                "description": f"hydrate_doc {doc_id} page {page_num}",
            }
        )

        out = await _call_playwright_run_flow(
            actions,
            name=f"hydrate_doc_{doc_id}_p{page_num}",
            browser=args.browser,
            timeout_ms=args.timeout_ms,
        )

        html_texts = _extract_html_texts(out.get("content_texts") or [])
        html = html_texts[-1] if html_texts else _extract_first_html(out.get("content_texts") or [])
        return (html or "").strip()

    def _parse_total_page(html_in: str) -> Optional[int]:
        if not html_in:
            return None
        try:
            soup = BeautifulSoup(html_in, "lxml")
            el = soup.select_one('#total_page')
            if el and el.get('value'):
                return int(str(el.get('value')).strip())
        except Exception:
            return None
        return None

    def _has_doc_id(html_in: str) -> bool:
        return f"short_text_docid_{doc_id}" in (html_in or "")

    # Try the discovered source_page first, then scan other pages until the doc_id is found.
    try:
        seed_page = int(source_page) if source_page is not None else 1
    except Exception:
        seed_page = 1
    if seed_page < 1:
        seed_page = 1

    html = ""
    tried: List[int] = []

    html_seed = await _fetch_results_html(seed_page)
    tried.append(seed_page)
    total_page = _parse_total_page(html_seed)
    if _has_doc_id(html_seed):
        html = html_seed
    else:
        max_page = total_page if total_page is not None else 15
        max_page = max(1, min(int(max_page), 50))
        for p in range(1, max_page + 1):
            if p in tried:
                continue
            html_p = await _fetch_results_html(p)
            tried.append(p)
            if _has_doc_id(html_p):
                html = html_p
                break

    if not html:
        raise HTTPException(status_code=502, detail=f"doc_id {doc_id} not found in search results after scanning pages")

    run_id = str(uuid.uuid4())
    created_at = _utc_ts()
    meta = {
        "doc_id": doc_id,
        "source_year": source_year,
        "source_page": source_page,
        "source_url": source_url,
        "url": url,
        "search_start_year": start_year,
        "search_end_year": end_year,
        "search_keyword": keyword,
        "clicked_short": bool(args.click_short),
        "tried_pages": tried,
        "scanned_total_page": total_page,
    }

    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO runs(run_id, created_at, label, meta_json, html) VALUES(?,?,?,?,?)",
            (run_id, created_at, "hydrate_doc", json.dumps(meta, ensure_ascii=False), html),
        )
        conn.commit()

    return {
        "run_id": run_id,
        "doc_id": doc_id,
        "url": url,
        "source_year": source_year,
        "source_page": source_page,
        "html_chars": len(html),
        "html_preview": html[:1000],
    }


def _handle_get_run(args: GetRunArgs) -> Dict[str, Any]:
    _ensure_db()
    run_id = (args.run_id or "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="runId is required")

    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        row = conn.execute(
            "SELECT run_id, created_at, label, meta_json, html FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"unknown run_id '{run_id}'")

    meta_raw = row[3]
    meta: Any = None
    if meta_raw:
        try:
            meta = json.loads(meta_raw)
        except Exception:
            meta = meta_raw

    html = row[4] or ""
    max_chars = int(args.max_chars)
    html_out = None
    truncated = False
    if bool(args.include_html):
        if len(html) > max_chars:
            html_out = html[:max_chars]
            truncated = True
        else:
            html_out = html

    return {
        "run_id": row[0],
        "created_at": row[1],
        "label": row[2],
        "meta": meta,
        "html_chars": len(html),
        "html_truncated": truncated,
        "html": html_out,
    }


def _handle_list_discovered(args: ListDiscoveredArgs) -> Dict[str, Any]:
    _ensure_db()
    limit = max(1, min(int(args.limit), 500))
    source_year = None
    try:
        if args.source_year is not None:
            source_year = int(args.source_year)
    except Exception:
        source_year = None

    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        if source_year is None:
            rows = conn.execute(
                "SELECT doc_id, last_seen_at, source_year, source_page FROM discovered ORDER BY last_seen_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT doc_id, last_seen_at, source_year, source_page FROM discovered WHERE source_year=? ORDER BY last_seen_at DESC LIMIT ?",
                (source_year, limit),
            ).fetchall()

    docs = [
        {"doc_id": r[0], "last_seen_at": r[1], "source_year": r[2], "source_page": r[3]} for r in (rows or [])
    ]
    return {"count": len(docs), "docs": docs}


def _extract_text_by_id(soup: BeautifulSoup, el_id: str) -> Optional[str]:
    el = soup.select_one(f"#{el_id}")
    if not el:
        return None
    return el.get_text("\n", strip=True)


def _handle_parse_hydrated_run(args: ParseHydratedRunArgs) -> Dict[str, Any]:
    _ensure_db()

    run_id = (args.run_id or "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="runId is required")

    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        row = conn.execute(
            "SELECT run_id, created_at, label, meta_json, html FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"unknown run_id '{run_id}'")

    label = (row[2] or "").strip()
    meta_raw = row[3] or ""
    html = (row[4] or "").strip()
    if not html:
        raise HTTPException(status_code=400, detail="run has no html")

    meta: Dict[str, Any] = {}
    if meta_raw:
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else {}
        except Exception:
            meta = {}

    doc_id = (args.doc_id or "").strip() or str(meta.get("doc_id") or meta.get("docId") or "").strip()
    if not doc_id:
        raise HTTPException(status_code=400, detail="docId is required (either pass docId or ensure run meta contains doc_id)")

    soup = BeautifulSoup(html, "lxml")

    short_text = _extract_text_by_id(soup, f"short_text_docid_{doc_id}")
    long_text = _extract_text_by_id(soup, f"long_text_docid_{doc_id}")
    remark_text = _extract_text_by_id(soup, f"remark_docid_{doc_id}")

    source_year = None
    try:
        if meta.get("source_year") is not None:
            source_year = int(meta.get("source_year"))
    except Exception:
        source_year = None

    now = _utc_ts()
    out_meta = {
        "run_id": run_id,
        "label": label,
        "parsed_at": now,
        "source_year": source_year,
    }

    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        existing = conn.execute("SELECT doc_id FROM hydrated_docs WHERE doc_id=?", (doc_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE hydrated_docs SET hydrated_at=?, run_id=?, source_year=?, short_text=?, long_text=?, remark_text=?, meta_json=? WHERE doc_id=?",
                (now, run_id, source_year, short_text, long_text, remark_text, json.dumps(out_meta, ensure_ascii=False), doc_id),
            )
            action = "updated"
        else:
            conn.execute(
                "INSERT INTO hydrated_docs(doc_id, hydrated_at, run_id, source_year, short_text, long_text, remark_text, meta_json) VALUES(?,?,?,?,?,?,?,?)",
                (doc_id, now, run_id, source_year, short_text, long_text, remark_text, json.dumps(out_meta, ensure_ascii=False)),
            )
            action = "inserted"
        conn.commit()

    return {
        "run_id": run_id,
        "doc_id": doc_id,
        "label": label,
        "action": action,
        "short_text_chars": len(short_text or ""),
        "long_text_chars": len(long_text or ""),
        "remark_text_chars": len(remark_text or ""),
        "short_text_preview": (short_text or "")[:300],
        "long_text_preview": (long_text or "")[:300],
        "remark_text_preview": (remark_text or "")[:300],
    }


def _handle_get_hydrated_doc(args: GetHydratedDocArgs) -> Dict[str, Any]:
    _ensure_db()
    doc_id = (args.doc_id or "").strip()
    if not doc_id:
        raise HTTPException(status_code=400, detail="docId is required")

    max_chars = int(args.max_chars)

    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        row = conn.execute(
            "SELECT doc_id, hydrated_at, run_id, source_year, short_text, long_text, remark_text FROM hydrated_docs WHERE doc_id=?",
            (doc_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"unknown doc_id '{doc_id}' (not in hydrated_docs)")

    def _cut(s: Optional[str]) -> Optional[str]:
        if s is None:
            return None
        if len(s) > max_chars:
            return s[:max_chars]
        return s

    return {
        "doc_id": row[0],
        "hydrated_at": row[1],
        "run_id": row[2],
        "source_year": row[3],
        "short_text": _cut(row[4] or ""),
        "long_text": _cut(row[5] or ""),
        "remark_text": _cut(row[6] or ""),
    }


def _parse_pagination(soup: BeautifulSoup) -> Dict[str, Optional[int]]:
    # Observed pattern:
    # <input type="hidden" id="total_page" name="total_page" value="11" />
    total_page = None
    el = soup.select_one('#total_page')
    if el and el.get('value'):
        try:
            total_page = int(str(el.get('value')).strip())
        except Exception:
            total_page = None

    # Pattern:
    # <li class="info"><span>หน้า 1 / 11</span>
    current_page = None
    info_span = soup.select_one('#pagination .info span')
    if info_span:
        text = info_span.get_text(' ', strip=True)
        # naive extraction: find first integer in string
        parts = [p for p in text.replace('/', ' ').split() if p.isdigit()]
        if parts:
            try:
                current_page = int(parts[0])
            except Exception:
                current_page = None

    return {
        'current_page': current_page,
        'total_page': total_page,
    }


def _extract_doc_ids(soup: BeautifulSoup) -> List[str]:
    # Observed in your HTML/JS:
    # <a class="btn-fiter-deka" data-deka-code="..."> ... </a>
    out: List[str] = []
    for el in soup.select('[data-deka-code]'):
        doc_id = (el.get('data-deka-code') or '').strip()
        if doc_id:
            out.append(doc_id)

    # Observed in rendered result lists:
    # <input type="checkbox" ... class="... deka-result" value="710157">
    for el in soup.select('input.deka-result'):
        val = (el.get('value') or '').strip()
        if val:
            out.append(val)

    # Fallback: hidden inputs sometimes carry doc ids
    for el in soup.select('input[type="hidden"]'):
        name = (el.get('name') or '').strip().lower()
        if name in {'dek_docid', 'docid', 'doc_id'}:
            val = (el.get('value') or '').strip()
            if val:
                out.append(val)

    # de-dup, preserve order
    seen = set()
    unique: List[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            unique.append(x)
    return unique


def _handle_parse_search_html(args: ParseSearchHtmlArgs) -> Dict[str, Any]:
    _ensure_db()
    html = (args.html or '').strip()
    if not html:
        raise HTTPException(status_code=400, detail='html is required')

    soup = BeautifulSoup(html, 'lxml')
    pagination = _parse_pagination(soup)
    doc_ids = _extract_doc_ids(soup)

    now = _utc_ts()
    inserted = 0
    updated = 0

    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        for doc_id in doc_ids:
            row = conn.execute('SELECT doc_id FROM discovered WHERE doc_id=?', (doc_id,)).fetchone()
            if row:
                conn.execute(
                    'UPDATE discovered SET last_seen_at=?, source_year=COALESCE(?, source_year), source_page=COALESCE(?, source_page), source_url=COALESCE(?, source_url) WHERE doc_id=?',
                    (now, args.source_year, args.source_page, args.source_url, doc_id),
                )
                updated += 1
            else:
                conn.execute(
                    'INSERT INTO discovered(doc_id, first_seen_at, last_seen_at, source_year, source_page, source_url, meta_json) VALUES(?,?,?,?,?,?,?)',
                    (
                        doc_id,
                        now,
                        now,
                        args.source_year,
                        args.source_page,
                        args.source_url,
                        json.dumps({'pagination': pagination}, ensure_ascii=False),
                    ),
                )
                inserted += 1
        conn.commit()

    return {
        'doc_ids_count': len(doc_ids),
        'inserted': inserted,
        'updated': updated,
        'pagination': pagination,
        'sample_doc_ids': doc_ids[:10],
    }


def _handle_parse_run(args: ParseRunArgs) -> Dict[str, Any]:
    _ensure_db()
    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        row = conn.execute('SELECT html FROM runs WHERE run_id=?', (args.run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='run_id not found')
    html = row[0] or ''
    return _handle_parse_search_html(
        ParseSearchHtmlArgs(
            html=html,
            sourceYear=args.source_year,
            sourcePage=args.source_page,
            sourceUrl=args.source_url,
        )
    )


def _handle_extract_links(args: ExtractLinksArgs) -> Dict[str, Any]:
    html = (args.html or "").strip()
    if not html:
        raise HTTPException(status_code=400, detail="html is required")

    limit = max(1, min(int(args.limit), 500))

    soup = BeautifulSoup(html, "lxml")

    if args.selector:
        # Minimal CSS selection support via BeautifulSoup (not full CSS4).
        nodes = soup.select(args.selector)
    else:
        nodes = soup.find_all("a")

    links = []
    for node in nodes:
        href = None
        try:
            href = node.get("href")
        except Exception:
            href = None
        if not href:
            continue
        text = "".join(node.get_text(" ", strip=True).split())
        links.append({"href": href, "text": text})
        if len(links) >= limit:
            break

    return {"count": len(links), "links": links}


def _handle_status(args: StatusArgs) -> Dict[str, Any]:
    _ensure_db()
    limit = max(1, min(int(args.limit), 50))
    with sqlite3.connect(MCP_DEKA_DB_PATH) as conn:
        row = conn.execute("SELECT COUNT(1) FROM runs").fetchone()
        total = int(row[0]) if row else 0
        row2 = conn.execute("SELECT COUNT(1) FROM discovered").fetchone()
        total_discovered = int(row2[0]) if row2 else 0
        recent = conn.execute(
            "SELECT run_id, created_at, label FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        recent_docs = conn.execute(
            "SELECT doc_id, last_seen_at, source_year, source_page FROM discovered ORDER BY last_seen_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    return {
        "total_runs": total,
        "total_discovered": total_discovered,
        "recent": [{"run_id": r[0], "created_at": r[1], "label": r[2]} for r in (recent or [])],
        "recent_discovered": [
            {"doc_id": d[0], "last_seen_at": d[1], "source_year": d[2], "source_page": d[3]} for d in (recent_docs or [])
        ],
    }


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return JsonRpcResponse(id=id_value, error=JsonRpcError(**err)).model_dump(exclude_none=True)


@app.post("/mcp")
async def mcp(payload: Dict[str, Any] = Body(...)) -> Any:
    request = JsonRpcRequest(**(payload or {}))
    if request.id is None:
        return None

    method = (request.method or "").strip()
    params = request.params or {}

    try:
        if method == "initialize":
            return JsonRpcResponse(
                id=request.id,
                result={
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                    "capabilities": {"tools": {}},
                },
            ).model_dump(exclude_none=True)

        if method in ("tools/list", "list_tools"):
            return JsonRpcResponse(id=request.id, result={"tools": _tool_definitions()}).model_dump(exclude_none=True)

        if method in ("tools/call", "call_tool"):
            tool_name = (params.get("name") or params.get("tool") or "").strip()
            arguments_raw = params.get("arguments") or {}
            if not tool_name:
                return _jsonrpc_error(request.id, -32602, "missing tool name")

            if tool_name == "run_search_flow":
                args = RunSearchFlowArgs(**(arguments_raw or {}))
                out = await _handle_run_search_flow(args)
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "get_run":
                args = GetRunArgs(**(arguments_raw or {}))
                out = _handle_get_run(args)
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "hydrate_doc":
                args = HydrateDocArgs(**(arguments_raw or {}))
                out = await _handle_hydrate_doc(args)
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "discover_basic_year":
                args = DiscoverBasicYearArgs(**(arguments_raw or {}))
                out = await _handle_discover_basic_year(args)
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "extract_links":
                args = ExtractLinksArgs(**(arguments_raw or {}))
                out = _handle_extract_links(args)
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "parse_search_html":
                args = ParseSearchHtmlArgs(**(arguments_raw or {}))
                out = _handle_parse_search_html(args)
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "parse_run":
                args = ParseRunArgs(**(arguments_raw or {}))
                out = _handle_parse_run(args)
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "parse_hydrated_run":
                args = ParseHydratedRunArgs(**(arguments_raw or {}))
                out = _handle_parse_hydrated_run(args)
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            if tool_name == "status":
                args = StatusArgs(**(arguments_raw or {}))
                out = _handle_status(args)
                return JsonRpcResponse(
                    id=request.id,
                    result={"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
                ).model_dump(exclude_none=True)

            return _jsonrpc_error(request.id, -32601, f"Unknown tool '{tool_name}'")

        return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'")
    except HTTPException as exc:
        return _jsonrpc_error(request.id, -32603, str(exc.detail))
    except Exception as exc:
        return _jsonrpc_error(request.id, -32603, str(exc))
