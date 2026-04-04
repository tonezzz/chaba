from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def load_sheet_table(
    *,
    spreadsheet_id: str,
    sheet_name: str,
    max_rows: int = 250,
    max_cols: str = "Q"
) -> list[list[Any]]:
    """Load data from Google Sheets table"""
    # TODO: Implement actual Sheets API call
    # This would use MCP tools to fetch sheet data
    logger.info(f"Loading sheet {sheet_name} from {spreadsheet_id}")
    return []


async def load_sheet_kv5(
    *,
    spreadsheet_id: str,
    sheet_name: str
) -> list[dict[str, Any]]:
    """Load key-value pairs from sheet (5-column format)"""
    # TODO: Implement loading from 5-column format
    # Columns: key, value, enabled, priority, scope
    logger.info(f"Loading KV5 from {sheet_name}")
    return []


def idx_from_header(header: list[Any]) -> dict[str, int]:
    """Create column index map from header row"""
    idx = {}
    for i, col in enumerate(header):
        if isinstance(col, str):
            col_lower = col.strip().lower()
            idx[col_lower] = i
    return idx


def get_cell(row: list[Any], idx: dict[str, int], key: str, default: Any = "") -> Any:
    """Get cell value by column name"""
    col_idx = idx.get(key.strip().lower())
    if col_idx is not None and 0 <= col_idx < len(row):
        return row[col_idx]
    return default


def parse_bool_cell(value: Any) -> bool:
    """Parse boolean value from cell"""
    s = str(value or "").strip().lower()
    return s in {"1", "true", "t", "yes", "y", "on"}


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert to integer"""
    try:
        return int(value or default)
    except (ValueError, TypeError):
        return default


def normalize_model_name(name: str) -> str:
    """Normalize model name"""
    s = str(name or "").strip()
    if s.startswith("models/"):
        s = s[len("models/") :]
    return s


def normalize_models_prefix(name: str) -> str:
    """Add models/ prefix if missing"""
    s = str(name or "").strip()
    if not s:
        return ""
    return s if s.startswith("models/") else f"models/{s}"


def parse_model_list(value: str) -> list[str]:
    """Parse comma-separated model list"""
    parts = [p.strip() for p in str(value or "").split(",")]
    return [p for p in parts if p]


def extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """Extract JSON object from text"""
    s = str(text or "").strip()
    if not s:
        return None
    
    try:
        i = s.find("{")
        j = s.rfind("}")
        if i >= 0 and j > i:
            s = s[i : j + 1]
        import json
        parsed = json.loads(s)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None
