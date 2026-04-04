from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def format_timestamp(ts: int | float | str) -> str:
    """Format timestamp to readable string"""
    try:
        if isinstance(ts, str):
            ts = int(float(ts))
        elif isinstance(ts, float):
            ts = int(ts)
        
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(ts)


def format_duration_ms(ms: int) -> str:
    """Format duration in milliseconds to readable string"""
    try:
        if ms < 1000:
            return f"{ms}ms"
        elif ms < 60000:
            seconds = ms / 1000
            return f"{seconds:.1f}s"
        else:
            minutes = ms / 60000
            return f"{minutes:.1f}m"
    except Exception:
        return f"{ms}ms"


def format_file_size(bytes_size: int) -> str:
    """Format file size in bytes to readable string"""
    try:
        if bytes_size < 1024:
            return f"{bytes_size}B"
        elif bytes_size < 1024 * 1024:
            return f"{bytes_size / 1024:.1f}KB"
        elif bytes_size < 1024 * 1024 * 1024:
            return f"{bytes_size / (1024 * 1024):.1f}MB"
        else:
            return f"{bytes_size / (1024 * 1024 * 1024):.1f}GB"
    except Exception:
        return f"{bytes_size}B"


def safe_filename(filename: str) -> str:
    """Make filename safe for filesystem"""
    try:
        import re
        # Remove invalid characters
        safe = re.sub(r'[<>:"/\\|?*]', '_', str(filename or ""))
        # Remove control characters
        safe = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', safe)
        # Trim and limit length
        safe = safe.strip()[:255]
        return safe or "unnamed"
    except Exception:
        return "unnamed"


def format_list(items: list[Any], max_items: int = 10, separator: str = ", ") -> str:
    """Format list of items to string"""
    try:
        if not items:
            return ""
        
        items_str = [str(item) for item in items[:max_items]]
        result = separator.join(items_str)
        
        if len(items) > max_items:
            result += f" ... and {len(items) - max_items} more"
        
        return result
    except Exception:
        return str(items)


def format_bytes_hex(data: bytes) -> str:
    """Format bytes as hex string"""
    try:
        return data.hex()
    except Exception:
        return str(data)


def parse_bool(value: Any) -> bool:
    """Parse boolean value from various types"""
    if isinstance(value, bool):
        return value
    
    if isinstance(value, (int, float)):
        return bool(value)
    
    if isinstance(value, str):
        s = value.strip().lower()
        return s in {"1", "true", "t", "yes", "y", "on"}
    
    return bool(value)


def parse_int(value: Any, default: int = 0) -> int:
    """Parse integer value safely"""
    try:
        return int(value or default)
    except (ValueError, TypeError):
        return default


def parse_float(value: Any, default: float = 0.0) -> float:
    """Parse float value safely"""
    try:
        return float(value or default)
    except (ValueError, TypeError):
        return default


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate string to max length"""
    try:
        if not text or len(text) <= max_length:
            return text
        
        return text[:max_length - len(suffix)] + suffix
    except Exception:
        return str(text)[:max_length]
