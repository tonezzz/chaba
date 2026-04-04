from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Header

from jarvis.utils.validation import require_api_token_if_configured
from jarvis.sheets.operations import load_sheet_table, load_sheet_kv5

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/sheets/table")
async def get_sheet_table(
    spreadsheet_id: str,
    sheet_name: str,
    max_rows: int = 250,
    max_cols: str = "Q",
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    """Get sheet table data"""
    require_api_token_if_configured(x_api_token)
    try:
        data = await load_sheet_table(
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name,
            max_rows=max_rows,
            max_cols=max_cols
        )
        return {"ok": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load sheet table: {str(e)}")


@router.get("/sheets/kv5")
async def get_sheet_kv5(
    spreadsheet_id: str,
    sheet_name: str,
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    """Get sheet key-value data (5-column format)"""
    require_api_token_if_configured(x_api_token)
    try:
        data = await load_sheet_kv5(
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name
        )
        return {"ok": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load sheet KV5: {str(e)}")


@router.post("/sheets/refresh")
async def refresh_sheet_cache(
    spreadsheet_id: str,
    sheet_name: str,
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    """Refresh sheet cache"""
    require_api_token_if_configured(x_api_token)
    try:
        # TODO: Implement cache refresh logic
        return {"ok": True, "message": "Sheet cache refresh - to be implemented"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh sheet cache: {str(e)}")
