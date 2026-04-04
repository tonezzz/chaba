from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def require_api_token_if_configured(x_api_token: Optional[str] = None) -> None:
    """Require API token if configured"""
    expected_token = os.getenv("JARVIS_API_TOKEN", "").strip()
    if expected_token:
        if not x_api_token or x_api_token.strip() != expected_token:
            raise HTTPException(status_code=401, detail="Invalid or missing API token")


def validate_session_id(session_id: Optional[str]) -> str:
    """Validate and normalize session ID"""
    if not session_id:
        import uuid
        return str(uuid.uuid4())
    return str(session_id).strip()


def validate_spreadsheet_id(spreadsheet_id: Optional[str]) -> str:
    """Validate spreadsheet ID"""
    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID is required")
    return str(spreadsheet_id).strip()


def validate_sheet_name(sheet_name: Optional[str]) -> str:
    """Validate sheet name"""
    if not sheet_name:
        raise ValueError("Sheet name is required")
    return str(sheet_name).strip()
