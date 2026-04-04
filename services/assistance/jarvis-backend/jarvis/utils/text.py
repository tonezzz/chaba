from __future__ import annotations

import html as _html
import re
from typing import Any

import logging

logger = logging.getLogger(__name__)


def strip_html_tags(s: str) -> str:
    """Strip HTML tags from text"""
    txt = str(s or "")
    if not txt:
        return ""
    
    try:
        txt = re.sub(r"<[^>]+>", " ", txt)
    except Exception:
        txt = txt
    
    try:
        txt = _html.unescape(txt)
    except Exception:
        pass
    
    try:
        txt = re.sub(r"\s+", " ", txt).strip()
    except Exception:
        txt = txt.strip()
    
    return txt


def normalize_simple_cmd(text: str) -> str:
    """Normalize simple command text"""
    s = str(text or "").strip().lower()
    if not s:
        return ""
    
    # Remove special characters, keep alphanumeric and Thai
    s = re.sub(r"[^a-z0-9\u0E00-\u0E7F]+", " ", s).strip()
    return " ".join(s.split())


def clamp_text(s: Any, limit: int) -> str:
    """Clamp text to specified limit"""
    try:
        t = str(s or "")
    except Exception:
        return ""
    
    t = t.strip()
    if not t:
        return ""
    if len(t) > limit:
        return t[:limit].rstrip() + "…"
    return t


def is_low_quality_news_description(*, title: str, description: str) -> bool:
    """Check if news description is low quality"""
    t = str(title or "").strip()
    d0 = str(description or "").strip()
    if not d0:
        return True
    
    d = strip_html_tags(d0) if ("<" in d0 and ">" in d0) else d0
    d = str(d or "").strip()
    if not d:
        return True
    
    tl = t.lower().strip()
    dl = d.lower().strip()
    if tl and dl == tl:
        return True
    
    # Common Google News RSS pattern: description is just the title as an <a> tag + publisher.
    if tl and dl.startswith(tl):
        rest = d[len(t) :].strip()
        rest = rest.replace("\u00a0", " ")
        rest = re.sub(r"\s+", " ", rest).strip()
        # If remainder looks like only a source label (e.g. Reuters) or is extremely short, treat as low quality.
        if not rest:
            return True
        if len(rest) <= 30 and re.fullmatch(r"[\w\-\|\s\.]+", rest or ""):
            return True
    
    # If the original description was HTML-y and stripping leaves something very short, treat as low quality.
    if ("<" in d0 and ">" in d0) and len(d) <= 40:
        return True
    
    return False


def clean_news_description(*, title: str, description: str) -> str:
    """Clean news description"""
    d0 = str(description or "")
    d = strip_html_tags(d0) if ("<" in d0 and ">" in d0) else str(d0).strip()
    
    if is_low_quality_news_description(title=str(title or ""), description=d):
        return ""
    
    return str(d or "").strip()


def extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """Extract JSON object from text"""
    s = str(text or "").strip()
    if not s:
        return None
    
    # Best-effort: grab first {...} block.
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


def normalize_cmd_text(text: str) -> str:
    """Normalize command text"""
    return str(text or "").strip()


def is_thai_memo_command(text: str) -> bool:
    """Check if text is a Thai memo command"""
    s = str(text or "").strip()
    if not s:
        return False
    
    # Check for Thai memo patterns
    thai_patterns = [
        r"^(?:ปรับปรุง|แก้ไข)\s*(?:เมโม|เมมโม|เมโม่|เมม)\s*$",
        r"^เพิ่ม\s*(?:เมโม|เมมโม|เมโม่|เมม)\s*",
        r"^ลบ\s*(?:เมโม|เมมโม|เมโม่|เมม)\s*",
        r"^ค้นหา\s*(?:เมโม|เมมโม|เมโม่|เมม)\s*",
    ]
    
    for pattern in thai_patterns:
        if re.match(pattern, s, re.IGNORECASE):
            return True
    
    return False


def format_thai_datetime(dt) -> str:
    """Format datetime for Thai locale"""
    try:
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(dt)
