from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Header

from jarvis.memo.commands import handle_memo_commands
from jarvis.memo.storage import (
    memo_add,
    memo_repair_ids,
    memo_columns_reorder,
    memo_index_backfill,
    memo_related,
    memo_summarize_related,
    memo_relate
)
from jarvis.utils.validation import require_api_token_if_configured

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/memo/header/normalize")
async def memo_header_normalize(x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token")) -> dict[str, Any]:
    """Normalize memo headers"""
    require_api_token_if_configured(x_api_token)
    # Implementation would go here
    return {"ok": True, "message": "Memo header normalize - to be implemented"}


@router.post("/memo/repair/ids")
async def memo_repair_ids_endpoint(
    req: dict[str, Any],
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    """Repair memo IDs"""
    require_api_token_if_configured(x_api_token)
    try:
        result = await memo_repair_ids(req)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to repair memo IDs: {str(e)}")


@router.post("/memo/columns/reorder")
async def memo_columns_reorder_endpoint(
    req: dict[str, Any],
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    """Reorder memo columns"""
    require_api_token_if_configured(x_api_token)
    try:
        result = await memo_columns_reorder(req)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reorder memo columns: {str(e)}")


@router.post("/memo/add")
async def memo_add_endpoint(
    req: dict[str, Any],
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    """Add new memo"""
    require_api_token_if_configured(x_api_token)
    try:
        result = await memo_add(req)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add memo: {str(e)}")


@router.post("/memo/index/backfill")
async def memo_index_backfill_endpoint(
    req: dict[str, Any],
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    """Backfill memo index"""
    require_api_token_if_configured(x_api_token)
    try:
        result = await memo_index_backfill(req)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to backfill memo index: {str(e)}")


@router.get("/memo/related")
async def memo_related_endpoint(
    q: Optional[str] = None,
    k: int = 30,
    group: Optional[str] = None,
) -> dict[str, Any]:
    """Get related memos"""
    try:
        result = await memo_related(q=q, k=k, group=group)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get related memos: {str(e)}")


@router.post("/memo/summarize_related")
async def memo_summarize_related_endpoint(
    req: dict[str, Any],
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    """Summarize related memos"""
    require_api_token_if_configured(x_api_token)
    try:
        result = await memo_summarize_related(req)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to summarize related memos: {str(e)}")


@router.post("/memo/relate")
async def memo_relate_endpoint(
    req: dict[str, Any],
    x_api_token: Optional[str] = Header(default=None, alias="X-Api-Token"),
) -> dict[str, Any]:
    """Relate memos"""
    require_api_token_if_configured(x_api_token)
    try:
        result = await memo_relate(req)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to relate memos: {str(e)}")
