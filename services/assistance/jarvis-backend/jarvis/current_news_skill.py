from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from fastapi import WebSocket


async def handle_current_news_trigger(
    ws: WebSocket,
    text: str,
    *,
    get_cached_ctx: Callable[[], Optional[dict[str, Any]]],
    refresh_ctx: Callable[[bool], Awaitable[dict[str, Any]]],
    render_brief: Callable[[dict[str, Any]], str],
) -> bool:
    s = " ".join(str(text or "").strip().lower().split())
    if not s:
        return False

    wants_refresh = any(
        p in s
        for p in (
            "refresh current news",
            "current news refresh",
            "refresh news",
            "update current news",
            "current news update",
            "อัปเดตข่าวปัจจุบัน",
            "อัปเดตข่าว",
            "รีเฟรชข่าว",
            "รีเฟรช ข่าว",
            "ข่าวปัจจุบัน อัปเดต",
            "ข่าวปัจจุบันอัปเดต",
        )
    )
    wants_sources = "list sources" in s or s == "sources"
    wants_details = s.startswith("details ") or s.startswith("detail ")
    is_trigger = (
        ("current news" in s)
        or ("cnn news" in s)
        or ("thai baht" in s)
        or (" baht" in f" {s}")
        or ("thb" in s)
        or wants_refresh
        or wants_details
        or wants_sources
    )
    if not is_trigger:
        return False

    ctx = get_cached_ctx()
    if wants_refresh or ctx is None:
        ctx = await refresh_ctx(bool(wants_refresh))

    if not isinstance(ctx, dict):
        return False

    if wants_sources:
        await ws.send_json(
            {
                "type": "current_news_sources",
                "sources": ctx.get("sources") or [],
                "updated_at": ctx.get("updated_at"),
            }
        )
        return True

    if wants_details:
        topic = str(s.split(" ", 1)[1] if " " in s else "").strip()
        topics = ctx.get("topics") if isinstance(ctx.get("topics"), dict) else {}
        key_map = {
            "iran": "iran_war",
            "iran war": "iran_war",
            "war": "iran_war",
            "gold": "gold",
            "dollar": "usd",
            "usd": "usd",
            "oil": "oil",
            "baht": "thb",
            "thai baht": "thb",
            "thb": "thb",
            "usd/thb": "thb",
        }
        chosen = key_map.get(topic, "")
        if chosen and isinstance(topics, dict) and isinstance(topics.get(chosen), dict):
            await ws.send_json(
                {"type": "current_news_details", "topic": chosen, "data": topics.get(chosen), "updated_at": ctx.get("updated_at")}
            )
        else:
            await ws.send_json(
                {
                    "type": "current_news_details",
                    "topic": topic,
                    "error": "unknown_topic",
                    "hint": "Try: details iran | details gold | details usd | details oil",
                }
            )
        return True

    brief = render_brief(ctx)
    await ws.send_json({"type": "current_news", "brief": brief, "context": ctx, "updated_at": ctx.get("updated_at")})
    return True
