from __future__ import annotations

from typing import Any, Awaitable, Callable


def prompt_cfg(
    sys_kv: Any,
    *,
    sys_kv_bool: Callable[[Any, str, bool], bool],
    safe_int: Callable[[Any, int], int],
) -> dict[str, Any]:
    enabled = sys_kv_bool(sys_kv, "memo.prompt.enabled", True)
    require_subject = sys_kv_bool(sys_kv, "memo.prompt.require_subject", True)
    require_group = sys_kv_bool(sys_kv, "memo.prompt.require_group", True)
    require_details = sys_kv_bool(sys_kv, "memo.prompt.require_details", True)
    min_chars = safe_int(sys_kv.get("memo.prompt.min_chars") if isinstance(sys_kv, dict) else None, 30)
    min_chars = max(0, min(500, int(min_chars)))
    return {
        "enabled": bool(enabled),
        "require_subject": bool(require_subject),
        "require_group": bool(require_group),
        "require_details": bool(require_details),
        "min_chars": min_chars,
    }


def needs_enrich(*, memo: str, subject: str, group: str, cfg: dict[str, Any]) -> dict[str, bool]:
    m = str(memo or "").strip()
    s = str(subject or "").strip()
    g = str(group or "").strip()
    need_subject = bool(cfg.get("require_subject")) and not s
    need_group = bool(cfg.get("require_group")) and not g
    need_details = bool(cfg.get("require_details")) and (len(m) < int(cfg.get("min_chars") or 0))
    return {"subject": need_subject, "group": need_group, "details": need_details}


async def enrich_prompt(
    ws: Any,
    *,
    ws_send_json: Callable[[Any, dict[str, Any]], Awaitable[None]],
    live_say: Callable[[Any, str], Awaitable[None]],
    instance_id: str,
) -> None:
    pending = getattr(ws.state, "pending_memo_enrich", None)
    if not isinstance(pending, dict):
        return
    need = pending.get("need") if isinstance(pending.get("need"), dict) else {}
    lang = str(getattr(ws.state, "user_lang", "") or "").strip().lower()

    prompt = ""
    if need.get("subject"):
        prompt = "หัวข้อเมโมคืออะไร?" if lang.startswith("th") else "What is the memo subject/title?"
    elif need.get("group"):
        prompt = (
            "เมโมนี้อยู่กลุ่มไหน? (เช่น ops/work/personal)"
            if lang.startswith("th")
            else "Which group/category is this memo? (e.g. ops/work/personal)"
        )
    elif need.get("details"):
        prompt = "เพิ่มรายละเอียดอีกนิดได้ไหม?" if lang.startswith("th") else "Can you add a bit more detail?"
    if not prompt:
        return

    try:
        await ws_send_json(ws, {"type": "text", "text": prompt, "instance_id": instance_id})
    except Exception:
        pass
    try:
        await live_say(ws, prompt)
    except Exception:
        pass
