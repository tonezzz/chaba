"""MCP Debug SSOT editing helpers.

Only appends to whitelisted top-level list sections. No deletes, no moves, no
in-place edits. This keeps the tool narrow and auditable.
"""
import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path("/home/tony/CascadeProjects/chaba-tony-dell")
SSOT_ROOT = REPO_ROOT / "docs" / "ssot"

import sys as _sys
_sys.path.insert(0, str(REPO_ROOT / "scripts" / "board"))
try:
    import card_io as _card_io
except ImportError:  # checkout predates card_io
    _card_io = None

# Top-level list sections this tool is allowed to append to.
ALLOWED_SECTIONS = {
    "quick_wins",
    "history",
    "request_log",
    "subtasks",
    "improvements",
    "improvements.done",
    "notes",
    "items",
    "services",
}


def _resolve_path(path):
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    try:
        p = p.resolve()
    except Exception:
        pass
    if not str(p).startswith(str(SSOT_ROOT.resolve())):
        return None
    if p.suffix != ".yml":
        return None
    return p


def _load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _save_yaml(path, data):
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True,
                          width=120, default_flow_style=False)
    if _card_io is not None:
        # atomic — never leave a torn SSOT file (2026-11-19 ENOSPC)
        _card_io.atomic_write_text(path, text)
        return
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    tmp.replace(path)


def mcp_ssot_append(path, section, item):
    """Append `item` to `section` in the SSOT at `path`.

    `item` can be a YAML string or a dict/list. `section` must be a whitelisted
    top-level list key.
    """
    p = _resolve_path(path)
    if p is None:
        return {"ok": False, "error": "path is not a valid SSOT under docs/ssot/"}
    if section not in ALLOWED_SECTIONS:
        return {"ok": False, "error": f"section '{section}' not in append allowlist"}
    try:
        data = _load_yaml(p)
    except Exception as exc:
        return {"ok": False, "error": f"failed to load {path}: {exc}"}
    if section not in data or not isinstance(data[section], list):
        return {"ok": False, "error": f"section '{section}' is not a list in {path}"}
    try:
        parsed = yaml.safe_load(item) if isinstance(item, str) else item
    except Exception as exc:
        return {"ok": False, "error": f"item is not valid YAML: {exc}"}
    data[section].append(parsed)
    try:
        _save_yaml(p, data)
    except Exception as exc:
        return {"ok": False, "error": f"failed to save {path}: {exc}"}
    logger.info("appended to %s[%s]: %s", p, section, parsed)
    return {"ok": True, "path": str(p), "section": section, "index": len(data[section]) - 1}
