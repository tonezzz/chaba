from __future__ import annotations

from typing import Any, Awaitable, Callable


async def render_daily_brief(
    user_id: str,
    *,
    agents_snapshot: Callable[[], dict[str, Any]],
    get_agent_statuses: Callable[[str], list[dict[str, Any]]],
    weaviate_enabled: Callable[[], bool],
    weaviate_query_upcoming_reminders: Callable[..., Awaitable[list[dict[str, Any]]]],
    list_upcoming_pending_reminders: Callable[..., list[dict[str, Any]]],
    get_user_timezone: Callable[[str], Any],
    now_ts: Callable[[], int],
    datetime_now_iso: Callable[[Any], str],
    datetime_from_ts_iso_utc: Callable[[int], str],
) -> dict[str, Any]:
    agents = agents_snapshot()
    statuses = get_agent_statuses(user_id)
    status_by_agent: dict[str, dict[str, Any]] = {}
    for s in statuses:
        aid = str(s.get("agent_id") or "").strip()
        if aid and aid not in status_by_agent:
            status_by_agent[aid] = s

    now_ts_i = int(now_ts())
    upcoming_reminders: list[dict[str, Any]] = []
    if weaviate_enabled():
        try:
            upcoming_reminders = await weaviate_query_upcoming_reminders(
                start_ts=now_ts_i,
                end_ts=now_ts_i + 24 * 3600,
                limit=50,
            )
        except Exception:
            upcoming_reminders = []
    if not upcoming_reminders:
        upcoming_reminders = list_upcoming_pending_reminders(
            user_id=user_id,
            start_ts=now_ts_i,
            end_ts=now_ts_i + 24 * 3600,
            time_field="notify_at",
            limit=50,
        )

    lines: list[str] = []
    tz = get_user_timezone(user_id)
    lines.append(f"Daily Brief ({datetime_now_iso(tz)})")

    lines.append("\nAgents")
    for agent_id in sorted(agents.keys()):
        name = str(agents[agent_id].get("name") or agent_id)
        s = status_by_agent.get(agent_id)
        if not s:
            lines.append(f"- {name}: no recent status")
            continue
        payload = s.get("payload")
        summary = ""
        if isinstance(payload, dict):
            summary = str(payload.get("summary") or payload.get("status") or "").strip()
        updated_at = int(s.get("updated_at") or 0)
        when = datetime_from_ts_iso_utc(updated_at) if updated_at else ""
        if summary:
            lines.append(f"- {name}: {summary} ({when})")
        else:
            lines.append(f"- {name}: updated ({when})")

    if upcoming_reminders:
        lines.append("\nReminders (next 24h)")
        for r in upcoming_reminders[:20]:
            title = str(r.get("title") or "").strip() or "Reminder"
            notify_at = r.get("notify_at")
            due_at = r.get("due_at")
            lines.append(f"- {title} (notify_at={notify_at}, due_at={due_at})")

    return {
        "user_id": user_id,
        "generated_at": int(now_ts()),
        "agent_count": len(agents),
        "status_count": len(statuses),
        "brief_text": "\n".join(lines).strip(),
    }
