import os
from typing import Any, Optional


def _parse_bool(v: Any, default: bool) -> bool:
    if v is None:
        return default
    s = str(v).strip().lower()
    if not s:
        return default
    if s in {"1", "true", "t", "yes", "y", "on", "enable", "enabled"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off", "disable", "disabled"}:
        return False
    return default


def _sys_kv_bool(sys_kv: Any, key: str, default: bool) -> bool:
    if not isinstance(sys_kv, dict):
        return default
    if key not in sys_kv:
        return default
    return _parse_bool(sys_kv.get(key), default=default)


def feature_enabled(feature: str, *, sys_kv: Optional[dict[str, Any]], default: bool = True) -> bool:
    """Master feature switch:

    - Env var is a hard override (kill-switch): JARVIS_FEATURE_<FEATURE>_ENABLED
    - sys_kv is runtime control: feature.<feature>.enabled

    If env disables the feature, return False regardless of sys_kv.
    """

    name = str(feature or "").strip().lower()
    if not name:
        return default

    env_key = f"JARVIS_FEATURE_{name.upper().replace('-', '_')}_ENABLED"
    env_raw = os.getenv(env_key)
    if env_raw is not None and str(env_raw).strip() != "":
        if not _parse_bool(env_raw, default=default):
            return False

    return _sys_kv_bool(sys_kv, f"feature.{name}.enabled", default=default)
