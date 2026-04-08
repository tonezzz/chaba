"""
Config API Router
Voice command configuration and system key-value helpers.
"""
from typing import Any
from fastapi import APIRouter

router = APIRouter()


def _parse_bool_cell(v: Any) -> bool:
    """Parse boolean value from cell."""
    s = str(v or "").strip().lower()
    return s in {"1", "true", "t", "yes", "y", "on", "enabled"}


def _split_phrases(value: Any) -> list[str]:
    """Split phrases from comma-separated value."""
    raw = str(value or "").strip()
    if not raw:
        return []
    parts: list[str] = []
    for line in raw.replace("\r", "\n").split("\n"):
        try:
            line = str(line or "")
            if "#" in line:
                line = line.split("#", 1)[0]
        except Exception:
            pass
        for p in str(line or "").split(","):
            s = str(p or "").strip()
            if s:
                parts.append(s)
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        k = p.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def _sys_kv_snapshot() -> dict[str, str]:
    """Get system key-value snapshot (simplified version)."""
    # For now, return empty dict - this would be populated from system sheet
    return {}


def _voice_command_config_from_sys_kv(sys_kv: dict[str, str]) -> dict[str, Any]:
    """Get voice command configuration from system key-value."""
    def _get(k: str, default: str = "") -> str:
        v = str(sys_kv.get(k) or "").strip()
        return v if v else default

    enabled = True
    raw_enabled = _get("voice_cmd.enabled", "")
    if raw_enabled:
        try:
            enabled = _parse_bool_cell(raw_enabled)
        except Exception:
            enabled = True

    try:
        debounce_ms = int(float(_get("voice_cmd.debounce_ms", "10000")))
        debounce_ms = max(0, min(debounce_ms, 120_000))
    except Exception:
        debounce_ms = 10_000

    return {
        "enabled": enabled,
        "debounce_ms": debounce_ms,
        "recent_activity": {
            "enabled": _parse_bool_cell(_get("voice_cmd.recent_activity.enabled", "true")),
            "phrases": _split_phrases(
                _get(
                    "voice_cmd.recent_activity.phrases",
                    "recent tasks,recent task,recent activity,what was i doing,what were you doing,เมื่อกี้ทำอะไร,เมื่อกี้ทำอะไรอยู่,ทำอะไรล่าสุด,งานล่าสุด,ล่าสุดทำอะไร",
                )
            ),
        },
        "reload": {
            "enabled": _parse_bool_cell(_get("voice_cmd.reload.enabled", "true")),
            "phrases": _split_phrases(_get("voice_cmd.reload.phrases", "")),
            "mode_keywords": {
                "gems": _split_phrases(_get("voice_cmd.reload.keywords.gems", "gems,gem,models,model,เจม,โมเดล")),
                "knowledge": _split_phrases(_get("voice_cmd.reload.keywords.knowledge", "knowledge,kb,know,ความรู้")),
                "memory": _split_phrases(_get("voice_cmd.reload.keywords.memory", "memory,mem,เมม,เมมโม")),
            },
        },
        "reminders_add": {
            "enabled": _parse_bool_cell(_get("voice_cmd.reminders_add.enabled", "true")),
            "phrases": _split_phrases(_get("voice_cmd.reminders_add.phrases", "")),
        },
        "gems_list": {
            "enabled": _parse_bool_cell(_get("voice_cmd.gems_list.enabled", "true")),
            "phrases": _split_phrases(_get("voice_cmd.gems_list.phrases", "")),
        },
    }


@router.get("/config/voice_commands")
@router.get("/jarvis/config/voice_commands")
def config_voice_commands() -> dict[str, Any]:
    """Get voice commands configuration."""
    sys_kv = _sys_kv_snapshot()
    cfg = _voice_command_config_from_sys_kv(sys_kv)
    return {"ok": True, "config": cfg}
