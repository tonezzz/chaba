from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()


def _today_ymd() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _ui_log_path_for_today() -> str:
    base_dir = str(os.getenv("JARVIS_UI_LOG_DIR") or "/data").strip() or "/data"
    return os.path.join(base_dir, f"jarvis-ui-{_today_ymd()}.jsonl")


def _ws_log_path_for_today() -> str:
    return str(os.getenv("JARVIS_WS_RECORD_PATH") or "/tmp/jarvis-ws.jsonl").strip() or "/tmp/jarvis-ws.jsonl"


def _read_tail(path: str, max_bytes: int, max_lines: Optional[int]) -> dict[str, Any]:
    if max_bytes <= 0:
        max_bytes = 1
    try:
        st = os.stat(path)
        size = int(st.st_size)
    except FileNotFoundError:
        return {"ok": True, "path": path, "content": "", "size": 0, "lines": 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stat log: {str(e)}")

    try:
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            data = f.read(max_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read log: {str(e)}")

    try:
        txt = data.decode("utf-8", errors="replace")
    except Exception:
        txt = ""

    if size > max_bytes:
        nl = txt.find("\n")
        if nl >= 0:
            txt = txt[nl + 1 :]

    if max_lines is not None:
        try:
            n = int(max_lines)
        except Exception:
            n = 0
        if n > 0:
            lines = txt.splitlines()
            if len(lines) > n:
                lines = lines[-n:]
            txt = "\n".join(lines)

    lines_count = 0
    if txt:
        lines_count = len(txt.splitlines())

    return {
        "ok": True,
        "path": path,
        "content": txt,
        "size": size,
        "lines": lines_count,
    }


@router.post("/logs/ui/append")
async def logs_ui_append(req: dict[str, Any]) -> dict[str, Any]:
    """Append UI logs"""
    try:
        entries = req.get("entries", [])
        if not isinstance(entries, list):
            raise HTTPException(status_code=400, detail="invalid_entries")

        path = _ui_log_path_for_today()
        os.makedirs(os.path.dirname(path), exist_ok=True)

        appended = 0
        with open(path, "a", encoding="utf-8") as f:
            for e in entries:
                try:
                    f.write(json.dumps(e, ensure_ascii=False))
                    f.write("\n")
                    appended += 1
                except Exception as err:
                    logger.warning(f"Failed to write log entry: {err}")
                    continue

        return {"ok": True, "path": path, "appended": appended}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to append UI logs: {str(e)}")


@router.get("/logs/sheets/status")
def logs_sheets_status() -> dict[str, Any]:
    """Get sheets logs status"""
    try:
        # Implementation would extract from main.py logs_sheets_status
        return {"ok": True, "queue_length": 0, "last_processed": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get sheets logs status: {str(e)}")


@router.get("/logs/ui/today")
def logs_ui_today(max_bytes: int = 200000, max_lines: Optional[int] = None) -> dict[str, Any]:
    """Get today's UI logs"""
    try:
        return _read_tail(_ui_log_path_for_today(), max_bytes=max_bytes, max_lines=max_lines)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get UI logs: {str(e)}")


@router.get("/logs/ws/today")
def logs_ws_today(max_bytes: int = 200000, max_lines: Optional[int] = None) -> dict[str, Any]:
    """Get today's WebSocket logs"""
    try:
        return _read_tail(_ws_log_path_for_today(), max_bytes=max_bytes, max_lines=max_lines)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get WebSocket logs: {str(e)}")
