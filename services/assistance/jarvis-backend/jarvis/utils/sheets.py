"""Sheet/data manipulation utilities."""
from __future__ import annotations
import json
from typing import Any


def json_loads_loose(raw: Any) -> Any:
    """Parse JSON string loosely, returning None on failure."""
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def normalize_projects_registry(obj: Any) -> list[dict[str, Any]]:
    """Normalize various registry formats to list of {name, spreadsheet_id}."""
    out: list[dict[str, Any]] = []
    if obj is None:
        return out
    if isinstance(obj, dict):
        # Accept mapping forms: {"name": "spreadsheet_id"} or {"spreadsheet_id": "name"}.
        for k, v in obj.items():
            k2 = str(k or "").strip()
            if not k2:
                continue
            if isinstance(v, str):
                v2 = str(v or "").strip()
                if not v2:
                    continue
                # Heuristic: spreadsheet ids are longer and contain dashes/underscores.
                if len(v2) >= 20:
                    out.append({"name": k2, "spreadsheet_id": v2})
                else:
                    out.append({"name": v2, "spreadsheet_id": k2})
            else:
                v_obj = v if isinstance(v, dict) else {}
                sid = str(v_obj.get("spreadsheet_id") or v_obj.get("id") or "").strip()
                nm = str(v_obj.get("name") or k2).strip()
                if sid:
                    out.append({"name": nm, "spreadsheet_id": sid})
        return out
    if isinstance(obj, list):
        for it in obj:
            if isinstance(it, str):
                sid = str(it or "").strip()
                if sid:
                    out.append({"name": "", "spreadsheet_id": sid})
                continue
            if isinstance(it, dict):
                sid = str(it.get("spreadsheet_id") or it.get("id") or "").strip()
                nm = str(it.get("name") or it.get("title") or "").strip()
                if sid:
                    out.append({"name": nm, "spreadsheet_id": sid})
        return out
    return out


def find_registry_match(registry: list[dict[str, Any]], *, name: str) -> dict[str, Any] | None:
    """Find registry item by name (exact match, then substring)."""
    want = str(name or "").strip().lower()
    if not want:
        return None
    for it in registry:
        if not isinstance(it, dict):
            continue
        nm = str(it.get("name") or "").strip().lower()
        if nm and nm == want:
            return it
    # fallback: substring
    for it in registry:
        if not isinstance(it, dict):
            continue
        nm = str(it.get("name") or "").strip().lower()
        if nm and want in nm:
            return it
    return None


def header_index(values: Any) -> dict[str, int]:
    """Build column index from header row."""
    if not isinstance(values, list) or not values or not isinstance(values[0], list):
        return {}
    idx: dict[str, int] = {}
    for j, h in enumerate(values[0]):
        k = str(h or "").strip().lower()
        if k and k not in idx:
            idx[k] = int(j)
    return idx


def set_row_value(row: list[Any], idx: dict[str, int], key: str, value: Any) -> None:
    """Set value in row by column key."""
    k = str(key or "").strip().lower()
    if not k:
        return
    j = idx.get(k)
    if j is None:
        return
    if j >= len(row):
        row.extend([""] * (j + 1 - len(row)))
    row[j] = value


def normalize_field_key(k: str) -> str:
    """Normalize field key to snake_case."""
    return str(k or "").strip().lower().replace(" ", "_")


def col_letter(col_idx0: int) -> str:
    """Convert 0-based column index to Excel letter (A, B, ... Z, AA, ...)."""
    n = int(col_idx0) + 1
    if n <= 0:
        return "A"
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(ord("A") + r) + out
    return out or "A"
