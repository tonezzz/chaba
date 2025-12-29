from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

APP_NAME = "mcp-quickchart"
APP_VERSION = "0.1.0"

QUICKCHART_BASE_URL = (os.getenv("QUICKCHART_BASE_URL") or "https://quickchart.io").rstrip("/")
QUICKCHART_API_BASE_URL = (os.getenv("QUICKCHART_API_BASE_URL") or "https://api.quickchart.io").rstrip("/")
DEFAULT_OUTPUT_DIR = (os.getenv("QUICKCHART_DEFAULT_OUTPUT_DIR") or "/data").strip() or "/data"

MAX_OUTPUT_BYTES = int(os.getenv("QUICKCHART_MAX_OUTPUT_BYTES", "20000000"))  # 20MB
REQUEST_TIMEOUT_SECONDS = float(os.getenv("QUICKCHART_TIMEOUT_SECONDS", "30"))


def _enabled(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


ENABLE_CHART = _enabled("QUICKCHART_ENABLE_CHART", True)
ENABLE_APEXCHARTS = _enabled("QUICKCHART_ENABLE_APEXCHARTS", True)
ENABLE_GOOGLECHARTS = _enabled("QUICKCHART_ENABLE_GOOGLECHARTS", True)
ENABLE_TEXTCHART = _enabled("QUICKCHART_ENABLE_TEXTCHART", True)
ENABLE_SPARKLINE = _enabled("QUICKCHART_ENABLE_SPARKLINE", True)
ENABLE_GRAPHVIZ = _enabled("QUICKCHART_ENABLE_GRAPHVIZ", True)
ENABLE_WORDCLOUD = _enabled("QUICKCHART_ENABLE_WORDCLOUD", True)
ENABLE_BARCODE = _enabled("QUICKCHART_ENABLE_BARCODE", True)
ENABLE_QRCODE = _enabled("QUICKCHART_ENABLE_QRCODE", True)
ENABLE_TABLE = _enabled("QUICKCHART_ENABLE_TABLE", True)
ENABLE_WATERMARK = _enabled("QUICKCHART_ENABLE_WATERMARK", True)
ENABLE_HELP = _enabled("QUICKCHART_ENABLE_HELP", True)


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    return JsonRpcResponse(id=id_value, error=JsonRpcError(code=code, message=message, data=data)).model_dump(
        exclude_none=True
    )


def _safe_output_path(output_path: str) -> Path:
    if not output_path:
        raise ValueError("outputPath is required when action=save_file")

    base = Path(DEFAULT_OUTPUT_DIR).resolve()
    target = Path(output_path)

    if not target.is_absolute():
        target = (base / target).resolve()
    else:
        target = target.resolve()

    if base != target and base not in target.parents:
        raise ValueError(f"outputPath must be inside {base}")

    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _encode_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def _build_url(base: str, path: str, query: Dict[str, Any]) -> str:
    cleaned: Dict[str, str] = {}
    for key, value in query.items():
        if value is None:
            continue
        text = _encode_value(value)
        if text == "":
            continue
        cleaned[key] = text
    qs = urlencode(cleaned, doseq=True)
    return f"{base}{path}?{qs}" if qs else f"{base}{path}"


async def _download_to_file(url: str, output_path: Path, method: str = "GET", json_body: Any = None) -> str:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
        if method.upper() == "POST":
            resp = await client.post(url, json=json_body)
        else:
            resp = await client.get(url)

    resp.raise_for_status()
    content = resp.content
    if len(content) > MAX_OUTPUT_BYTES:
        raise ValueError(f"Response too large ({len(content)} bytes)")

    output_path.write_bytes(content)
    return str(output_path)


def _tool_defs() -> List[Dict[str, Any]]:
    common = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get_url", "save_file"]},
            "outputPath": {"type": "string"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "format": {"type": "string"},
        },
        "required": ["action"],
        "additionalProperties": True,
    }

    tools: List[Dict[str, Any]] = []

    if ENABLE_CHART:
        tools.append({
            "name": "create-chart-using-chartjs",
            "description": "Create charts using Chart.js and QuickChart.io - get chart image URL or save chart image to file",
            "inputSchema": common,
        })

    if ENABLE_APEXCHARTS:
        tools.append({
            "name": "create-chart-using-apexcharts",
            "description": "Create charts using ApexCharts - get chart image URL or save chart image to file",
            "inputSchema": common,
        })

    if ENABLE_GOOGLECHARTS:
        tools.append({
            "name": "create-chart-using-googlecharts",
            "description": "Create charts using Google Charts - get chart image URL or save chart image to file",
            "inputSchema": common,
        })

    if ENABLE_TEXTCHART:
        tools.append({
            "name": "create-chart-using-natural-language",
            "description": "Generate charts from natural language descriptions - get chart image URL or save chart image to file",
            "inputSchema": common,
        })

    if ENABLE_SPARKLINE:
        tools.append({
            "name": "create-sparkline-using-chartjs",
            "description": "Create compact sparkline charts - get sparkline image URL or save sparkline image to file",
            "inputSchema": common,
        })

    if ENABLE_GRAPHVIZ:
        tools.append({
            "name": "create-diagram-using-graphviz",
            "description": "Create graph diagrams using GraphViz - get diagram image URL or save diagram image to file",
            "inputSchema": common,
        })

    if ENABLE_WORDCLOUD:
        tools.append({
            "name": "create-wordcloud",
            "description": "Create word cloud visualizations - get word cloud image URL or save word cloud image to file",
            "inputSchema": common,
        })

    if ENABLE_BARCODE:
        tools.append({
            "name": "create-barcode",
            "description": "Generate barcodes - get barcode image URL or save barcode image to file",
            "inputSchema": common,
        })

    if ENABLE_TABLE:
        tools.append({
            "name": "create-table",
            "description": "Convert data to table images - get table image URL or save table image to file",
            "inputSchema": common,
        })

    if ENABLE_QRCODE:
        tools.append({
            "name": "create-qr-code",
            "description": "Create QR codes with customization - get QR code image URL or save QR code image to file",
            "inputSchema": common,
        })

    if ENABLE_WATERMARK:
        tools.append({
            "name": "create-watermark",
            "description": "Add watermarks/logos to images - get watermarked image URL or save result to file",
            "inputSchema": common,
        })

    if ENABLE_HELP:
        tools.append({
            "name": "get-visualization-tool-help",
            "description": "Get usage info/examples for available visualization tools",
            "inputSchema": {"type": "object", "properties": {}},
        })

    return tools


def _help_payload() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "quickchart_base_url": QUICKCHART_BASE_URL,
        "quickchart_api_base_url": QUICKCHART_API_BASE_URL,
        "default_output_dir": DEFAULT_OUTPUT_DIR,
        "tools": [tool["name"] for tool in _tool_defs()],
    }


async def _handle_tool_call(tool_name: str, args: Dict[str, Any]) -> str:
    if tool_name == "get-visualization-tool-help":
        return json.dumps(_help_payload(), indent=2)

    action = (args.get("action") or "").strip()
    if action not in {"get_url", "save_file"}:
        raise ValueError("action must be 'get_url' or 'save_file'")

    output_path_raw = (args.get("outputPath") or "").strip()

    width = args.get("width")
    height = args.get("height")
    fmt = args.get("format")

    payload = dict(args)
    payload.pop("action", None)
    payload.pop("outputPath", None)

    endpoint_url: str
    method = "GET"
    json_body: Any = None

    if tool_name == "create-chart-using-chartjs":
        query: Dict[str, Any] = {
            "c": payload.get("chart") or payload.get("config") or payload.get("c") or payload,
        }
        if width:
            query["width"] = width
        if height:
            query["height"] = height
        if fmt:
            query["format"] = fmt
        endpoint_url = _build_url(QUICKCHART_BASE_URL, "/chart", query)

    elif tool_name == "create-sparkline-using-chartjs":
        query = {
            "c": payload.get("config") or payload.get("chart") or payload.get("c") or payload,
        }
        if width:
            query["width"] = width
        if height:
            query["height"] = height
        if fmt:
            query["format"] = fmt
        endpoint_url = _build_url(QUICKCHART_BASE_URL, "/sparkline", query)

    elif tool_name == "create-diagram-using-graphviz":
        query = {
            "graph": payload.get("graph") or payload.get("dot") or payload.get("source") or "",
            "layout": payload.get("layout"),
            "format": fmt or payload.get("format"),
            "width": width,
            "height": height,
        }
        endpoint_url = _build_url(QUICKCHART_BASE_URL, "/graphviz", query)

    elif tool_name == "create-wordcloud":
        query = {
            "text": payload.get("text") or "",
            "width": width,
            "height": height,
            "format": fmt or payload.get("format"),
        }
        for k in (
            "font",
            "fontScale",
            "rotation",
            "minWordLength",
            "removeStopwords",
            "colors",
            "backgroundColor",
        ):
            if k in payload:
                query[k] = payload[k]
        endpoint_url = _build_url(QUICKCHART_BASE_URL, "/wordcloud", query)

    elif tool_name == "create-barcode":
        query = {
            "type": payload.get("type") or "code128",
            "text": payload.get("text") or "",
            "width": width,
            "height": height,
            "format": fmt or payload.get("format"),
        }
        endpoint_url = _build_url(QUICKCHART_BASE_URL, "/barcode", query)

    elif tool_name == "create-qr-code":
        query = {
            "text": payload.get("text") or "",
            "size": payload.get("size") or width or height,
            "format": fmt or payload.get("format"),
        }
        for k in (
            "dark",
            "light",
            "ecLevel",
            "margin",
            "centerImageUrl",
            "centerImageSizeRatio",
            "caption",
            "captionFont",
            "captionFontSize",
        ):
            if k in payload:
                query[k] = payload[k]
        endpoint_url = _build_url(QUICKCHART_BASE_URL, "/qr", query)

    elif tool_name == "create-watermark":
        query = {
            "mainImageUrl": payload.get("mainImageUrl") or payload.get("image") or "",
            "watermarkImageUrl": payload.get("watermarkImageUrl") or payload.get("watermark") or "",
            "position": payload.get("position"),
            "opacity": payload.get("opacity"),
            "format": fmt or payload.get("format"),
        }
        endpoint_url = _build_url(QUICKCHART_BASE_URL, "/watermark", query)

    elif tool_name == "create-chart-using-apexcharts":
        method = "POST"
        endpoint_url = f"{QUICKCHART_BASE_URL}/apex-charts/render"
        json_body = {
            "config": payload.get("config") or payload,
            "width": width,
            "height": height,
            "format": fmt or payload.get("format"),
            "version": payload.get("version"),
        }

    elif tool_name == "create-chart-using-googlecharts":
        method = "POST"
        endpoint_url = f"{QUICKCHART_BASE_URL}/google-charts/render"
        json_body = {
            "code": payload.get("code") or "",
            "packages": payload.get("packages") or ["corechart"],
            "width": width,
            "height": height,
            "format": fmt or payload.get("format"),
            "language": payload.get("language"),
        }

    elif tool_name == "create-chart-using-natural-language":
        query = {
            "description": payload.get("description") or "",
            "data1": payload.get("data1"),
            "data2": payload.get("data2"),
            "labels": payload.get("labels"),
            "title": payload.get("title"),
            "width": width,
            "height": height,
            "format": fmt or payload.get("format"),
        }
        endpoint_url = _build_url(QUICKCHART_BASE_URL, "/natural", query)

    elif tool_name == "create-table":
        method = "POST"
        endpoint_url = f"{QUICKCHART_API_BASE_URL}/v1/table"
        json_body = payload.get("data") or payload

    else:
        raise ValueError(f"Unknown tool '{tool_name}'")

    if action == "get_url":
        if method == "POST":
            return json.dumps({"url": endpoint_url, "method": "POST", "json": json_body}, ensure_ascii=False)
        return endpoint_url

    output_path = _safe_output_path(output_path_raw)
    saved = await _download_to_file(endpoint_url, output_path, method=method, json_body=json_body)
    return f"saved_file: {saved}"


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "time": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/.well-known/mcp.json")
async def well_known_manifest() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "MCP server for generating QuickChart.io visualizations.",
        "capabilities": {"tools": _tool_defs()},
    }


@app.post("/mcp")
async def mcp_endpoint(payload: Dict[str, Any] = Body(...)):
    request = JsonRpcRequest(**(payload or {}))

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

    if method in ("tools/list", "list_tools"):
        return JsonRpcResponse(id=request.id, result={"tools": _tool_defs()}).model_dump(exclude_none=True)

    if method in ("tools/call", "call_tool"):
        tool_name = (params.get("name") or params.get("tool") or "").strip()
        arguments_raw = params.get("arguments") or {}
        if not tool_name:
            return _jsonrpc_error(request.id, -32602, "Missing tool name")

        try:
            out = await _handle_tool_call(tool_name, dict(arguments_raw or {}))
        except Exception as exc:  # noqa: BLE001
            return _jsonrpc_error(request.id, -32603, str(exc))

        return JsonRpcResponse(
            id=request.id,
            result={"content": [{"type": "text", "text": out}]},
        ).model_dump(exclude_none=True)

    return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'")
