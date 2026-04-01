from __future__ import annotations

import json
import asyncio
import os
import time
from typing import Any, Optional


def _json_loads_loose(raw: Any) -> Any:
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


def _normalize_projects_registry(obj: Any) -> list[dict[str, Any]]:
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


def _find_registry_match(registry: list[dict[str, Any]], *, name: str) -> dict[str, Any] | None:
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


def _header_index(values: Any) -> dict[str, int]:
    if not isinstance(values, list) or not values or not isinstance(values[0], list):
        return {}
    idx: dict[str, int] = {}
    for j, h in enumerate(values[0]):
        k = str(h or "").strip().lower()
        if k and k not in idx:
            idx[k] = int(j)
    return idx


def _set_row_value(row: list[Any], idx: dict[str, int], key: str, value: Any) -> None:
    k = str(key or "").strip().lower()
    if not k:
        return
    j = idx.get(k)
    if j is None:
        return
    if j >= len(row):
        row.extend([""] * (j + 1 - len(row)))
    row[j] = value


def _normalize_field_key(k: str) -> str:
    return str(k or "").strip().lower().replace(" ", "_")


def _col_letter(col_idx0: int) -> str:
    n = int(col_idx0) + 1
    if n <= 0:
        return "A"
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(ord("A") + r) + out
    return out or "A"


async def handle_mcp_tool_call(session_id: Optional[str], tool_name: str, args: dict[str, Any], *, deps: dict[str, Any]) -> Any:
    HTTPException = deps["HTTPException"]

    async def _emit_pending_awaiting_user(*, session_id0: str, confirmation_id: str, action: str, payload: Any) -> None:
        try:
            session_ws0 = deps.get("SESSION_WS")
            if not isinstance(session_ws0, dict):
                return
            ws0 = session_ws0.get(str(session_id0))
            if ws0 is None:
                return
            await ws0.send_json(
                {
                    "type": "pending_event",
                    "event": "awaiting_user",
                    "confirmation_id": str(confirmation_id),
                    "action": str(action or ""),
                    "payload": payload,
                }
            )
        except Exception:
            return

    if tool_name in {"memo_update_queue", "system_memo_update_queue"}:
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        session_ws = deps["SESSION_WS"]
        feature_enabled = deps["feature_enabled"]
        sys_kv_bool = deps["sys_kv_bool"]
        safe_int = deps["safe_int"]
        create_pending_write = deps["create_pending_write"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        sys_kv = getattr(ws.state, "sys_kv", None)
        if not feature_enabled("memo", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
            raise HTTPException(status_code=403, detail="feature_disabled:memo")
        if not sys_kv_bool(sys_kv, "memo.enabled", False):
            raise HTTPException(status_code=403, detail="memo_disabled")

        memo_id = safe_int(args.get("id"), 0)
        if memo_id <= 0:
            raise HTTPException(status_code=400, detail="missing_id")

        proposed: dict[str, Any] = {"id": int(memo_id)}
        for k in ("memo", "group", "subject", "status", "result"):
            if k in args and args.get(k) is not None:
                proposed[k] = str(args.get(k) or "")
        if "active" in args and args.get("active") is not None:
            proposed["active"] = bool(args.get("active"))

        confirmation_id = create_pending_write(str(session_id), "memo_update", proposed)
        await _emit_pending_awaiting_user(session_id0=str(session_id), confirmation_id=confirmation_id, action="memo_update", payload=proposed)
        return {"ok": True, "queued": True, "confirmation_id": confirmation_id, "id": int(memo_id)}

    if tool_name == "news_feedback":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        session_ws = deps["SESSION_WS"]
        feature_enabled = deps["feature_enabled"]
        record_news_usage_event = deps["record_news_usage_event"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")
        sys_kv = getattr(ws.state, "sys_kv", None)
        if not feature_enabled("current-news", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
            raise HTTPException(status_code=403, detail="feature_disabled:current-news")

        label = str(args.get("label") or "").strip().lower()
        if label not in {"relevant", "irrelevant", "good_source", "bad_source"}:
            raise HTTPException(status_code=400, detail="invalid_label")

        payload = {
            "label": label,
            "link": str(args.get("link") or "").strip() or None,
            "title": str(args.get("title") or "").strip() or None,
            "topic": str(args.get("topic") or "").strip() or None,
            "source_url": str(args.get("source_url") or "").strip() or None,
        }
        ok = bool(record_news_usage_event(str(session_id), "news_feedback", payload))
        return {"ok": ok, "recorded": ok, "event_type": "news_feedback", "payload": payload}

    if tool_name == "news_tuning_suggest":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        session_ws = deps["SESSION_WS"]
        feature_enabled = deps["feature_enabled"]
        list_news_usage_events = deps["list_news_usage_events"]
        load_news_topics_from_sheet = deps.get("load_news_topics_from_sheet")
        load_news_sources_from_sheet = deps.get("load_news_sources_from_sheet")
        create_pending_write = deps["create_pending_write"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")
        sys_kv = getattr(ws.state, "sys_kv", None)
        if not feature_enabled("current-news", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
            raise HTTPException(status_code=403, detail="feature_disabled:current-news")

        limit_events = args.get("limit_events")
        try:
            lim = int(limit_events) if limit_events is not None else 200
        except Exception:
            lim = 200
        lim = max(1, min(lim, 2000))
        events = list_news_usage_events(str(session_id), limit=lim)

        # SSOT: load current sheet config (including disabled) so we can make safe proposals.
        sheet_topics: dict[str, dict[str, Any]] = {}
        sheet_sources: list[dict[str, Any]] = []
        try:
            if load_news_topics_from_sheet is not None:
                sheet_topics = await load_news_topics_from_sheet(sys_kv=sys_kv if isinstance(sys_kv, dict) else None, include_disabled=True)
        except Exception:
            sheet_topics = {}
        try:
            if load_news_sources_from_sheet is not None:
                sheet_sources = await load_news_sources_from_sheet(sys_kv=sys_kv if isinstance(sys_kv, dict) else None, include_disabled=True)
        except Exception:
            sheet_sources = []

        existing_source_urls: set[str] = set()
        existing_sources_by_url: dict[str, dict[str, Any]] = {}
        for s in sheet_sources:
            if not isinstance(s, dict):
                continue
            u0 = str(s.get("url") or "").strip()
            if not u0:
                continue
            key = u0.lower()
            existing_source_urls.add(key)
            if key not in existing_sources_by_url:
                existing_sources_by_url[key] = s

        # Heuristics: turn explicit feedback + usage signals into proposed sheet changes.
        good_sources: set[str] = set()
        bad_sources: set[str] = set()
        unknown_topics: dict[str, int] = {}
        for ev in events:
            if not isinstance(ev, dict):
                continue

            et = str(ev.get("event_type") or "").strip()
            p = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
            if et == "news_feedback":
                label = str(p.get("label") or "").strip().lower()
                src = str(p.get("source_url") or "").strip()
                if src:
                    if label == "good_source":
                        good_sources.add(src)
                    if label == "bad_source":
                        bad_sources.add(src)
                continue

            if et == "news_usage":
                tool = str(p.get("tool") or "").strip()
                if tool == "current_news_details":
                    found = p.get("found")
                    topic0 = str(p.get("topic") or "").strip()
                    if (found is False) and topic0:
                        unknown_topics[topic0] = int(unknown_topics.get(topic0, 0) or 0) + 1

        proposed_sources: list[dict[str, Any]] = []
        for u in sorted(good_sources):
            proposed_sources.append({"url": u, "enabled": True})
        for u in sorted(bad_sources):
            key = u.lower()
            if key in existing_source_urls:
                # Safe policy: do not attempt to disable existing rows.
                continue
            # Safe: append as disabled suggestion only.
            proposed_sources.append({"url": u, "enabled": False})

        proposed_topics: list[dict[str, Any]] = []
        # Propose creating missing topics as disabled (safe). Use a conservative keyword set.
        for raw_topic, count in sorted(unknown_topics.items(), key=lambda it: (-int(it[1] or 0), str(it[0] or ""))):
            if count <= 0:
                continue
            t0 = str(raw_topic or "").strip()
            if not t0:
                continue

            # If the user typed an existing topic key but it's disabled, propose enabling it.
            existing = sheet_topics.get(t0) if isinstance(sheet_topics, dict) else None
            if isinstance(existing, dict):
                if existing.get("enabled") is False:
                    kw0 = existing.get("keywords") if isinstance(existing.get("keywords"), list) else []
                    proposed_topics.append({"topic": t0, "keywords": [str(x or "").strip() for x in kw0 if str(x or "").strip()], "enabled": True})
                continue

            # Otherwise: propose a new topic row as disabled.
            topic_key = "_".join([w for w in re.sub(r"[^a-zA-Z0-9]+", " ", t0).strip().lower().split() if w])
            if not topic_key:
                topic_key = re.sub(r"\s+", "_", t0.strip().lower())
            topic_key = re.sub(r"[^a-z0-9_]+", "_", topic_key).strip("_")
            if not topic_key:
                continue
            if topic_key in sheet_topics:
                continue
            proposed_topics.append({"topic": topic_key, "keywords": [t0], "enabled": False})

        proposed: dict[str, Any] = {
            "topics": proposed_topics,
            "sources": proposed_sources,
            "based_on": {
                "events_considered": len(events),
                "unknown_topics": [{"topic": k, "count": int(v)} for k, v in sorted(unknown_topics.items(), key=lambda it: (-int(it[1] or 0), str(it[0] or "")))][:50],
            },
            "ssot": {
                "topics_count": len(sheet_topics) if isinstance(sheet_topics, dict) else 0,
                "sources_count": len(sheet_sources) if isinstance(sheet_sources, list) else 0,
            },
        }

        confirmation_id = create_pending_write(str(session_id), "news_tuning_apply", proposed)
        await _emit_pending_awaiting_user(session_id0=str(session_id), confirmation_id=confirmation_id, action="news_tuning_apply", payload=proposed)
        return {"ok": True, "queued": True, "confirmation_id": confirmation_id, "proposed": proposed}

    if tool_name == "system_skill_upsert_queue":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        session_ws = deps["SESSION_WS"]
        feature_enabled = deps["feature_enabled"]
        safe_int = deps["safe_int"]
        create_pending_write = deps["create_pending_write"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        sys_kv = getattr(ws.state, "sys_kv", None)
        if not feature_enabled("skills", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=False):
            raise HTTPException(status_code=403, detail="feature_disabled:skills")

        name = str(args.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="missing_name")

        enabled_raw = args.get("enabled")
        enabled = True if enabled_raw is None else bool(enabled_raw)
        priority = int(safe_int(args.get("priority"), 0))
        scope = str(args.get("scope") or "global").strip() or "global"
        content = str(args.get("content") or "")
        if not content.strip():
            raise HTTPException(status_code=400, detail="missing_content")

        payload = {
            "name": name,
            "enabled": bool(enabled),
            "priority": int(priority),
            "scope": scope,
            "content": content,
        }
        confirmation_id = create_pending_write(str(session_id), "skill_upsert", payload)
        await _emit_pending_awaiting_user(session_id0=str(session_id), confirmation_id=confirmation_id, action="skill_upsert", payload=payload)
        return {"ok": True, "queued": True, "confirmation_id": confirmation_id, "name": name}

    if tool_name == "system_write_queue":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        session_ws = deps["SESSION_WS"]
        create_pending_write = deps["create_pending_write"]
        safe_int = deps["safe_int"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        action = str(args.get("action") or "").strip()
        payload = args.get("payload")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid_payload")

        allowlisted = {
            "system_reload",
            "bundle_publish_macro_reload",
            "bundle_seed_macros",
            "bundle_bootstrap_skills",
            "bundle_bootstrap_news_skills",
            "google_account_relink",
            "memo_update",
            "skill_upsert",
        }

        supported_actions = {
            "system_reload": {
                "payload": {"mode": "full|macros|macros_only"},
                "notes": "Queues a system reload (pending_confirm required).",
            },
            "bundle_publish_macro_reload": {
                "payload": {"macro": {"name": "...", "enabled": True, "steps": []}, "reload_mode": "full|macros|macros_only"},
                "notes": "Publishes macro row then reloads (pending_confirm required).",
            },
            "bundle_seed_macros": {
                "payload": {"macros": [{"name": "...", "steps": []}], "reload_mode": "full|macros|macros_only"},
                "notes": "Seeds macros then reloads (pending_confirm required).",
            },
            "bundle_bootstrap_skills": {
                "payload": {"spreadsheet_id": "...", "sheet_name": "skills", "seed_name": "skill_ping"},
                "notes": "Creates/initializes skills tab + seed row then reloads.",
            },
            "bundle_bootstrap_news_skills": {
                "payload": {"seed_name": "jarvis-news-skill-smoke-test"},
                "notes": "Creates/initializes dedicated news skills tab (configured via sys_kv) + seed row then reloads.",
            },
            "google_account_relink": {
                "payload": {"auth_url": "...", "redirect_uri": "...", "token_path": "...", "scopes": []},
                "notes": "Queues relink flow; confirm step expects pasted redirected url/code.",
            },
            "memo_update": {
                "payload": {"id": 123, "memo": "...", "group": "...", "subject": "...", "status": "...", "result": "...", "active": True},
                "notes": "Updates a memo row by stable id (pending_confirm required).",
            },
            "skill_upsert": {
                "payload": {"name": "...", "enabled": True, "priority": 10, "scope": "global", "content": "..."},
                "notes": "Upserts a row in the skills sheet by name (pending_confirm required).",
            },
        }

        if (not action) or action.lower() in {"help", "list", "supported"}:
            return {"ok": True, "supported_actions": supported_actions}
        if action not in allowlisted:
            raise HTTPException(status_code=400, detail={"error": "action_not_allowed", "action": action})

        # Minimal per-action validation to prevent footguns.
        if action == "system_reload":
            mode = str(payload.get("mode") or "full").strip().lower() or "full"
            if mode not in {"full", "macros", "macros_only"}:
                raise HTTPException(status_code=400, detail={"error": "invalid_mode", "mode": mode})
            payload = {"mode": mode}
        elif action == "bundle_publish_macro_reload":
            macro = payload.get("macro")
            if not isinstance(macro, dict):
                raise HTTPException(status_code=400, detail="missing_macro")
            macro_name = str(macro.get("name") or "").strip()
            if not macro_name:
                raise HTTPException(status_code=400, detail="missing_macro_name")
        elif action == "bundle_seed_macros":
            macros = payload.get("macros")
            if not isinstance(macros, list) or not macros:
                raise HTTPException(status_code=400, detail="missing_macros")
        elif action == "google_account_relink":
            auth_url = str(payload.get("auth_url") or "").strip()
            redirect_uri = str(payload.get("redirect_uri") or "").strip()
            token_path = str(payload.get("token_path") or "").strip()
            if not auth_url or not redirect_uri or not token_path:
                raise HTTPException(status_code=400, detail="missing_relink_fields")
        elif action == "memo_update":
            memo_id = safe_int(payload.get("id"), 0)
            if memo_id <= 0:
                raise HTTPException(status_code=400, detail="missing_id")
            proposed: dict[str, Any] = {"id": int(memo_id)}
            for k in ("memo", "group", "subject", "status", "result"):
                if k in payload and payload.get(k) is not None:
                    proposed[k] = str(payload.get(k) or "")
            if "active" in payload and payload.get("active") is not None:
                proposed["active"] = bool(payload.get("active"))
            payload = proposed
        elif action == "skill_upsert":
            name = str(payload.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="missing_name")
            content = str(payload.get("content") or "")
            if not content.strip():
                raise HTTPException(status_code=400, detail="missing_content")
            enabled_raw = payload.get("enabled")
            enabled = True if enabled_raw is None else bool(enabled_raw)
            priority = int(safe_int(payload.get("priority"), 0))
            scope = str(payload.get("scope") or "global").strip() or "global"
            payload = {
                "name": name,
                "enabled": bool(enabled),
                "priority": int(priority),
                "scope": scope,
                "content": content,
            }

        confirmation_id = create_pending_write(str(session_id), action, payload)
        await _emit_pending_awaiting_user(session_id0=str(session_id), confirmation_id=confirmation_id, action=action, payload=payload)
        return {
            "ok": True,
            "queued": True,
            "confirmation_id": confirmation_id,
            "action": action,
            "supported_actions": supported_actions,
        }

    if tool_name == "projects_registry_list":
        session_ws = deps["SESSION_WS"]
        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        namespace = str(args.get("namespace") or "").strip()
        if not namespace:
            raise HTTPException(status_code=400, detail="missing_namespace")

        sys_kv = getattr(ws.state, "sys_kv", None)
        sys_kv_dict = sys_kv if isinstance(sys_kv, dict) else None
        if not sys_kv_dict:
            raise HTTPException(status_code=400, detail="missing_sys_kv")

        reg_key = f"projects.{namespace}.projects_json"
        raw = sys_kv_dict.get(reg_key)
        parsed = _json_loads_loose(raw)
        items = _normalize_projects_registry(parsed)
        active_id = str(sys_kv_dict.get(f"projects.{namespace}.active_id") or "").strip() or None
        return {"ok": True, "namespace": namespace, "active_id": active_id, "items": items, "count": len(items)}

    if tool_name == "projects_sheet_read":
        session_ws = deps["SESSION_WS"]
        pick_sheets_tool_name = deps["pick_sheets_tool_name"]
        mcp_tools_call = deps["mcp_tools_call"]
        mcp_text_json = deps["mcp_text_json"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        namespace = str(args.get("namespace") or "").strip()
        if not namespace:
            raise HTTPException(status_code=400, detail="missing_namespace")

        tab = str(args.get("tab") or "").strip()
        if not tab:
            raise HTTPException(status_code=400, detail="missing_tab")

        spreadsheet_id = str(args.get("spreadsheet_id") or "").strip()
        project_name = str(args.get("project_name") or args.get("name") or "").strip()
        a1_range = str(args.get("range") or "").strip()
        if not a1_range:
            a1_range = f"{tab}!A:Z"

        sys_kv = getattr(ws.state, "sys_kv", None)
        sys_kv_dict = sys_kv if isinstance(sys_kv, dict) else None
        if not sys_kv_dict:
            raise HTTPException(status_code=400, detail="missing_sys_kv")

        if not spreadsheet_id:
            active_id = str(sys_kv_dict.get(f"projects.{namespace}.active_id") or "").strip()
            if active_id:
                spreadsheet_id = active_id

        if not spreadsheet_id and project_name:
            reg_key = f"projects.{namespace}.projects_json"
            reg = _normalize_projects_registry(_json_loads_loose(sys_kv_dict.get(reg_key)))
            hit = _find_registry_match(reg, name=project_name)
            if hit is not None:
                spreadsheet_id = str(hit.get("spreadsheet_id") or "").strip()

        if not spreadsheet_id:
            raise HTTPException(status_code=400, detail="missing_spreadsheet_id")

        tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
        res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": a1_range})
        parsed = mcp_text_json(res)
        if isinstance(parsed, dict) and isinstance(parsed.get("data"), dict) and "values" not in parsed:
            # mcp-google-sheets wraps google payload under data; normalize.
            data_obj = parsed.get("data")
            if isinstance(data_obj, dict) and "values" in data_obj:
                parsed = {"ok": True, "data": data_obj, "values": data_obj.get("values")}
        values = parsed.get("values") if isinstance(parsed, dict) else None
        return {"ok": True, "namespace": namespace, "spreadsheet_id": spreadsheet_id, "range": a1_range, "values": values}

    if tool_name in {
        "projects_instructions_read",
        "projects_dictionary_read",
        "projects_schema_registry_read",
        "projects_entities_read",
        "projects_relations_read",
        "projects_proposals_read",
        "projects_changelog_read",
    }:
        alias_to_tab = {
            "projects_instructions_read": "instructions",
            "projects_dictionary_read": "dictionary",
            "projects_schema_registry_read": "schema_registry",
            "projects_entities_read": "entities",
            "projects_relations_read": "relations",
            "projects_proposals_read": "proposals",
            "projects_changelog_read": "changelog",
        }
        tab0 = alias_to_tab.get(tool_name, "")
        forwarded = dict(args or {})
        forwarded.setdefault("tab", tab0)
        return await handle_mcp_tool_call(session_id, "projects_sheet_read", forwarded, deps=deps)

    if tool_name == "projects_proposal_start_project":
        session_ws = deps["SESSION_WS"]
        pick_sheets_tool_name = deps["pick_sheets_tool_name"]
        mcp_tools_call = deps["mcp_tools_call"]
        mcp_text_json = deps["mcp_text_json"]
        create_pending_write = deps.get("create_pending_write")

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        namespace = str(args.get("namespace") or "").strip()
        if not namespace:
            raise HTTPException(status_code=400, detail="missing_namespace")

        new_project_title = str(args.get("new_project_title") or args.get("project_title") or args.get("title") or "").strip()
        if not new_project_title:
            raise HTTPException(status_code=400, detail="missing_new_project_title")

        objective = str(args.get("objective") or "").strip()
        priority = str(args.get("priority") or "").strip()
        due_date = str(args.get("due_date") or "").strip()
        seed_tasks = args.get("seed_tasks")
        if seed_tasks is None:
            seed_tasks = []
        if not isinstance(seed_tasks, list):
            raise HTTPException(status_code=400, detail="invalid_seed_tasks")

        spreadsheet_id = str(args.get("spreadsheet_id") or "").strip()
        project_name = str(args.get("project_name") or args.get("name") or "").strip()

        sys_kv = getattr(ws.state, "sys_kv", None)
        sys_kv_dict = sys_kv if isinstance(sys_kv, dict) else None
        if not sys_kv_dict:
            raise HTTPException(status_code=400, detail="missing_sys_kv")

        if not spreadsheet_id:
            active_id = str(sys_kv_dict.get(f"projects.{namespace}.active_id") or "").strip()
            if active_id:
                spreadsheet_id = active_id

        if not spreadsheet_id and project_name:
            reg_key = f"projects.{namespace}.projects_json"
            reg = _normalize_projects_registry(_json_loads_loose(sys_kv_dict.get(reg_key)))
            hit = _find_registry_match(reg, name=project_name)
            if hit is not None:
                spreadsheet_id = str(hit.get("spreadsheet_id") or "").strip()

        if not spreadsheet_id:
            raise HTTPException(status_code=400, detail="missing_spreadsheet_id")

        # Build payload and append a proposal row (robust to schema differences).
        payload = {
            "action": "start_project",
            "new_project_title": new_project_title,
            "objective": objective or None,
            "priority": priority or None,
            "due_date": due_date or None,
            "seed_tasks": [str(x or "").strip() for x in seed_tasks if str(x or "").strip()],
        }

        tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
        header_res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": "proposals!A1:Z1"})
        header_parsed = mcp_text_json(header_res)
        header_values = None
        if isinstance(header_parsed, dict):
            header_values = header_parsed.get("values")
            if header_values is None and isinstance(header_parsed.get("data"), dict):
                header_values = header_parsed.get("data", {}).get("values")
        idx = _header_index(header_values)

        row: list[Any] = [""] * (max(idx.values()) + 1) if idx else []
        _set_row_value(row, idx, "created_at", "")
        _set_row_value(row, idx, "created", "")
        _set_row_value(row, idx, "ts", "")
        _set_row_value(row, idx, "kind", "start_project")
        _set_row_value(row, idx, "type", "start_project")
        _set_row_value(row, idx, "title", new_project_title)
        _set_row_value(row, idx, "project_title", new_project_title)
        _set_row_value(row, idx, "objective", objective)
        _set_row_value(row, idx, "priority", priority)
        _set_row_value(row, idx, "due_date", due_date)
        _set_row_value(row, idx, "payload_json", json.dumps(payload, ensure_ascii=False))
        _set_row_value(row, idx, "status", "proposed")

        if not row:
            row = ["", "start_project", new_project_title, json.dumps(payload, ensure_ascii=False), "proposed"]

        tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
        if not create_pending_write:
            raise HTTPException(status_code=500, detail="missing_create_pending_write")

        pending_payload = {
            "mcp_name": tool_append,
            "arguments": {
                "spreadsheet_id": spreadsheet_id,
                "range": "proposals!A:Z",
                "values": [row],
                "value_input_option": "USER_ENTERED",
                "insert_data_option": "INSERT_ROWS",
            },
            "mcp_base": "",
            "tool_name": "projects_proposal_start_project",
        }
        confirmation_id = create_pending_write(str(session_id), action="mcp_tools_call", payload=pending_payload)
        await _emit_pending_awaiting_user(
            session_id0=str(session_id),
            confirmation_id=confirmation_id,
            action="mcp_tools_call",
            payload=pending_payload,
        )
        return {
            "ok": True,
            "queued": True,
            "confirmation_id": confirmation_id,
            "namespace": namespace,
            "spreadsheet_id": spreadsheet_id,
            "proposal": payload,
        }

    if tool_name == "projects_entities_append_queue":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        session_ws = deps["SESSION_WS"]
        pick_sheets_tool_name = deps["pick_sheets_tool_name"]
        mcp_tools_call = deps["mcp_tools_call"]
        mcp_text_json = deps["mcp_text_json"]
        create_pending_write = deps.get("create_pending_write")
        if not create_pending_write:
            raise HTTPException(status_code=500, detail="missing_create_pending_write")

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        namespace = str(args.get("namespace") or "").strip()
        if not namespace:
            raise HTTPException(status_code=400, detail="missing_namespace")

        spreadsheet_id = str(args.get("spreadsheet_id") or "").strip()
        project_name = str(args.get("project_name") or args.get("name") or "").strip()

        sys_kv = getattr(ws.state, "sys_kv", None)
        sys_kv_dict = sys_kv if isinstance(sys_kv, dict) else None
        if not sys_kv_dict:
            raise HTTPException(status_code=400, detail="missing_sys_kv")

        if not spreadsheet_id:
            active_id = str(sys_kv_dict.get(f"projects.{namespace}.active_id") or "").strip()
            if active_id:
                spreadsheet_id = active_id

        if not spreadsheet_id and project_name:
            reg_key = f"projects.{namespace}.projects_json"
            reg = _normalize_projects_registry(_json_loads_loose(sys_kv_dict.get(reg_key)))
            hit = _find_registry_match(reg, name=project_name)
            if hit is not None:
                spreadsheet_id = str(hit.get("spreadsheet_id") or "").strip()

        if not spreadsheet_id:
            raise HTTPException(status_code=400, detail="missing_spreadsheet_id")

        fields_in = args.get("fields")
        entity_in = args.get("entity")
        if fields_in is None and isinstance(entity_in, dict):
            fields_in = entity_in
        if not isinstance(fields_in, dict) or not fields_in:
            raise HTTPException(status_code=400, detail="missing_fields")

        # Load header from entities tab to map fields -> columns.
        tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
        header_res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": "entities!A1:Z1"})
        header_parsed = mcp_text_json(header_res)
        header_values = None
        if isinstance(header_parsed, dict):
            header_values = header_parsed.get("values")
            if header_values is None and isinstance(header_parsed.get("data"), dict):
                header_values = header_parsed.get("data", {}).get("values")
        idx = _header_index(header_values)
        if not idx:
            raise HTTPException(status_code=400, detail="entities_sheet_missing_header")

        row: list[Any] = [""] * (max(idx.values()) + 1)

        # Common aliases.
        aliases = {
            "id": ["id", "entity_id"],
            "name": ["name", "title", "entity_name"],
            "type": ["type", "entity_type", "kind"],
            "notes": ["notes", "note", "description", "desc"],
            "status": ["status", "state"],
            "tags": ["tags", "tag"],
            "source": ["source"],
            "external_id": ["external_id", "ext_id"],
            "parent_id": ["parent_id", "parent", "parent_entity_id"],
        }

        # Apply direct header-matching keys first.
        for k, v in fields_in.items():
            kk = _normalize_field_key(str(k))
            if kk in idx:
                _set_row_value(row, idx, kk, v)

        # Apply aliases.
        for _, keys in aliases.items():
            val: Any = None
            found_key = ""
            for k in keys:
                if k in fields_in and fields_in.get(k) is not None:
                    val = fields_in.get(k)
                    found_key = k
                    break
                # also check normalized variants
                for src_k in list(fields_in.keys()):
                    if _normalize_field_key(str(src_k)) == k and fields_in.get(src_k) is not None:
                        val = fields_in.get(src_k)
                        found_key = str(src_k)
                        break
                if found_key:
                    break
            if found_key and val is not None:
                for dest in keys:
                    if dest in idx:
                        _set_row_value(row, idx, dest, val)
                        break

        # If the sheet supports payload_json, store the original fields.
        if "payload_json" in idx and row[idx["payload_json"]] in (None, ""):
            _set_row_value(row, idx, "payload_json", json.dumps(fields_in, ensure_ascii=False))

        tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
        pending_payload = {
            "mcp_name": tool_append,
            "arguments": {
                "spreadsheet_id": spreadsheet_id,
                "range": "entities!A:Z",
                "values": [row],
                "value_input_option": "USER_ENTERED",
                "insert_data_option": "INSERT_ROWS",
            },
            "mcp_base": "",
            "tool_name": "projects_entities_append_queue",
        }
        confirmation_id = create_pending_write(str(session_id), action="mcp_tools_call", payload=pending_payload)
        await _emit_pending_awaiting_user(
            session_id0=str(session_id),
            confirmation_id=confirmation_id,
            action="mcp_tools_call",
            payload=pending_payload,
        )
        return {
            "ok": True,
            "queued": True,
            "confirmation_id": confirmation_id,
            "namespace": namespace,
            "spreadsheet_id": spreadsheet_id,
            "row": row,
        }

    if tool_name == "projects_entities_update_by_id_queue":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        session_ws = deps["SESSION_WS"]
        pick_sheets_tool_name = deps["pick_sheets_tool_name"]
        mcp_tools_call = deps["mcp_tools_call"]
        mcp_text_json = deps["mcp_text_json"]
        create_pending_write = deps.get("create_pending_write")
        if not create_pending_write:
            raise HTTPException(status_code=500, detail="missing_create_pending_write")

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        namespace = str(args.get("namespace") or "").strip()
        if not namespace:
            raise HTTPException(status_code=400, detail="missing_namespace")

        spreadsheet_id = str(args.get("spreadsheet_id") or "").strip()
        project_name = str(args.get("project_name") or args.get("name") or "").strip()

        sys_kv = getattr(ws.state, "sys_kv", None)
        sys_kv_dict = sys_kv if isinstance(sys_kv, dict) else None
        if not sys_kv_dict:
            raise HTTPException(status_code=400, detail="missing_sys_kv")

        if not spreadsheet_id:
            active_id = str(sys_kv_dict.get(f"projects.{namespace}.active_id") or "").strip()
            if active_id:
                spreadsheet_id = active_id

        if not spreadsheet_id and project_name:
            reg_key = f"projects.{namespace}.projects_json"
            reg = _normalize_projects_registry(_json_loads_loose(sys_kv_dict.get(reg_key)))
            hit = _find_registry_match(reg, name=project_name)
            if hit is not None:
                spreadsheet_id = str(hit.get("spreadsheet_id") or "").strip()

        if not spreadsheet_id:
            raise HTTPException(status_code=400, detail="missing_spreadsheet_id")

        entity_id = str(args.get("id") or args.get("entity_id") or "").strip()
        if not entity_id:
            raise HTTPException(status_code=400, detail="missing_entity_id")

        fields_in = args.get("fields")
        entity_in = args.get("entity")
        if fields_in is None and isinstance(entity_in, dict):
            fields_in = entity_in
        if not isinstance(fields_in, dict) or not fields_in:
            raise HTTPException(status_code=400, detail="missing_fields")

        # Read entities sheet to locate row.
        tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
        max_rows = int(args.get("max_rows") or 0) if str(args.get("max_rows") or "").strip() else 0
        rng = "entities!A:Z" if max_rows <= 0 else f"entities!A1:Z{max_rows}"
        res0 = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": rng})
        parsed0 = mcp_text_json(res0)
        values = None
        if isinstance(parsed0, dict):
            values = parsed0.get("values")
            if values is None and isinstance(parsed0.get("data"), dict):
                values = parsed0.get("data", {}).get("values")
        if not isinstance(values, list) or not values:
            raise HTTPException(status_code=400, detail="entities_sheet_empty")

        idx = _header_index([values[0]] if isinstance(values[0], list) else None)
        if not idx:
            raise HTTPException(status_code=400, detail="entities_sheet_missing_header")

        id_col = None
        if "id" in idx:
            id_col = idx["id"]
        elif "entity_id" in idx:
            id_col = idx["entity_id"]
        if id_col is None:
            raise HTTPException(status_code=400, detail="entities_sheet_missing_id_column")

        found_row_num: int | None = None
        found_row: list[Any] | None = None
        for i, r in enumerate(values[1:], start=2):
            if not isinstance(r, list):
                continue
            rid = ""
            if id_col < len(r):
                rid = str(r[id_col] or "").strip()
            if rid == entity_id:
                found_row_num = int(i)
                found_row = r
                break
        if found_row_num is None or found_row is None:
            raise HTTPException(status_code=404, detail="entity_not_found")

        # Merge updates into existing row.
        max_col = max(idx.values())
        row_out: list[Any] = list(found_row) + ([""] * max(0, (max_col + 1) - len(found_row)))

        # Apply direct header-matching keys.
        for k, v in fields_in.items():
            kk = _normalize_field_key(str(k))
            if kk in idx:
                _set_row_value(row_out, idx, kk, v)

        # Common aliases (same mapping as append).
        aliases = {
            "id": ["id", "entity_id"],
            "name": ["name", "title", "entity_name"],
            "type": ["type", "entity_type", "kind"],
            "notes": ["notes", "note", "description", "desc"],
            "status": ["status", "state"],
            "tags": ["tags", "tag"],
            "source": ["source"],
            "external_id": ["external_id", "ext_id"],
            "parent_id": ["parent_id", "parent", "parent_entity_id"],
        }
        for _, keys in aliases.items():
            val: Any = None
            found_key = ""
            for k in keys:
                if k in fields_in and fields_in.get(k) is not None:
                    val = fields_in.get(k)
                    found_key = k
                    break
                for src_k in list(fields_in.keys()):
                    if _normalize_field_key(str(src_k)) == k and fields_in.get(src_k) is not None:
                        val = fields_in.get(src_k)
                        found_key = str(src_k)
                        break
                if found_key:
                    break
            if found_key and val is not None:
                for dest in keys:
                    if dest in idx:
                        _set_row_value(row_out, idx, dest, val)
                        break

        # Never allow changing the id via update; enforce it.
        if "id" in idx:
            row_out[idx["id"]] = entity_id
        if "entity_id" in idx:
            row_out[idx["entity_id"]] = entity_id

        start_col = _col_letter(0)
        end_col = _col_letter(max_col)
        tool_update = pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
        pending_payload = {
            "mcp_name": tool_update,
            "arguments": {
                "spreadsheet_id": spreadsheet_id,
                "range": f"entities!{start_col}{found_row_num}:{end_col}{found_row_num}",
                "values": [row_out[: (max_col + 1)]],
                "value_input_option": "USER_ENTERED",
            },
            "mcp_base": "",
            "tool_name": "projects_entities_update_by_id_queue",
        }
        confirmation_id = create_pending_write(str(session_id), action="mcp_tools_call", payload=pending_payload)
        await _emit_pending_awaiting_user(
            session_id0=str(session_id),
            confirmation_id=confirmation_id,
            action="mcp_tools_call",
            payload=pending_payload,
        )
        return {
            "ok": True,
            "queued": True,
            "confirmation_id": confirmation_id,
            "namespace": namespace,
            "spreadsheet_id": spreadsheet_id,
            "row": found_row_num,
            "entity_id": entity_id,
            "row_out": row_out[: (max_col + 1)],
        }

    if tool_name == "projects_relations_append_queue":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        session_ws = deps["SESSION_WS"]
        pick_sheets_tool_name = deps["pick_sheets_tool_name"]
        mcp_tools_call = deps["mcp_tools_call"]
        mcp_text_json = deps["mcp_text_json"]
        create_pending_write = deps.get("create_pending_write")
        if not create_pending_write:
            raise HTTPException(status_code=500, detail="missing_create_pending_write")

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        namespace = str(args.get("namespace") or "").strip()
        if not namespace:
            raise HTTPException(status_code=400, detail="missing_namespace")

        spreadsheet_id = str(args.get("spreadsheet_id") or "").strip()
        project_name = str(args.get("project_name") or args.get("name") or "").strip()

        sys_kv = getattr(ws.state, "sys_kv", None)
        sys_kv_dict = sys_kv if isinstance(sys_kv, dict) else None
        if not sys_kv_dict:
            raise HTTPException(status_code=400, detail="missing_sys_kv")

        if not spreadsheet_id:
            active_id = str(sys_kv_dict.get(f"projects.{namespace}.active_id") or "").strip()
            if active_id:
                spreadsheet_id = active_id

        if not spreadsheet_id and project_name:
            reg_key = f"projects.{namespace}.projects_json"
            reg = _normalize_projects_registry(_json_loads_loose(sys_kv_dict.get(reg_key)))
            hit = _find_registry_match(reg, name=project_name)
            if hit is not None:
                spreadsheet_id = str(hit.get("spreadsheet_id") or "").strip()

        if not spreadsheet_id:
            raise HTTPException(status_code=400, detail="missing_spreadsheet_id")

        fields_in = args.get("fields")
        rel_in = args.get("relation")
        if fields_in is None and isinstance(rel_in, dict):
            fields_in = rel_in
        if not isinstance(fields_in, dict) or not fields_in:
            raise HTTPException(status_code=400, detail="missing_fields")

        tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
        header_res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": "relations!A1:Z1"})
        header_parsed = mcp_text_json(header_res)
        header_values = None
        if isinstance(header_parsed, dict):
            header_values = header_parsed.get("values")
            if header_values is None and isinstance(header_parsed.get("data"), dict):
                header_values = header_parsed.get("data", {}).get("values")
        idx = _header_index(header_values)
        if not idx:
            raise HTTPException(status_code=400, detail="relations_sheet_missing_header")

        row: list[Any] = [""] * (max(idx.values()) + 1)

        # Direct header matches.
        for k, v in fields_in.items():
            kk = _normalize_field_key(str(k))
            if kk in idx:
                _set_row_value(row, idx, kk, v)

        # Common aliases.
        aliases = {
            "id": ["id", "relation_id"],
            "from_id": ["from_id", "src_id", "source_id", "parent_id", "a_id"],
            "to_id": ["to_id", "dst_id", "target_id", "child_id", "b_id"],
            "type": ["type", "relation_type", "kind"],
            "notes": ["notes", "note", "description", "desc"],
            "status": ["status", "state"],
            "tags": ["tags", "tag"],
            "source": ["source"],
            "external_id": ["external_id", "ext_id"],
        }

        for _, keys in aliases.items():
            val: Any = None
            found_key = ""
            for k in keys:
                if k in fields_in and fields_in.get(k) is not None:
                    val = fields_in.get(k)
                    found_key = k
                    break
                for src_k in list(fields_in.keys()):
                    if _normalize_field_key(str(src_k)) == k and fields_in.get(src_k) is not None:
                        val = fields_in.get(src_k)
                        found_key = str(src_k)
                        break
                if found_key:
                    break
            if found_key and val is not None:
                for dest in keys:
                    if dest in idx:
                        _set_row_value(row, idx, dest, val)
                        break

        if "payload_json" in idx and row[idx["payload_json"]] in (None, ""):
            _set_row_value(row, idx, "payload_json", json.dumps(fields_in, ensure_ascii=False))

        tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
        pending_payload = {
            "mcp_name": tool_append,
            "arguments": {
                "spreadsheet_id": spreadsheet_id,
                "range": "relations!A:Z",
                "values": [row],
                "value_input_option": "USER_ENTERED",
                "insert_data_option": "INSERT_ROWS",
            },
            "mcp_base": "",
            "tool_name": "projects_relations_append_queue",
        }
        confirmation_id = create_pending_write(str(session_id), action="mcp_tools_call", payload=pending_payload)
        await _emit_pending_awaiting_user(
            session_id0=str(session_id),
            confirmation_id=confirmation_id,
            action="mcp_tools_call",
            payload=pending_payload,
        )
        return {
            "ok": True,
            "queued": True,
            "confirmation_id": confirmation_id,
            "namespace": namespace,
            "spreadsheet_id": spreadsheet_id,
            "row": row,
        }

    if tool_name == "projects_proposals_apply_approved":
        session_ws = deps["SESSION_WS"]
        pick_sheets_tool_name = deps["pick_sheets_tool_name"]
        mcp_tools_call = deps["mcp_tools_call"]
        mcp_text_json = deps["mcp_text_json"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        namespace = str(args.get("namespace") or "").strip()
        if not namespace:
            raise HTTPException(status_code=400, detail="missing_namespace")

        spreadsheet_id = str(args.get("spreadsheet_id") or "").strip()
        project_name = str(args.get("project_name") or args.get("name") or "").strip()

        sys_kv = getattr(ws.state, "sys_kv", None)
        sys_kv_dict = sys_kv if isinstance(sys_kv, dict) else None
        if not sys_kv_dict:
            raise HTTPException(status_code=400, detail="missing_sys_kv")

        if not spreadsheet_id:
            active_id = str(sys_kv_dict.get(f"projects.{namespace}.active_id") or "").strip()
            if active_id:
                spreadsheet_id = active_id

        if not spreadsheet_id and project_name:
            reg_key = f"projects.{namespace}.projects_json"
            reg = _normalize_projects_registry(_json_loads_loose(sys_kv_dict.get(reg_key)))
            hit = _find_registry_match(reg, name=project_name)
            if hit is not None:
                spreadsheet_id = str(hit.get("spreadsheet_id") or "").strip()

        if not spreadsheet_id:
            raise HTTPException(status_code=400, detail="missing_spreadsheet_id")

        limit = int(args.get("limit") or 20) if str(args.get("limit") or "").strip() else 20
        limit = max(1, min(50, int(limit)))

        tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
        tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
        tool_update = pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")

        # Load proposals rows.
        res0 = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": "proposals!A:Z"})
        parsed0 = mcp_text_json(res0)
        values = None
        if isinstance(parsed0, dict):
            values = parsed0.get("values")
            if values is None and isinstance(parsed0.get("data"), dict):
                values = parsed0.get("data", {}).get("values")
        if not isinstance(values, list) or not values:
            return {"ok": True, "applied": 0, "skipped": 0, "message": "proposals_empty"}

        idxp = _header_index([values[0]] if isinstance(values[0], list) else None)
        if not idxp:
            raise HTTPException(status_code=400, detail="proposals_sheet_missing_header")

        def _cell(row: list[Any], col: str) -> Any:
            j = idxp.get(str(col or "").strip().lower())
            if j is None or j < 0 or j >= len(row):
                return ""
            return row[j]

        status_col = "status" if "status" in idxp else ("proposal_status" if "proposal_status" in idxp else "")
        if not status_col:
            raise HTTPException(status_code=400, detail="proposals_sheet_missing_status")
        status_j = idxp[status_col]

        payload_col = "payload_json" if "payload_json" in idxp else ("payload" if "payload" in idxp else "")
        kind_col = "kind" if "kind" in idxp else ("type" if "type" in idxp else "")
        title_col = "title" if "title" in idxp else ("project_title" if "project_title" in idxp else "")
        objective_col = "objective" if "objective" in idxp else ""
        priority_col = "priority" if "priority" in idxp else ""
        due_col = "due_date" if "due_date" in idxp else ""
        applied_at_col = "applied_at" if "applied_at" in idxp else ("applied" if "applied" in idxp else "")

        # Preload entities/relations headers.
        ent_header_res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": "entities!A1:Z1"})
        ent_header_parsed = mcp_text_json(ent_header_res)
        ent_header_values = None
        if isinstance(ent_header_parsed, dict):
            ent_header_values = ent_header_parsed.get("values")
            if ent_header_values is None and isinstance(ent_header_parsed.get("data"), dict):
                ent_header_values = ent_header_parsed.get("data", {}).get("values")
        idxe = _header_index(ent_header_values)

        rel_header_res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": "relations!A1:Z1"})
        rel_header_parsed = mcp_text_json(rel_header_res)
        rel_header_values = None
        if isinstance(rel_header_parsed, dict):
            rel_header_values = rel_header_parsed.get("values")
            if rel_header_values is None and isinstance(rel_header_parsed.get("data"), dict):
                rel_header_values = rel_header_parsed.get("data", {}).get("values")
        idxr = _header_index(rel_header_values)

        if not idxe:
            raise HTTPException(status_code=400, detail="entities_sheet_missing_header")
        if not idxr:
            raise HTTPException(status_code=400, detail="relations_sheet_missing_header")

        def _new_id(prefix: str) -> str:
            return f"{prefix}_{int(time.time())}_{os.urandom(3).hex()}"

        def _norm_status(v: Any) -> str:
            return str(v or "").strip().lower()

        applied = 0
        skipped = 0
        details: list[dict[str, Any]] = []

        for row_num, r in enumerate(values[1:], start=2):
            if applied >= limit:
                break
            if not isinstance(r, list):
                continue
            st = _norm_status(r[status_j] if status_j < len(r) else "")
            if st != "approved":
                continue

            payload: dict[str, Any] = {}
            if payload_col:
                raw = _cell(r, payload_col)
                if raw:
                    parsed = _json_loads_loose(raw)
                    if isinstance(parsed, dict):
                        payload = parsed

            action = str(payload.get("action") or "").strip().lower()
            if not action and kind_col:
                action = str(_cell(r, kind_col) or "").strip().lower()
            if action in {"start_project", "start project", "start-project"}:
                new_project_title = str(payload.get("new_project_title") or payload.get("project_title") or "").strip()
                if not new_project_title and title_col:
                    new_project_title = str(_cell(r, title_col) or "").strip()
                if not new_project_title:
                    skipped += 1
                    details.append({"row": row_num, "status": "skipped", "reason": "missing_project_title"})
                    continue

                objective = str(payload.get("objective") or "").strip()
                if not objective and objective_col:
                    objective = str(_cell(r, objective_col) or "").strip()
                priority = str(payload.get("priority") or "").strip()
                if not priority and priority_col:
                    priority = str(_cell(r, priority_col) or "").strip()
                due_date = str(payload.get("due_date") or "").strip()
                if not due_date and due_col:
                    due_date = str(_cell(r, due_col) or "").strip()
                seed_tasks = payload.get("seed_tasks")
                if not isinstance(seed_tasks, list):
                    seed_tasks = []
                seed_tasks = [str(x or "").strip() for x in seed_tasks if str(x or "").strip()]

                project_id = _new_id("project")
                entities_rows: list[list[Any]] = []

                def _entity_row(fields: dict[str, Any]) -> list[Any]:
                    row0: list[Any] = [""] * (max(idxe.values()) + 1)
                    for k, v in fields.items():
                        kk = _normalize_field_key(str(k))
                        if kk in idxe:
                            _set_row_value(row0, idxe, kk, v)
                    if "payload_json" in idxe and row0[idxe["payload_json"]] in (None, ""):
                        _set_row_value(row0, idxe, "payload_json", json.dumps(fields, ensure_ascii=False))
                    return row0

                entities_rows.append(
                    _entity_row(
                        {
                            "id": project_id,
                            "type": "project",
                            "name": new_project_title,
                            "objective": objective,
                            "priority": priority,
                            "due_date": due_date,
                            "status": "active",
                        }
                    )
                )

                rel_rows: list[list[Any]] = []

                def _rel_row(fields: dict[str, Any]) -> list[Any]:
                    row0: list[Any] = [""] * (max(idxr.values()) + 1)
                    for k, v in fields.items():
                        kk = _normalize_field_key(str(k))
                        if kk in idxr:
                            _set_row_value(row0, idxr, kk, v)
                    if "payload_json" in idxr and row0[idxr["payload_json"]] in (None, ""):
                        _set_row_value(row0, idxr, "payload_json", json.dumps(fields, ensure_ascii=False))
                    return row0

                for t in seed_tasks:
                    task_id = _new_id("task")
                    entities_rows.append(
                        _entity_row(
                            {
                                "id": task_id,
                                "type": "task",
                                "name": t,
                                "parent_id": project_id,
                                "status": "todo",
                            }
                        )
                    )
                    rel_rows.append(
                        _rel_row(
                            {
                                "from_id": project_id,
                                "to_id": task_id,
                                "type": "parent_of",
                                "status": "active",
                            }
                        )
                    )

                # Apply entities + relations.
                if entities_rows:
                    await mcp_tools_call(
                        tool_append,
                        {
                            "spreadsheet_id": spreadsheet_id,
                            "range": "entities!A:Z",
                            "values": entities_rows,
                            "value_input_option": "USER_ENTERED",
                            "insert_data_option": "INSERT_ROWS",
                        },
                    )
                if rel_rows:
                    await mcp_tools_call(
                        tool_append,
                        {
                            "spreadsheet_id": spreadsheet_id,
                            "range": "relations!A:Z",
                            "values": rel_rows,
                            "value_input_option": "USER_ENTERED",
                            "insert_data_option": "INSERT_ROWS",
                        },
                    )

                # Mark proposal as applied.
                status_col_letter = _col_letter(status_j)
                updates: list[dict[str, Any]] = []
                updates.append(
                    {
                        "range": f"proposals!{status_col_letter}{row_num}",
                        "values": [["applied"]],
                    }
                )
                if applied_at_col:
                    aj = idxp.get(applied_at_col)
                    if isinstance(aj, int):
                        applied_col_letter = _col_letter(aj)
                        updates.append(
                            {
                                "range": f"proposals!{applied_col_letter}{row_num}",
                                "values": [[int(time.time())]],
                            }
                        )

                for u in updates:
                    await mcp_tools_call(
                        tool_update,
                        {
                            "spreadsheet_id": spreadsheet_id,
                            "range": u["range"],
                            "values": u["values"],
                            "value_input_option": "USER_ENTERED",
                        },
                    )

                applied += 1
                details.append({"row": row_num, "status": "applied", "action": "start_project", "project_id": project_id})
            else:
                skipped += 1
                details.append({"row": row_num, "status": "skipped", "reason": "unsupported_action", "action": action})

        return {
            "ok": True,
            "namespace": namespace,
            "spreadsheet_id": spreadsheet_id,
            "applied": applied,
            "skipped": skipped,
            "limit": limit,
            "details": details,
        }

    if tool_name == "projects_active_get":
        session_ws = deps["SESSION_WS"]
        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        namespace = str(args.get("namespace") or "").strip()
        if not namespace:
            raise HTTPException(status_code=400, detail="missing_namespace")

        sys_kv = getattr(ws.state, "sys_kv", None)
        sys_kv_dict = sys_kv if isinstance(sys_kv, dict) else None
        if not sys_kv_dict:
            raise HTTPException(status_code=400, detail="missing_sys_kv")

        active_id = str(sys_kv_dict.get(f"projects.{namespace}.active_id") or "").strip() or None
        return {"ok": True, "namespace": namespace, "active_id": active_id}

    if tool_name == "projects_active_set":
        session_ws = deps["SESSION_WS"]
        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        namespace = str(args.get("namespace") or "").strip()
        if not namespace:
            raise HTTPException(status_code=400, detail="missing_namespace")

        spreadsheet_id = str(args.get("spreadsheet_id") or "").strip()
        project_name = str(args.get("project_name") or args.get("name") or "").strip()
        if not spreadsheet_id and not project_name:
            raise HTTPException(status_code=400, detail="missing_spreadsheet_id_or_project_name")

        sys_kv = getattr(ws.state, "sys_kv", None)
        sys_kv_dict = sys_kv if isinstance(sys_kv, dict) else None
        if not sys_kv_dict:
            raise HTTPException(status_code=400, detail="missing_sys_kv")

        if not spreadsheet_id and project_name:
            reg_key = f"projects.{namespace}.projects_json"
            reg = _normalize_projects_registry(_json_loads_loose(sys_kv_dict.get(reg_key)))
            hit = _find_registry_match(reg, name=project_name)
            if hit is not None:
                spreadsheet_id = str(hit.get("spreadsheet_id") or "").strip()
        if not spreadsheet_id:
            raise HTTPException(status_code=400, detail="missing_spreadsheet_id")

        sys_kv_dict[f"projects.{namespace}.active_id"] = spreadsheet_id
        try:
            ws.state.sys_kv = sys_kv_dict
        except Exception:
            pass

        return {"ok": True, "namespace": namespace, "active_id": spreadsheet_id}

    if tool_name == "time_now":
        ZoneInfo = deps["ZoneInfo"]
        datetime = deps["datetime"]
        timezone = deps["timezone"]
        get_user_timezone = deps["get_user_timezone"]
        default_user_id = deps["DEFAULT_USER_ID"]

        tz_raw = str(args.get("timezone") or "").strip()
        if tz_raw:
            try:
                tz = ZoneInfo(tz_raw)
            except Exception:
                tz = get_user_timezone(default_user_id)
        else:
            tz = get_user_timezone(default_user_id)
        now_utc = datetime.now(tz=timezone.utc)
        now_local = now_utc.astimezone(tz)
        return {
            "unix_ts": int(now_utc.timestamp()),
            "utc_iso": now_utc.replace(tzinfo=timezone.utc).isoformat(),
            "local_iso": now_local.isoformat(),
            "timezone": tz.key,
        }

    if tool_name == "session_last_get":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        get_session_last_item = deps["get_session_last_item"]
        slot = str(args.get("slot") or "").strip().lower()
        out = get_session_last_item(str(session_id), slot)
        return out or {"ok": True, "slot": slot, "empty": True}

    if tool_name == "system_reload":
        session_ws = deps["SESSION_WS"]
        system_reload_impl = deps.get("system_reload_impl")
        load_ws_system_kv = deps["load_ws_system_kv"]
        macro_tools_force_reload_from_sheet = deps["macro_tools_force_reload_from_sheet"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        if system_reload_impl is not None:
            out = await system_reload_impl(ws)
            keys = out.get("sys_kv_keys") if isinstance(out, dict) else None
            macros_count = out.get("macros_count") if isinstance(out, dict) else None
            return {"ok": True, "sys_kv_keys": keys or [], "macros_count": int(macros_count or 0)}

        sys_kv = await load_ws_system_kv(ws)
        macros = await macro_tools_force_reload_from_sheet(sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
        keys = sorted([str(k or "").strip() for k in (sys_kv or {}).keys()]) if isinstance(sys_kv, dict) else []
        return {"ok": True, "sys_kv_keys": keys, "macros_count": len(macros or {})}

    if tool_name == "system_reload_macros":
        session_ws = deps["SESSION_WS"]
        load_ws_system_kv = deps["load_ws_system_kv"]
        macro_tools_force_reload_from_sheet = deps["macro_tools_force_reload_from_sheet"]
        macro_tools_reload_selected_from_sheet = deps.get("macro_tools_reload_selected_from_sheet")

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        mode = str(args.get("mode") or "all").strip().lower() or "all"
        if mode not in {"all", "by_name", "by_id"}:
            raise HTTPException(status_code=400, detail={"invalid_mode": mode, "allowed": ["all", "by_name", "by_id"]})

        sys_kv = await load_ws_system_kv(ws)
        sys_kv_dict = sys_kv if isinstance(sys_kv, dict) else None

        if mode == "all":
            macros = await macro_tools_force_reload_from_sheet(sys_kv=sys_kv_dict)
            return {"ok": True, "mode": "all", "macros_count": len(macros or {})}

        # by_name / by_id (aliases)
        single = str(args.get("name") or "").strip()
        if mode == "by_id" and not single:
            single = str(args.get("id") or "").strip()
        names_in = args.get("names")
        if mode == "by_id" and not isinstance(names_in, list):
            names_in = args.get("ids")
        names: list[str] = []
        if single:
            names.append(single)
        if isinstance(names_in, list):
            names.extend([str(x or "").strip() for x in names_in])
        names = [n for n in names if n]
        if not names:
            raise HTTPException(status_code=400, detail="missing_macro_name")
        if macro_tools_reload_selected_from_sheet is None:
            raise HTTPException(status_code=500, detail="missing_macro_tools_reload_selected_from_sheet")
        return await macro_tools_reload_selected_from_sheet(names=names, sys_kv=sys_kv_dict)

    if tool_name == "system_reload_queue":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        create_pending_write = deps["create_pending_write"]
        mode = str(args.get("mode") or "full").strip().lower() or "full"
        allowed_modes = {"full", "all", "memory", "knowledge", "sys", "gems"}
        if mode not in allowed_modes:
            raise HTTPException(status_code=400, detail="invalid_reload_mode")
        payload = {"mode": mode}
        confirmation_id = create_pending_write(str(session_id), "system_reload", payload)
        await _emit_pending_awaiting_user(session_id0=str(session_id), confirmation_id=confirmation_id, action="system_reload", payload=payload)
        return {"ok": True, "queued": True, "confirmation_id": confirmation_id, "mode": mode}

    if tool_name == "system_macro_upsert_bundle_queue":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        create_pending_write = deps["create_pending_write"]
        mode = str(args.get("reload_mode") or "full").strip().lower() or "full"
        allowed_modes = {"full", "all", "memory", "knowledge", "sys", "gems"}
        if mode not in allowed_modes:
            raise HTTPException(status_code=400, detail="invalid_reload_mode")
        macro_args: dict[str, Any] = {}
        for k in ("name", "enabled", "description", "parameters_json", "steps_json"):
            if k in args:
                macro_args[k] = args.get(k)
        if not str(macro_args.get("name") or "").strip():
            raise HTTPException(status_code=400, detail="missing_macro_name")
        if not str(macro_args.get("steps_json") or "").strip():
            raise HTTPException(status_code=400, detail="missing_steps_json")
        payload = {"macro": macro_args, "reload_mode": mode}
        confirmation_id = create_pending_write(
            str(session_id),
            "bundle_publish_macro_reload",
            payload,
        )
        await _emit_pending_awaiting_user(session_id0=str(session_id), confirmation_id=confirmation_id, action="bundle_publish_macro_reload", payload=payload)
        return {"ok": True, "queued": True, "confirmation_id": confirmation_id, "reload_mode": mode, "macro": {"name": macro_args.get("name")}}

    if tool_name == "google_account_relink_queue":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        create_pending_write = deps["create_pending_write"]
        list_pending_writes = deps["list_pending_writes"]
        mcp_tools_call = deps["mcp_tools_call"]
        mcp_text_json = deps["mcp_text_json"]

        existing = list_pending_writes(str(session_id))
        for it in existing:
            if isinstance(it, dict) and str(it.get("action") or "") == "google_account_relink":
                return {"ok": True, "queued": False, "already": True, "confirmation_id": str(it.get("confirmation_id") or "")}

        begin_res = await mcp_tools_call("google-sheets_1mcp_google_account_relink_begin", {})
        begin_parsed = mcp_text_json(begin_res)
        if not isinstance(begin_parsed, dict):
            raise HTTPException(status_code=500, detail="google_account_relink_begin_failed")

        payload = {
            "provider": "google",
            "auth_url": str(begin_parsed.get("auth_url") or "").strip(),
            "redirect_uri": str(begin_parsed.get("redirect_uri") or "").strip(),
            "token_path": str(begin_parsed.get("token_path") or "").strip(),
            "scopes": begin_parsed.get("scopes") if isinstance(begin_parsed.get("scopes"), list) else [],
            "queued_by": "manual",
        }
        confirmation_id = create_pending_write(str(session_id), "google_account_relink", payload)
        await _emit_pending_awaiting_user(session_id0=str(session_id), confirmation_id=confirmation_id, action="google_account_relink", payload=payload)
        return {"ok": True, "queued": True, "confirmation_id": confirmation_id, "action": "google_account_relink"}

    if tool_name in {"system_skills_list", "system_skill_get"}:
        session_ws = deps["SESSION_WS"]
        system_spreadsheet_id = deps["system_spreadsheet_id"]
        system_skills_sheet_name = deps["system_skills_sheet_name"]
        pick_sheets_tool_name = deps["pick_sheets_tool_name"]
        mcp_tools_call = deps["mcp_tools_call"]
        mcp_text_json = deps["mcp_text_json"]
        safe_int = deps["safe_int"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")
        sys_kv = getattr(ws.state, "sys_kv", None)
        sys_kv_dict = sys_kv if isinstance(sys_kv, dict) else None

        spreadsheet_id = str(system_spreadsheet_id() or "").strip()
        if not spreadsheet_id:
            raise HTTPException(status_code=400, detail="missing_system_spreadsheet_id")
        sheet_name = str(system_skills_sheet_name(sys_kv=sys_kv_dict) or "").strip() or "skills"

        tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
        res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_name}!A:Z"})
        parsed = mcp_text_json(res)
        values = parsed.get("values") if isinstance(parsed, dict) else None
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if not isinstance(values, list) and isinstance(data, dict):
            values = data.get("values")
        if not isinstance(values, list) or not values:
            return {"ok": True, "sheet": sheet_name, "count": 0, "items": []} if tool_name == "system_skills_list" else {"ok": False, "error": "skills_sheet_empty"}

        header = [str(c or "").strip().lower() for c in (values[0] if isinstance(values[0], list) else [])]
        idx: dict[str, int] = {}
        for i, col in enumerate(header):
            if col and col not in idx:
                idx[col] = int(i)

        required_cols = ["name", "enabled", "priority", "scope", "content"]
        missing = [c for c in required_cols if c not in idx]
        if missing:
            raise HTTPException(status_code=400, detail={"skills_sheet_missing_columns": missing})

        def _cell(row: list[Any], col: str) -> Any:
            j = idx.get(str(col or "").strip().lower())
            if j is None or j < 0 or j >= len(row):
                return ""
            return row[j]

        def _as_bool_cell(v: Any) -> bool:
            s = str(v or "").strip().lower()
            return s in {"1", "true", "t", "yes", "y", "on"}

        if tool_name == "system_skills_list":
            items: list[dict[str, Any]] = []
            for i, r in enumerate(values[1:], start=2):
                if not isinstance(r, list):
                    continue
                nm = str(_cell(r, "name") or "").strip()
                if not nm:
                    continue
                items.append(
                    {
                        "row": int(i),
                        "name": nm,
                        "enabled": _as_bool_cell(_cell(r, "enabled")),
                        "priority": int(safe_int(_cell(r, "priority"), 0)),
                        "scope": str(_cell(r, "scope") or "global").strip() or "global",
                    }
                )
            items.sort(key=lambda it: (int(it.get("priority") or 0), str(it.get("name") or "")))
            return {"ok": True, "sheet": sheet_name, "count": len(items), "items": items}

        name = str(args.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="missing_skill_name")

        for i, r in enumerate(values[1:], start=2):
            if not isinstance(r, list):
                continue
            nm = str(_cell(r, "name") or "").strip()
            if nm != name:
                continue
            return {
                "ok": True,
                "sheet": sheet_name,
                "row": int(i),
                "name": nm,
                "enabled": _as_bool_cell(_cell(r, "enabled")),
                "priority": int(safe_int(_cell(r, "priority"), 0)),
                "scope": str(_cell(r, "scope") or "global").strip() or "global",
                "content": str(_cell(r, "content") or ""),
            }
        raise HTTPException(status_code=404, detail={"skill_not_found": name})

    if tool_name in {"system_macro_get", "system_macro_upsert", "system_macros_list"}:
        session_ws = deps["SESSION_WS"]
        system_spreadsheet_id = deps["system_spreadsheet_id"]
        system_macros_sheet_name = deps["system_macros_sheet_name"]
        pick_sheets_tool_name = deps["pick_sheets_tool_name"]
        mcp_tools_call = deps["mcp_tools_call"]
        mcp_text_json = deps["mcp_text_json"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")
        sys_kv = getattr(ws.state, "sys_kv", None)
        sys_kv_dict = sys_kv if isinstance(sys_kv, dict) else None

        spreadsheet_id = str(system_spreadsheet_id() or "").strip()
        if not spreadsheet_id:
            raise HTTPException(status_code=400, detail="missing_system_spreadsheet_id")
        sheet_name = str(system_macros_sheet_name(sys_kv=sys_kv_dict) or "").strip() or "macros"

        def _as_bool_cell(v: Any) -> bool:
            s = str(v or "").strip().lower()
            return s in {"1", "true", "t", "yes", "y", "on"}

        def _col_letter(col_idx0: int) -> str:
            n = int(col_idx0) + 1
            if n <= 0:
                return "A"
            out = ""
            while n > 0:
                n, r = divmod(n - 1, 26)
                out = chr(ord("A") + r) + out
            return out or "A"

        tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
        res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_name}!A:Z"})
        parsed = mcp_text_json(res)
        values = parsed.get("values") if isinstance(parsed, dict) else None
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if not isinstance(values, list) and isinstance(data, dict):
            values = data.get("values")
        if not isinstance(values, list) or not values:
            raise HTTPException(status_code=400, detail="system_macros_sheet_empty")

        header = [str(c or "").strip().lower() for c in (values[0] if isinstance(values[0], list) else [])]
        idx: dict[str, int] = {}
        for i, col in enumerate(header):
            if col and col not in idx:
                idx[col] = int(i)

        required_cols = ["name", "enabled", "description", "parameters_json", "steps_json"]
        missing = [c for c in required_cols if c not in idx]
        if missing:
            raise HTTPException(status_code=400, detail={"system_macros_sheet_missing_columns": missing})

        def _cell(row: list[Any], col: str) -> Any:
            j = idx.get(str(col or "").strip().lower())
            if j is None or j < 0 or j >= len(row):
                return ""
            return row[j]

        if tool_name == "system_macros_list":
            items: list[dict[str, Any]] = []
            for i, r in enumerate(values[1:], start=2):
                if not isinstance(r, list):
                    continue
                nm = str(_cell(r, "name") or "").strip()
                if not nm:
                    continue
                items.append({"row": int(i), "name": nm, "enabled": _as_bool_cell(_cell(r, "enabled"))})
            items.sort(key=lambda it: str(it.get("name") or ""))
            return {"ok": True, "sheet": sheet_name, "count": len(items), "items": items}

        name = str(args.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="missing_macro_name")

        found_row_num: int | None = None
        found_row: list[Any] | None = None
        for i, r in enumerate(values[1:], start=2):
            if not isinstance(r, list):
                continue
            nm = str(_cell(r, "name") or "").strip()
            if nm == name:
                found_row_num = int(i)
                found_row = r
                break

        if tool_name == "system_macro_get":
            if found_row_num is None or not isinstance(found_row, list):
                raise HTTPException(status_code=404, detail={"macro_not_found": name})
            return {
                "ok": True,
                "name": name,
                "row": found_row_num,
                "enabled": _as_bool_cell(_cell(found_row, "enabled")),
                "description": str(_cell(found_row, "description") or ""),
                "parameters_json": str(_cell(found_row, "parameters_json") or ""),
                "steps_json": str(_cell(found_row, "steps_json") or ""),
            }

        # system_macro_upsert
        enabled = args.get("enabled")
        if enabled is None:
            enabled = True
        enabled_cell = "TRUE" if bool(enabled) else "FALSE"
        description = str(args.get("description") or "").strip()
        parameters_json = str(args.get("parameters_json") or "").strip()
        steps_json = str(args.get("steps_json") or "").strip()
        if not steps_json:
            raise HTTPException(status_code=400, detail="missing_steps_json")

        max_col = max(idx[c] for c in required_cols)
        row_out: list[Any] = [""] * (max_col + 1)
        row_out[idx["name"]] = name
        row_out[idx["enabled"]] = enabled_cell
        row_out[idx["description"]] = description
        row_out[idx["parameters_json"]] = parameters_json
        row_out[idx["steps_json"]] = steps_json

        create_pending_write = deps["create_pending_write"]

        if found_row_num is None:
            tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
            pending_payload = {
                "mcp_name": tool_append,
                "arguments": {
                    "spreadsheet_id": spreadsheet_id,
                    "range": f"{sheet_name}!A:Z",
                    "values": [row_out],
                },
                "mcp_base": "",
                "tool_name": tool_append,
            }
            confirmation_id = create_pending_write(
                str(session_id),
                action="mcp_tools_call",
                payload=pending_payload,
            )
            await _emit_pending_awaiting_user(session_id0=str(session_id), confirmation_id=confirmation_id, action="mcp_tools_call", payload=pending_payload)
            return {
                "ok": True,
                "queued": True,
                "confirmation_id": confirmation_id,
                "action": "system_macro_upsert",
                "mode": "append",
                "row": 0,
            }

        tool_update = pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
        start_col = _col_letter(0)
        end_col = _col_letter(max_col)
        pending_payload2 = {
            "mcp_name": tool_update,
            "arguments": {
                "spreadsheet_id": spreadsheet_id,
                "range": f"{sheet_name}!{start_col}{found_row_num}:{end_col}{found_row_num}",
                "values": [row_out],
                "value_input_option": "RAW",
            },
            "mcp_base": "",
            "tool_name": tool_update,
        }
        confirmation_id2 = create_pending_write(
            str(session_id),
            action="mcp_tools_call",
            payload=pending_payload2,
        )
        await _emit_pending_awaiting_user(session_id0=str(session_id), confirmation_id=confirmation_id2, action="mcp_tools_call", payload=pending_payload2)
        return {"ok": True, "queued": True, "action": "update", "name": name, "row": found_row_num, "confirmation_id": confirmation_id2}

    if tool_name == "memory_add":
        session_ws = deps["SESSION_WS"]
        feature_enabled = deps["feature_enabled"]
        sys_kv_bool = deps["sys_kv_bool"]
        safe_int = deps["safe_int"]
        memory_sheet_upsert = deps["memory_sheet_upsert"]
        load_ws_sheet_memory = deps["load_ws_sheet_memory"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")
        sys_kv = getattr(ws.state, "sys_kv", None)
        if not feature_enabled("memory", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
            raise HTTPException(status_code=403, detail="feature_disabled:memory")
        if not isinstance(sys_kv, dict) or "memory.write.enabled" not in sys_kv:
            raise HTTPException(status_code=500, detail={"missing_sys_kv_key": "memory.write.enabled"})
        if not isinstance(sys_kv, dict) or "memory.autowrite.enabled" not in sys_kv:
            raise HTTPException(status_code=500, detail={"missing_sys_kv_key": "memory.autowrite.enabled"})
        if not sys_kv_bool(sys_kv, "memory.write.enabled", False):
            raise HTTPException(status_code=403, detail="memory_write_disabled")
        if not sys_kv_bool(sys_kv, "memory.autowrite.enabled", False):
            raise HTTPException(status_code=403, detail="memory_autowrite_disabled")

        key = str(args.get("key") or "").strip() or None
        value = str(args.get("value") or "").strip()
        if not value:
            raise HTTPException(status_code=400, detail="memory_missing_value")
        scope = str(args.get("scope") or "global").strip() or "global"
        priority = safe_int(args.get("priority"), 0)
        res = await memory_sheet_upsert(
            ws,
            key=key,
            value=value,
            scope=scope,
            priority=priority,
            enabled=True,
            source="gemini",
        )
        try:
            await load_ws_sheet_memory(ws)
        except Exception:
            pass
        return res

    if tool_name == "memo_add":
        try:
            session_ws = deps["SESSION_WS"]
            feature_enabled = deps["feature_enabled"]
            sys_kv_bool = deps["sys_kv_bool"]
            safe_int = deps.get("safe_int")
            memo_sheet_cfg_from_sys_kv = deps["memo_sheet_cfg_from_sys_kv"]
            sheet_name_to_a1 = deps["sheet_name_to_a1"]
            sheet_get_header_row = deps["sheet_get_header_row"]
            idx_from_header = deps["idx_from_header"]
            memo_ensure_header = deps["memo_ensure_header"]
            pick_sheets_tool_name = deps["pick_sheets_tool_name"]
            mcp_tools_call = deps["mcp_tools_call"]
            mcp_text_json = deps["mcp_text_json"]
            memo_prompt_cfg = deps["memo_prompt_cfg"]
            memo_needs_enrich = deps["memo_needs_enrich"]
            memo_enrich_prompt = deps["memo_enrich_prompt"]
            AGENT_CONTINUE_WINDOW_SECONDS = deps["AGENT_CONTINUE_WINDOW_SECONDS"]
            datetime = deps["datetime"]
            timezone = deps["timezone"]
            time_mod = deps["time"]

            ws = session_ws.get(str(session_id)) if session_id else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")

            sys_kv = getattr(ws.state, "sys_kv", None)
            if not feature_enabled("memo", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:memo")
            if not sys_kv_bool(sys_kv, "memo.enabled", False):
                raise HTTPException(status_code=403, detail="memo_disabled")

            memo_txt = str(args.get("memo") or "").strip()
            if not memo_txt:
                raise HTTPException(status_code=400, detail="memo_missing_text")

            spreadsheet_id, sheet_name = memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
            if not spreadsheet_id:
                raise HTTPException(status_code=400, detail="missing_memo_ss")
            if not sheet_name:
                raise HTTPException(status_code=400, detail="missing_memo_sheet_name")

            sheet_a1 = sheet_name_to_a1(sheet_name, default="memo")

            # Always ensure canonical header before indexing/appending. This prevents legacy/manual headers
            # from silently causing incorrect column mapping.
            try:
                await memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, force=False)
            except Exception:
                pass

            header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
            # If Google Sheets "Table" conversion inserts non-canonical columns (e.g. a type/format column like "Tr"),
            # treat that as corruption and force-write the canonical header.
            try:
                canonical = {
                    "id",
                    "date_time",
                    "active",
                    "status",
                    "group",
                    "subject",
                    "memo",
                    "result",
                    "_created",
                    "_updated",
                }
                lowered_first = [str(x or "").strip().lower() for x in (header or [])][:10]
                unknown = [c for c in lowered_first if c and c not in canonical]
                if unknown:
                    await memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, force=True)
                    header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
            except Exception:
                pass
            idx = idx_from_header(header)
            if not idx:
                await memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1)
                header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
                idx = idx_from_header(header)
            if not idx:
                raise HTTPException(status_code=400, detail="memo_sheet_missing_header")

            now_dt = datetime.now(tz=timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
            status = str(args.get("status") or "").strip() or "new"
            group = str(args.get("group") or "").strip()
            subject = str(args.get("subject") or "").strip()
            result = str(args.get("result") or "").strip()
            active = args.get("active")

            def _col_letter(col_idx0: int) -> str:
                n = int(col_idx0) + 1
                if n <= 0:
                    return "A"
                out = ""
                while n > 0:
                    n, r = divmod(n - 1, 26)
                    out = chr(ord("A") + r) + out
                return out or "A"

            async def _next_memo_id() -> int:
                try:
                    id_col = "A"
                    try:
                        j0 = idx.get("id") if isinstance(idx, dict) else None
                        if isinstance(j0, int) and j0 >= 0:
                            id_col = _col_letter(j0)
                    except Exception:
                        id_col = "A"
                    tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
                    res_get = await mcp_tools_call(
                        tool_get,
                        {
                            "spreadsheet_id": spreadsheet_id,
                            "range": f"{sheet_a1}!{id_col}2:{id_col}",
                            "major_dimension": "COLUMNS",
                        },
                    )
                    parsed_get = mcp_text_json(res_get)
                    data = parsed_get.get("data") if isinstance(parsed_get, dict) else None
                    vals = parsed_get.get("values") if isinstance(parsed_get, dict) else None
                    if not isinstance(vals, list) and isinstance(data, dict):
                        vals = data.get("values")
                    col = vals[0] if isinstance(vals, list) and vals and isinstance(vals[0], list) else []
                    max_id = 0
                    for v in col:
                        s2 = str(v or "").strip()
                        if not s2:
                            continue
                        try:
                            n2 = int(float(s2))
                        except Exception:
                            continue
                        if n2 > max_id:
                            max_id = n2
                    if max_id > 0:
                        return max_id + 1

                    # Header was normalized but existing rows may not have ids yet.
                    # Fall back to a safe row-count-based next id.
                    try:
                        anchor_col = "A"
                        j_memo = idx.get("memo") if isinstance(idx, dict) else None
                        j_dt = idx.get("date_time") if isinstance(idx, dict) else None
                        if isinstance(j_memo, int) and j_memo >= 0:
                            anchor_col = _col_letter(j_memo)
                        elif isinstance(j_dt, int) and j_dt >= 0:
                            anchor_col = _col_letter(j_dt)
                        res_rows = await mcp_tools_call(
                            tool_get,
                            {
                                "spreadsheet_id": spreadsheet_id,
                                "range": f"{sheet_a1}!{anchor_col}2:{anchor_col}",
                                "major_dimension": "COLUMNS",
                            },
                        )
                        parsed_rows = mcp_text_json(res_rows)
                        data2 = parsed_rows.get("data") if isinstance(parsed_rows, dict) else None
                        vals2 = parsed_rows.get("values") if isinstance(parsed_rows, dict) else None
                        if not isinstance(vals2, list) and isinstance(data2, dict):
                            vals2 = data2.get("values")
                        col2 = vals2[0] if isinstance(vals2, list) and vals2 and isinstance(vals2[0], list) else []
                        return len(col2) + 1
                    except Exception:
                        return 1
                except Exception:
                    return 1

            def _set(row: list[Any], col: str, value: Any) -> None:
                j = idx.get(str(col or "").strip().lower())
                if j is None:
                    return
                while len(row) <= j:
                    row.append("")
                row[j] = value

            memo_id = await _next_memo_id()
            # Write a fixed-width row (A:J) but map values by header-derived indices.
            # This preserves legacy header order while preventing Sheets "Table" formatting from shifting columns.
            row_out: list[Any] = [""] * 10
            _set(row_out, "id", memo_id)
            _set(row_out, "date_time", now_dt)
            _set(row_out, "active", True if active is None else bool(active))
            _set(row_out, "status", status)
            _set(row_out, "group", group)
            _set(row_out, "subject", subject)
            _set(row_out, "memo", memo_txt)
            _set(row_out, "result", result)
            _set(row_out, "_created", now_dt)
            _set(row_out, "_updated", now_dt)

            tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
            res = await mcp_tools_call(
                tool_append,
                {
                    "spreadsheet_id": spreadsheet_id,
                    "range": f"{sheet_a1}!A:J",
                    "values": [row_out],
                    "value_input_option": "USER_ENTERED",
                    "insert_data_option": "INSERT_ROWS",
                },
            )
            parsed = mcp_text_json(res)
            out = {"ok": True, "id": memo_id, "sheet": sheet_name, "spreadsheet_id": spreadsheet_id, "raw": parsed}

            cfg = memo_prompt_cfg(sys_kv)
            if cfg.get("enabled"):
                need = memo_needs_enrich(
                    memo=memo_txt,
                    subject=str(args.get("subject") or "").strip(),
                    group=str(args.get("group") or "").strip(),
                    cfg=cfg,
                )
                if need.get("subject") or need.get("group") or need.get("details"):
                    try:
                        ws.state.pending_memo_enrich = {
                            "memo": memo_txt,
                            "subject": str(args.get("subject") or "").strip(),
                            "group": str(args.get("group") or "").strip(),
                            "details": "",
                            "need": need,
                        }
                        ws.state.active_agent_id = "memo_enrich"
                        ws.state.active_agent_until_ts = int(time_mod.time()) + int(AGENT_CONTINUE_WINDOW_SECONDS)
                    except Exception:
                        pass
                    await memo_enrich_prompt(ws)
            return out
        except HTTPException as e:
            logger = deps.get("logger")
            try:
                if logger is not None:
                    logger.info(
                        "memo_add_tool_failed status=%s detail=%s",
                        getattr(e, "status_code", None),
                        getattr(e, "detail", None),
                    )
            except Exception:
                pass
            return {
                "ok": False,
                "error": "memo_add_failed",
                "status_code": getattr(e, "status_code", None),
                "detail": getattr(e, "detail", None),
            }
        except Exception as e:
            logger = deps.get("logger")
            try:
                if logger is not None:
                    logger.exception("memo_add_tool_failed_unhandled")
            except Exception:
                pass
            return {"ok": False, "error": "memo_add_failed", "detail": f"{type(e).__name__}: {e}"}

    if tool_name == "memo_get":
        try:
            session_ws = deps["SESSION_WS"]
            feature_enabled = deps["feature_enabled"]
            sys_kv_bool = deps["sys_kv_bool"]
            safe_int = deps["safe_int"]
            memo_sheet_cfg_from_sys_kv = deps["memo_sheet_cfg_from_sys_kv"]
            sheet_name_to_a1 = deps["sheet_name_to_a1"]
            sheet_get_header_row = deps["sheet_get_header_row"]
            idx_from_header = deps["idx_from_header"]
            memo_ensure_header = deps["memo_ensure_header"]
            pick_sheets_tool_name = deps["pick_sheets_tool_name"]
            mcp_tools_call = deps["mcp_tools_call"]
            mcp_text_json = deps["mcp_text_json"]

            ws = session_ws.get(str(session_id)) if session_id else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            sys_kv = getattr(ws.state, "sys_kv", None)
            if not feature_enabled("memo", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:memo")
            if not sys_kv_bool(sys_kv, "memo.enabled", False):
                raise HTTPException(status_code=403, detail="memo_disabled")

            memo_id = safe_int(args.get("id"), 0)
            if memo_id <= 0:
                raise HTTPException(status_code=400, detail="missing_id")

            spreadsheet_id, sheet_name = memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
            if not spreadsheet_id:
                raise HTTPException(status_code=400, detail="missing_memo_ss")
            if not sheet_name:
                raise HTTPException(status_code=400, detail="missing_memo_sheet_name")

            sheet_a1 = sheet_name_to_a1(sheet_name, default="memo")
            header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
            idx = idx_from_header(header)
            if not idx:
                await memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1)
                header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
                idx = idx_from_header(header)
            if not idx:
                raise HTTPException(status_code=400, detail="memo_sheet_missing_header")

            tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
            res = await mcp_tools_call(
                tool_get,
                {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_a1}!A2:J"},
            )
            parsed = mcp_text_json(res)
            data = parsed.get("data") if isinstance(parsed, dict) else None
            vals = parsed.get("values") if isinstance(parsed, dict) else None
            if not isinstance(vals, list) and isinstance(data, dict):
                vals = data.get("values")
            rows = vals if isinstance(vals, list) else []

            def _cell(row: list[Any], col: str) -> Any:
                j = idx.get(str(col or "").strip().lower())
                if j is None or j < 0 or j >= len(row):
                    return ""
                return row[j]

            hit: dict[str, Any] | None = None
            for r in rows:
                if not isinstance(r, list):
                    continue
                v = str(_cell(r, "id") or "").strip()
                try:
                    rid = int(float(v)) if v else 0
                except Exception:
                    rid = 0
                if rid == int(memo_id):
                    hit = {
                        "id": rid,
                        "active": _cell(r, "active"),
                        "group": str(_cell(r, "group") or ""),
                        "subject": str(_cell(r, "subject") or ""),
                        "memo": str(_cell(r, "memo") or ""),
                        "status": str(_cell(r, "status") or ""),
                        "result": str(_cell(r, "result") or ""),
                        "date_time": str(_cell(r, "date_time") or ""),
                        "_created": str(_cell(r, "_created") or ""),
                        "_updated": str(_cell(r, "_updated") or ""),
                    }
                    break

            if hit is None:
                return {"ok": False, "error": "not_found", "id": int(memo_id)}
            return {"ok": True, "memo": hit}
        except HTTPException as e:
            return {
                "ok": False,
                "error": "memo_get_failed",
                "status_code": getattr(e, "status_code", None),
                "detail": getattr(e, "detail", None),
            }
        except Exception as e:
            return {"ok": False, "error": "memo_get_failed", "detail": f"{type(e).__name__}: {e}"}

    if tool_name == "memo_list":
        try:
            session_ws = deps["SESSION_WS"]
            feature_enabled = deps["feature_enabled"]
            sys_kv_bool = deps["sys_kv_bool"]
            safe_int = deps["safe_int"]
            memo_sheet_cfg_from_sys_kv = deps["memo_sheet_cfg_from_sys_kv"]
            sheet_name_to_a1 = deps["sheet_name_to_a1"]
            sheet_get_header_row = deps["sheet_get_header_row"]
            idx_from_header = deps["idx_from_header"]
            memo_ensure_header = deps["memo_ensure_header"]
            pick_sheets_tool_name = deps["pick_sheets_tool_name"]
            mcp_tools_call = deps["mcp_tools_call"]
            mcp_text_json = deps["mcp_text_json"]

            ws = session_ws.get(str(session_id)) if session_id else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            sys_kv = getattr(ws.state, "sys_kv", None)
            if not feature_enabled("memo", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:memo")
            if not sys_kv_bool(sys_kv, "memo.enabled", False):
                raise HTTPException(status_code=403, detail="memo_disabled")

            limit = max(1, min(50, int(safe_int(args.get("limit"), 20))))

            spreadsheet_id, sheet_name = memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
            if not spreadsheet_id:
                raise HTTPException(status_code=400, detail="missing_memo_ss")
            if not sheet_name:
                raise HTTPException(status_code=400, detail="missing_memo_sheet_name")

            sheet_a1 = sheet_name_to_a1(sheet_name, default="memo")
            header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
            idx = idx_from_header(header)
            if not idx:
                await memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1)
                header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
                idx = idx_from_header(header)
            if not idx:
                raise HTTPException(status_code=400, detail="memo_sheet_missing_header")

            tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
            res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_a1}!A2:J"})
            parsed = mcp_text_json(res)
            data = parsed.get("data") if isinstance(parsed, dict) else None
            vals = parsed.get("values") if isinstance(parsed, dict) else None
            if not isinstance(vals, list) and isinstance(data, dict):
                vals = data.get("values")
            rows = vals if isinstance(vals, list) else []

            def _cell(row: list[Any], col: str) -> Any:
                j = idx.get(str(col or "").strip().lower())
                if j is None or j < 0 or j >= len(row):
                    return ""
                return row[j]

            items: list[dict[str, Any]] = []
            for r in rows:
                if not isinstance(r, list):
                    continue
                v = str(_cell(r, "id") or "").strip()
                try:
                    rid = int(float(v)) if v else 0
                except Exception:
                    rid = 0
                if rid <= 0:
                    continue
                items.append(
                    {
                        "id": rid,
                        "active": _cell(r, "active"),
                        "group": str(_cell(r, "group") or ""),
                        "subject": str(_cell(r, "subject") or ""),
                        "status": str(_cell(r, "status") or ""),
                        "memo": str(_cell(r, "memo") or ""),
                        "date_time": str(_cell(r, "date_time") or ""),
                    }
                )
            items.sort(key=lambda it: int(it.get("id") or 0), reverse=True)
            return {"ok": True, "items": items[:limit], "count": len(items[:limit])}
        except HTTPException as e:
            return {
                "ok": False,
                "error": "memo_list_failed",
                "status_code": getattr(e, "status_code", None),
                "detail": getattr(e, "detail", None),
            }
        except Exception as e:
            return {"ok": False, "error": "memo_list_failed", "detail": f"{type(e).__name__}: {e}"}

    if tool_name in {"current_news_get", "current_news_refresh", "current_news_sources", "current_news_details"}:
        try:
            session_ws = deps["SESSION_WS"]
            feature_enabled = deps["feature_enabled"]
            record_news_usage_event = deps.get("record_news_usage_event")
            get_news_cache = deps["get_news_cache"]
            set_news_cache = deps["set_news_cache"]
            refresh_current_news_cache = deps["refresh_current_news_cache"]
            render_current_news_brief = deps["render_current_news_brief"]

            ws = session_ws.get(str(session_id)) if session_id else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            sys_kv = getattr(ws.state, "sys_kv", None)
            try:
                user_lang = str(getattr(ws.state, "user_lang", "") or "").strip() or "th"
            except Exception:
                user_lang = "th"
            if not feature_enabled("current-news", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:current-news")

            cached = get_news_cache("current-news")
            ctx = cached.get("payload") if isinstance(cached, dict) else None
            if not isinstance(ctx, dict):
                ctx = None

            if tool_name == "current_news_refresh":
                source = args.get("source")
                enrich_missing = args.get("enrich_missing")
                try:
                    if record_news_usage_event is not None:
                        record_news_usage_event(
                            str(session_id),
                            "news_usage",
                            {
                                "tool": tool_name,
                                "action": "refresh",
                                "source": str(source).strip() if source is not None else None,
                                "enrich_missing": bool(enrich_missing) if enrich_missing is not None else None,
                            },
                        )
                except Exception:
                    pass
                ctx = await refresh_current_news_cache(
                    sys_kv=sys_kv if isinstance(sys_kv, dict) else None,
                    source=str(source) if source is not None else None,
                    enrich_missing=bool(enrich_missing) if enrich_missing is not None else None,
                )
                try:
                    set_news_cache("current-news", ctx)
                except Exception:
                    pass
                return {
                    "ok": True,
                    "refreshed": True,
                    "context": ctx,
                    "brief": render_current_news_brief(ctx, lang=user_lang) if isinstance(ctx, dict) else "",
                }

            if ctx is None:
                # Option 1 (fast UX): do not block on cold cache. Kick refresh in background.
                async def _bg_refresh() -> None:
                    try:
                        ctx2 = await refresh_current_news_cache(sys_kv=sys_kv if isinstance(sys_kv, dict) else None, force_fetch=True)
                        try:
                            set_news_cache("current-news", ctx2)
                        except Exception:
                            pass
                    except Exception:
                        return

                try:
                    asyncio.create_task(_bg_refresh())
                except Exception:
                    pass

                return {
                    "ok": True,
                    "brief": "",
                    "updated_at": None,
                    "context": None,
                    "refreshing": True,
                }

            if tool_name == "current_news_sources":
                try:
                    if record_news_usage_event is not None:
                        record_news_usage_event(
                            str(session_id),
                            "news_usage",
                            {"tool": tool_name, "action": "sources"},
                        )
                except Exception:
                    pass
                return {"ok": True, "sources": ctx.get("sources") or [], "updated_at": ctx.get("updated_at"), "context": ctx}

            if tool_name == "current_news_details":
                topic = str(args.get("topic") or "").strip().lower()
                topics = ctx.get("topics") if isinstance(ctx.get("topics"), dict) else {}
                key_map = {
                    "iran": "iran_war",
                    "iran war": "iran_war",
                    "war": "iran_war",
                    "อิหร่าน": "iran_war",
                    "สงคราม": "iran_war",
                    "สงครามอิหร่าน": "iran_war",
                    "gold": "gold",
                    "ทอง": "gold",
                    "ทองคำ": "gold",
                    "xau": "gold",
                    "dollar": "usd",
                    "usd": "usd",
                    "ดอลลาร์": "usd",
                    "อัตราดอกเบี้ย": "usd",
                    "เฟด": "usd",
                    "oil": "oil",
                    "น้ำมัน": "oil",
                    "ราคาน้ำมัน": "oil",
                    "baht": "thb",
                    "thai baht": "thb",
                    "thb": "thb",
                    "usd/thb": "thb",
                    "เงินบาท": "thb",
                    "ค่าเงินบาท": "thb",
                }
                if not topic:
                    available = sorted([str(k) for k in (topics.keys() if isinstance(topics, dict) else []) if str(k).strip()])
                    try:
                        if record_news_usage_event is not None:
                            record_news_usage_event(
                                str(session_id),
                                "news_usage",
                                {"tool": tool_name, "action": "details", "topic": None, "found": False},
                            )
                    except Exception:
                        pass
                    return {
                        "ok": True,
                        "found": False,
                        "topic": "",
                        "hint": "Provide a topic, e.g. iran | gold | usd | oil | baht (also Thai: อิหร่าน | ทอง | น้ำมัน | เงินบาท)",
                        "available": available,
                        "updated_at": ctx.get("updated_at"),
                        "context": ctx,
                    }

                # SSOT: allow direct lookup by sheet topic key.
                if isinstance(topics, dict) and isinstance(topics.get(topic), dict):
                    try:
                        if record_news_usage_event is not None:
                            record_news_usage_event(
                                str(session_id),
                                "news_usage",
                                {"tool": tool_name, "action": "details", "topic": topic, "mapped_topic": topic, "found": True},
                            )
                    except Exception:
                        pass
                    return {"ok": True, "found": True, "topic": topic, "data": topics.get(topic), "updated_at": ctx.get("updated_at"), "context": ctx}

                chosen = key_map.get(topic, "")
                if chosen and isinstance(topics, dict) and isinstance(topics.get(chosen), dict):
                    try:
                        if record_news_usage_event is not None:
                            record_news_usage_event(
                                str(session_id),
                                "news_usage",
                                {"tool": tool_name, "action": "details", "topic": topic, "mapped_topic": chosen, "found": True},
                            )
                    except Exception:
                        pass
                    return {"ok": True, "found": True, "topic": chosen, "data": topics.get(chosen), "updated_at": ctx.get("updated_at"), "context": ctx}
                available = sorted([str(k) for k in (topics.keys() if isinstance(topics, dict) else []) if str(k).strip()])
                try:
                    if record_news_usage_event is not None:
                        record_news_usage_event(
                            str(session_id),
                            "news_usage",
                            {"tool": tool_name, "action": "details", "topic": topic, "found": False, "available": available[:30]},
                        )
                except Exception:
                    pass
                return {
                    "ok": True,
                    "found": False,
                    "topic": topic,
                    "hint": "Unknown topic. Try: iran | gold | usd | oil | baht (Thai: อิหร่าน | ทอง | น้ำมัน | เงินบาท)",
                    "available": available,
                    "updated_at": ctx.get("updated_at"),
                    "context": ctx,
                }

            try:
                if record_news_usage_event is not None:
                    record_news_usage_event(
                        str(session_id),
                        "news_usage",
                        {"tool": tool_name, "action": "get"},
                    )
            except Exception:
                pass
            brief = render_current_news_brief(ctx, lang=user_lang)
            return {"ok": True, "brief": brief, "updated_at": ctx.get("updated_at"), "context": ctx}
        except HTTPException as e:
            return {"ok": False, "error": "current_news_failed", "status_code": getattr(e, "status_code", None), "detail": getattr(e, "detail", None)}
        except Exception as e:
            return {"ok": False, "error": "current_news_failed", "detail": f"{type(e).__name__}: {e}"}

    if tool_name == "news_topics_upsert":
        try:
            session_ws = deps["SESSION_WS"]
            feature_enabled = deps["feature_enabled"]
            news_topics_upsert = deps["news_topics_upsert"]

            ws = session_ws.get(str(session_id)) if session_id else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            sys_kv = getattr(ws.state, "sys_kv", None)
            if not feature_enabled("current-news", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:current-news")

            topic = str(args.get("topic") or "").strip()
            kw_raw = args.get("keywords")
            keywords: list[str] = []
            if isinstance(kw_raw, list):
                keywords = [str(x or "").strip() for x in kw_raw if str(x or "").strip()]
            limit = args.get("limit")
            headlines = args.get("headlines")
            enabled = args.get("enabled")
            if enabled is None:
                enabled = True

            payload = await news_topics_upsert(
                sys_kv=sys_kv if isinstance(sys_kv, dict) else None,
                topic=topic,
                keywords=keywords,
                limit=int(limit) if limit is not None else None,
                headlines=int(headlines) if headlines is not None else None,
                enabled=bool(enabled),
            )
            return {"ok": True, **(payload if isinstance(payload, dict) else {"result": payload})}
        except HTTPException as e:
            return {"ok": False, "error": "news_topics_upsert_failed", "status_code": getattr(e, "status_code", None), "detail": getattr(e, "detail", None)}
        except Exception as e:
            return {"ok": False, "error": "news_topics_upsert_failed", "detail": f"{type(e).__name__}: {e}"}

    if tool_name == "news_sources_upsert":
        try:
            session_ws = deps["SESSION_WS"]
            feature_enabled = deps["feature_enabled"]
            news_sources_upsert = deps["news_sources_upsert"]

            ws = session_ws.get(str(session_id)) if session_id else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            sys_kv = getattr(ws.state, "sys_kv", None)
            if not feature_enabled("current-news", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:current-news")

            url = str(args.get("url") or "").strip()
            name = args.get("name")
            typ = args.get("type")
            tags = args.get("tags")
            enabled = args.get("enabled")
            if enabled is None:
                enabled = True

            payload = await news_sources_upsert(
                sys_kv=sys_kv if isinstance(sys_kv, dict) else None,
                url=url,
                name=str(name).strip() if name is not None else None,
                typ=str(typ).strip() if typ is not None else None,
                tags=str(tags).strip() if tags is not None else None,
                enabled=bool(enabled),
            )
            return {"ok": True, **(payload if isinstance(payload, dict) else {"result": payload})}
        except HTTPException as e:
            return {"ok": False, "error": "news_sources_upsert_failed", "status_code": getattr(e, "status_code", None), "detail": getattr(e, "detail", None)}
        except Exception as e:
            return {"ok": False, "error": "news_sources_upsert_failed", "detail": f"{type(e).__name__}: {e}"}

    if tool_name == "news_items_upsert":
        try:
            session_ws = deps["SESSION_WS"]
            feature_enabled = deps["feature_enabled"]
            news_items_upsert = deps["news_items_upsert"]

            ws = session_ws.get(str(session_id)) if session_id else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            sys_kv = getattr(ws.state, "sys_kv", None)
            if not feature_enabled("current-news", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:current-news")

            link = str(args.get("link") or "").strip()
            title = args.get("title")
            pub_date = args.get("pubDate")
            description = args.get("description")

            payload = await news_items_upsert(
                sys_kv=sys_kv if isinstance(sys_kv, dict) else None,
                link=link,
                title=str(title).strip() if title is not None else None,
                pubDate=str(pub_date).strip() if pub_date is not None else None,
                description=str(description).strip() if description is not None else None,
            )
            return {"ok": True, **(payload if isinstance(payload, dict) else {"result": payload})}
        except HTTPException as e:
            return {"ok": False, "error": "news_items_upsert_failed", "status_code": getattr(e, "status_code", None), "detail": getattr(e, "detail", None)}
        except Exception as e:
            return {"ok": False, "error": "news_items_upsert_failed", "detail": f"{type(e).__name__}: {e}"}

    if tool_name == "news_sources_list":
        try:
            session_ws = deps["SESSION_WS"]
            feature_enabled = deps["feature_enabled"]
            news_sources_list = deps["news_sources_list"]

            ws = session_ws.get(str(session_id)) if session_id else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            sys_kv = getattr(ws.state, "sys_kv", None)
            if not feature_enabled("current-news", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:current-news")

            include_disabled = bool(args.get("include_disabled") or False)
            payload = await news_sources_list(sys_kv=sys_kv if isinstance(sys_kv, dict) else None, include_disabled=include_disabled)
            return {"ok": True, **(payload if isinstance(payload, dict) else {"result": payload})}
        except HTTPException as e:
            return {"ok": False, "error": "news_sources_list_failed", "status_code": getattr(e, "status_code", None), "detail": getattr(e, "detail", None)}
        except Exception as e:
            return {"ok": False, "error": "news_sources_list_failed", "detail": f"{type(e).__name__}: {e}"}

    if tool_name == "gnews_rss_build":
        try:
            gnews_rss_build = deps["gnews_rss_build"]
            query = str(args.get("query") or "").strip()
            hl = args.get("hl")
            gl = args.get("gl")
            ceid = args.get("ceid")
            payload = gnews_rss_build(
                query=query,
                hl=str(hl).strip() if hl is not None else None,
                gl=str(gl).strip() if gl is not None else None,
                ceid=str(ceid).strip() if ceid is not None else None,
            )
            return {"ok": True, **(payload if isinstance(payload, dict) else {"result": payload})}
        except HTTPException as e:
            return {"ok": False, "error": "gnews_rss_build_failed", "status_code": getattr(e, "status_code", None), "detail": getattr(e, "detail", None)}
        except Exception as e:
            return {"ok": False, "error": "gnews_rss_build_failed", "detail": f"{type(e).__name__}: {e}"}

    if tool_name == "it_topic_packs_seed":
        try:
            session_ws = deps["SESSION_WS"]
            feature_enabled = deps["feature_enabled"]
            it_topic_packs_seed = deps["it_topic_packs_seed"]

            ws = session_ws.get(str(session_id)) if session_id else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            sys_kv = getattr(ws.state, "sys_kv", None)
            if not feature_enabled("current-news", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:current-news")

            pack = args.get("pack")
            payload = await it_topic_packs_seed(sys_kv=sys_kv if isinstance(sys_kv, dict) else None, pack=str(pack).strip() if pack is not None else None)
            return {"ok": True, **(payload if isinstance(payload, dict) else {"result": payload})}
        except HTTPException as e:
            return {"ok": False, "error": "it_topic_packs_seed_failed", "status_code": getattr(e, "status_code", None), "detail": getattr(e, "detail", None)}
        except Exception as e:
            return {"ok": False, "error": "it_topic_packs_seed_failed", "detail": f"{type(e).__name__}: {e}"}

    if tool_name in {
        "news_follow_list",
        "news_follow_refresh",
        "news_follow_report",
        "news_follow_focus_list",
        "news_follow_focus_add",
        "news_follow_focus_remove",
    }:
        try:
            session_ws = deps["SESSION_WS"]
            feature_enabled = deps["feature_enabled"]
            get_news_follow_focus = deps["get_news_follow_focus"]
            set_news_follow_focus = deps["set_news_follow_focus"]
            get_news_follow_summaries = deps["get_news_follow_summaries"]
            refresh_news_follow_summaries = deps["refresh_news_follow_summaries"]
            default_user_id = deps.get("DEFAULT_USER_ID")

            ws = session_ws.get(str(session_id)) if session_id else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            sys_kv = getattr(ws.state, "sys_kv", None)
            if not feature_enabled("follow-news", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:follow-news")

            user_id = str(default_user_id or "").strip() or "default"
            focus = get_news_follow_focus(user_id)
            summaries = get_news_follow_summaries(user_id)

            if tool_name == "news_follow_focus_list":
                return {"ok": True, "focus": focus}

            if tool_name == "news_follow_focus_add":
                item = str(args.get("item") or "").strip()
                if not item:
                    raise HTTPException(status_code=400, detail="missing_focus_item")
                set_news_follow_focus(user_id, focus + [item])
                return {"ok": True, "focus": get_news_follow_focus(user_id)}

            if tool_name == "news_follow_focus_remove":
                item = str(args.get("item") or "").strip().lower()
                if not item:
                    raise HTTPException(status_code=400, detail="missing_focus_item")
                new_focus = [f for f in focus if str(f or "").strip().lower() != item]
                set_news_follow_focus(user_id, new_focus)
                return {"ok": True, "focus": get_news_follow_focus(user_id)}

            if tool_name == "news_follow_refresh":
                payload = await refresh_news_follow_summaries(user_id, focus)
                return {"ok": True, "refreshed": True, "status": payload}

            if tool_name == "news_follow_report":
                summary_id = str(args.get("summary_id") or "").strip()
                if not summary_id:
                    raise HTTPException(status_code=400, detail="missing_summary_id")
                chosen = None
                for it in summaries:
                    if isinstance(it, dict) and str(it.get("summary_id") or "").strip() == summary_id:
                        chosen = it
                        break
                if not isinstance(chosen, dict):
                    return {"ok": False, "error": "summary_not_found", "summary_id": summary_id, "summaries": summaries}
                return {"ok": True, "summary": chosen}

            available = [
                {
                    "summary_id": str(it.get("summary_id") or ""),
                    "title": str(it.get("title") or ""),
                    "created_at": it.get("created_at"),
                    "focus": it.get("focus"),
                }
                for it in summaries
                if isinstance(it, dict)
            ]
            return {"ok": True, "focus": focus, "summaries": available, "count": len(available)}
        except HTTPException as e:
            return {"ok": False, "error": "news_follow_failed", "status_code": getattr(e, "status_code", None), "detail": getattr(e, "detail", None)}
        except Exception as e:
            return {"ok": False, "error": "news_follow_failed", "detail": f"{type(e).__name__}: {e}"}

    if tool_name == "chaba_search_memo":
        try:
            session_ws = deps["SESSION_WS"]
            feature_enabled = deps["feature_enabled"]
            sys_kv_bool = deps["sys_kv_bool"]
            safe_int = deps["safe_int"]
            memo_sheet_cfg_from_sys_kv = deps["memo_sheet_cfg_from_sys_kv"]
            sheet_name_to_a1 = deps["sheet_name_to_a1"]
            sheet_get_header_row = deps["sheet_get_header_row"]
            idx_from_header = deps["idx_from_header"]
            memo_ensure_header = deps["memo_ensure_header"]
            pick_sheets_tool_name = deps["pick_sheets_tool_name"]
            mcp_tools_call = deps["mcp_tools_call"]
            mcp_text_json = deps["mcp_text_json"]

            ws = session_ws.get(str(session_id)) if session_id else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            sys_kv = getattr(ws.state, "sys_kv", None)
            if not feature_enabled("memo", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:memo")
            if not sys_kv_bool(sys_kv, "memo.enabled", False):
                raise HTTPException(status_code=403, detail="memo_disabled")

            query = str(args.get("query") or "").strip()
            if not query:
                raise HTTPException(status_code=400, detail="missing_query")
            ql = query.lower()

            limit = max(1, min(50, int(safe_int(args.get("limit"), 10))))
            active_only = args.get("active_only")
            if active_only is None:
                active_only = True
            active_only = bool(active_only)

            spreadsheet_id, sheet_name = memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
            if not spreadsheet_id:
                raise HTTPException(status_code=400, detail="missing_memo_ss")
            if not sheet_name:
                raise HTTPException(status_code=400, detail="missing_memo_sheet_name")

            sheet_a1 = sheet_name_to_a1(sheet_name, default="memo")
            header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
            idx = idx_from_header(header)
            if not idx:
                await memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1)
                header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
                idx = idx_from_header(header)
            if not idx:
                raise HTTPException(status_code=400, detail="memo_sheet_missing_header")

            tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
            res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_a1}!A2:J"})
            parsed = mcp_text_json(res)
            data = parsed.get("data") if isinstance(parsed, dict) else None
            vals = parsed.get("values") if isinstance(parsed, dict) else None
            if not isinstance(vals, list) and isinstance(data, dict):
                vals = data.get("values")
            rows = vals if isinstance(vals, list) else []

            def _cell(row: list[Any], col: str) -> Any:
                j = idx.get(str(col or "").strip().lower())
                if j is None or j < 0 or j >= len(row):
                    return ""
                return row[j]

            def _is_active(v: Any) -> bool:
                s = str(v or "").strip().lower()
                if not s:
                    return True
                return s in {"1", "true", "t", "yes", "y", "on", "enabled"}

            items: list[dict[str, Any]] = []
            for r in rows:
                if not isinstance(r, list):
                    continue
                v_id = str(_cell(r, "id") or "").strip()
                try:
                    rid = int(float(v_id)) if v_id else 0
                except Exception:
                    rid = 0
                if rid <= 0:
                    continue
                if active_only and not _is_active(_cell(r, "active")):
                    continue

                group = str(_cell(r, "group") or "")
                subject = str(_cell(r, "subject") or "")
                status = str(_cell(r, "status") or "")
                memo_txt = str(_cell(r, "memo") or "")
                result = str(_cell(r, "result") or "")

                hay = " ".join([group, subject, status, memo_txt, result]).lower()
                if ql not in hay:
                    continue

                dt = str(_cell(r, "date_time") or "")
                items.append(
                    {
                        "id": rid,
                        "date_time": dt,
                        "active": _cell(r, "active"),
                        "group": group,
                        "subject": subject,
                        "status": status,
                        "memo": memo_txt,
                    }
                )
                if len(items) >= limit:
                    break

            items.sort(key=lambda it: int(it.get("id") or 0), reverse=True)
            return {"ok": True, "query": query, "items": items[:limit], "count": len(items[:limit])}
        except HTTPException as e:
            return {
                "ok": False,
                "error": "chaba_search_memo_failed",
                "status_code": getattr(e, "status_code", None),
                "detail": getattr(e, "detail", None),
            }
        except Exception as e:
            return {"ok": False, "error": "chaba_search_memo_failed", "detail": f"{type(e).__name__}: {e}"}

    if tool_name == "memory_search":
        session_ws = deps["SESSION_WS"]
        feature_enabled = deps["feature_enabled"]
        safe_int = deps["safe_int"]
        load_ws_sheet_memory = deps["load_ws_sheet_memory"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")
        sys_kv = getattr(ws.state, "sys_kv", None)
        if not feature_enabled("memory", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
            raise HTTPException(status_code=403, detail="feature_disabled:memory")
        q = str(args.get("query") or "").strip()
        if not q:
            raise HTTPException(status_code=400, detail="missing_query")
        items = getattr(ws.state, "memory_items", None)
        if not isinstance(items, list) or not items:
            try:
                await load_ws_sheet_memory(ws)
            except Exception:
                pass
            items = getattr(ws.state, "memory_items", None)
        if not isinstance(items, list):
            items = []
        ql = q.lower()
        hits: list[dict[str, Any]] = []
        limit = safe_int(args.get("limit"), 20)
        limit = max(1, min(50, int(limit)))
        for it in items:
            if not isinstance(it, dict):
                continue
            k = str(it.get("key") or "")
            v = str(it.get("value") or "")
            if ql in k.lower() or ql in v.lower():
                hits.append({"key": k, "value": v, "scope": it.get("scope"), "priority": it.get("priority")})
            if len(hits) >= limit:
                break
        return {"ok": True, "query": q, "items": hits}

    if tool_name == "memory_list":
        session_ws = deps["SESSION_WS"]
        feature_enabled = deps["feature_enabled"]
        safe_int = deps["safe_int"]
        load_ws_sheet_memory = deps["load_ws_sheet_memory"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")
        sys_kv = getattr(ws.state, "sys_kv", None)
        if not feature_enabled("memory", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
            raise HTTPException(status_code=403, detail="feature_disabled:memory")
        items = getattr(ws.state, "memory_items", None)
        if not isinstance(items, list) or not items:
            try:
                await load_ws_sheet_memory(ws)
            except Exception:
                pass
            items = getattr(ws.state, "memory_items", None)
        if not isinstance(items, list):
            items = []
        limit = safe_int(args.get("limit"), 50)
        limit = max(1, min(200, int(limit)))
        out: list[str] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            k = str(it.get("key") or "").strip()
            if k:
                out.append(k)
            if len(out) >= limit:
                break
        return {"ok": True, "keys": out}

    if tool_name == "pending_list":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        list_pending_writes = deps["list_pending_writes"]
        return list_pending_writes(session_id)

    if tool_name == "pending_get":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        get_pending_write = deps["get_pending_write"]
        get_pending_write_any_session = deps.get("get_pending_write_any_session")
        session_ws = deps.get("SESSION_WS")
        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        out = get_pending_write(str(session_id), confirmation_id)
        if not out and get_pending_write_any_session and isinstance(session_ws, dict):
            ws = session_ws.get(str(session_id))
            is_admin = bool(getattr(getattr(ws, "state", None), "is_admin", False)) if ws is not None else False
            if is_admin:
                out_any = get_pending_write_any_session(confirmation_id)
                if isinstance(out_any, dict):
                    out = {
                        "confirmation_id": str(out_any.get("confirmation_id") or confirmation_id),
                        "action": out_any.get("action"),
                        "payload": out_any.get("payload"),
                        "created_at": out_any.get("created_at"),
                    }
        if not out:
            raise HTTPException(status_code=404, detail="pending_write_not_found")
        return out

    if tool_name == "pending_preview":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        get_pending_write = deps["get_pending_write"]
        get_pending_write_any_session = deps.get("get_pending_write_any_session")
        session_ws = deps.get("SESSION_WS")
        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        item = get_pending_write(str(session_id), confirmation_id)
        if not item and get_pending_write_any_session and isinstance(session_ws, dict):
            ws = session_ws.get(str(session_id))
            is_admin = bool(getattr(getattr(ws, "state", None), "is_admin", False)) if ws is not None else False
            if is_admin:
                out_any = get_pending_write_any_session(confirmation_id)
                if isinstance(out_any, dict):
                    item = {
                        "confirmation_id": str(out_any.get("confirmation_id") or confirmation_id),
                        "action": out_any.get("action"),
                        "payload": out_any.get("payload"),
                        "created_at": out_any.get("created_at"),
                    }
        if not item:
            raise HTTPException(status_code=404, detail="pending_write_not_found")

        action = str(item.get("action") or "")
        payload = item.get("payload")

        preview: dict[str, Any] = {
            "ok": True,
            "confirmation_id": str(item.get("confirmation_id") or confirmation_id),
            "created_at": int(item.get("created_at") or 0),
            "action": action,
            "risk": "medium",
            "writes_count": 1,
            "targets": [],
            "summary": "",
            "details": {},
        }

        if action == "mcp_tools_call" and isinstance(payload, dict):
            mcp_name = str(payload.get("mcp_name") or "")
            mcp_args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
            original_tool = str(payload.get("tool_name") or "")
            spreadsheet_id = str(mcp_args.get("spreadsheet_id") or "").strip()
            rng = str(mcp_args.get("range") or "").strip()
            values = mcp_args.get("values")
            row_count = len(values) if isinstance(values, list) else 0
            tool_kind = original_tool or mcp_name
            if tool_kind in {"google_sheets_values_update", "google_sheets_values_append"}:
                sheet = ""
                if rng and "!" in rng:
                    sheet = rng.split("!", 1)[0]
                preview["risk"] = "medium"
                preview["targets"] = [
                    {
                        "kind": "google_sheet",
                        "spreadsheet_id": spreadsheet_id,
                        "sheet": sheet,
                        "tool": tool_kind,
                        "range": rng,
                        "rows": row_count,
                    }
                ]
                preview["summary"] = f"{tool_kind}: {sheet or rng or 'sheet'}" + (f" (rows={row_count})" if row_count else "")
                preview["details"] = {
                    "mcp_name": mcp_name,
                    "tool_name": tool_kind,
                    "range": rng,
                    "rows": row_count,
                }
            else:
                preview["risk"] = "high"
                preview["summary"] = f"{tool_kind or action}"
                preview["details"] = {"mcp_name": mcp_name, "tool_name": tool_kind}
        elif action == "system_reload" and isinstance(payload, dict):
            mode = str(payload.get("mode") or "full").strip().lower() or "full"
            preview["risk"] = "high"
            preview["writes_count"] = 0
            preview["targets"] = [{"kind": "system", "action": "system_reload", "mode": mode}]
            preview["summary"] = f"system_reload (mode={mode})"
            preview["details"] = {"mode": mode}
        elif action == "bundle_publish_macro_reload" and isinstance(payload, dict):
            macro = payload.get("macro") if isinstance(payload.get("macro"), dict) else {}
            macro_name = str(macro.get("name") or "").strip()
            mode = str(payload.get("reload_mode") or "full").strip().lower() or "full"
            preview["risk"] = "high"
            preview["writes_count"] = 1
            preview["targets"] = [
                {"kind": "google_sheet", "tool": "system_macro_upsert", "name": macro_name},
                {"kind": "system", "action": "system_reload", "mode": mode},
            ]
            preview["summary"] = f"publish macro '{macro_name}' + system_reload (mode={mode})"
            preview["details"] = {"macro": {"name": macro_name}, "reload_mode": mode}
        elif action == "bundle_seed_macros" and isinstance(payload, dict):
            macros = payload.get("macros") if isinstance(payload.get("macros"), list) else []
            mode = str(payload.get("reload_mode") or "full").strip().lower() or "full"
            names: list[str] = []
            for it in macros:
                if isinstance(it, dict):
                    nm = str(it.get("name") or "").strip()
                    if nm:
                        names.append(nm)
            preview["risk"] = "high"
            preview["writes_count"] = len(names)
            preview["targets"] = [{"kind": "google_sheet", "action": "macro_upsert", "name": nm} for nm in names[:50]]
            preview["summary"] = f"seed_macros count={len(names)} + reload (mode={mode})"
            preview["details"] = {"count": len(names), "names": names[:200], "reload_mode": mode}
        elif action == "google_account_relink" and isinstance(payload, dict):
            auth_url = str(payload.get("auth_url") or "").strip()
            redirect_uri = str(payload.get("redirect_uri") or "").strip()
            token_path = str(payload.get("token_path") or "").strip()
            scopes = payload.get("scopes") if isinstance(payload.get("scopes"), list) else None
            preview["risk"] = "high"
            preview["writes_count"] = 0
            preview["targets"] = [
                {
                    "kind": "google",
                    "action": "oauth_relink",
                    "token_path": token_path,
                }
            ]
            preview["summary"] = "google_account_relink"
            preview["details"] = {
                "provider": "google",
                "auth_url": auth_url,
                "redirect_uri": redirect_uri,
                "token_path": token_path,
                "scopes": scopes or [],
                "instructions": "Open auth_url, approve consent, then paste the redirected URL (or code) into confirm input.",
            }
        elif action == "memo_update" and isinstance(payload, dict):
            memo_id = payload.get("id")
            preview["risk"] = "high"
            preview["writes_count"] = 1
            preview["targets"] = [{"kind": "google_sheet", "action": "memo_update", "id": memo_id}]
            preview["summary"] = f"memo_update id={memo_id}"
            preview["details"] = {"id": memo_id, "proposed": payload}
        elif action == "skill_upsert" and isinstance(payload, dict):
            name = payload.get("name")
            preview["risk"] = "high"
            preview["writes_count"] = 1
            preview["targets"] = [{"kind": "google_sheet", "action": "skill_upsert", "name": name}]
            preview["summary"] = f"skill_upsert name={name}"
            preview["details"] = {"name": name, "proposed": payload}
        elif action == "news_tuning_apply" and isinstance(payload, dict):
            topics = payload.get("topics") if isinstance(payload.get("topics"), list) else []
            sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
            preview["risk"] = "high"
            preview["writes_count"] = len(topics) + len(sources)
            preview["targets"] = [
                {"kind": "google_sheet", "action": "news_topics_upsert", "count": len(topics)},
                {"kind": "google_sheet", "action": "news_sources_upsert", "count": len(sources)},
            ]
            preview["summary"] = f"news_tuning_apply topics={len(topics)} sources={len(sources)}"
            preview["details"] = {"topics": topics[:50], "sources": sources[:50]}
        else:
            preview["risk"] = "high"
            preview["summary"] = action or "pending"

        return preview

    if tool_name == "pending_confirm":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")

        pop_pending_write = deps["pop_pending_write"]
        pop_pending_write_any_session = deps.get("pop_pending_write_any_session")
        session_ws = deps["SESSION_WS"]
        system_reload_impl = deps.get("system_reload_impl")
        load_ws_system_kv = deps["load_ws_system_kv"]
        macro_tools_force_reload_from_sheet = deps["macro_tools_force_reload_from_sheet"]
        adapt_aim_tool_args = deps["adapt_aim_tool_args"]
        aim_mcp_tools_call = deps["aim_mcp_tools_call"]
        mcp_tools_call = deps["mcp_tools_call"]
        mcp_text_json = deps["mcp_text_json"]
        adapt_playwright_tool_args = deps["adapt_playwright_tool_args"]
        google_calendar_fetch_event = deps["google_calendar_fetch_event"]
        google_tasks_fetch_task = deps["google_tasks_fetch_task"]
        undo_sheet_append = deps["undo_sheet_append"]
        google_calendar_undo_log = deps["google_calendar_undo_log"]
        google_tasks_undo_log = deps["google_tasks_undo_log"]
        set_session_last_item = deps["set_session_last_item"]
        news_topics_upsert = deps.get("news_topics_upsert")
        news_sources_upsert = deps.get("news_sources_upsert")

        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        user_input = args.get("input") if isinstance(args.get("input"), dict) else {}
        owner_session_id: str | None = str(session_id)
        pending = pop_pending_write(session_id, confirmation_id)
        if not pending and pop_pending_write_any_session and isinstance(session_ws, dict):
            ws0 = session_ws.get(str(session_id))
            is_admin = bool(getattr(getattr(ws0, "state", None), "is_admin", False)) if ws0 is not None else False
            if is_admin:
                pending_any = pop_pending_write_any_session(confirmation_id)
                if isinstance(pending_any, dict):
                    owner_session_id = str(pending_any.get("session_id") or "").strip() or None
                    pending = {
                        "action": pending_any.get("action"),
                        "payload": pending_any.get("payload"),
                        "created_at": pending_any.get("created_at"),
                    }
        if not pending:
            raise HTTPException(status_code=404, detail="pending_write_not_found")

        # Emit best-effort event (owner + actor session).
        try:
            ev = {
                "type": "pending_event",
                "event": "confirmed",
                "confirmation_id": confirmation_id,
                "action": str(pending.get("action") or ""),
            }
            ws_owner = session_ws.get(str(owner_session_id)) if owner_session_id else None
            ws_actor = session_ws.get(str(session_id)) if session_id else None
            if ws_owner is not None:
                await ws_owner.send_json(ev)
            if ws_actor is not None and ws_actor is not ws_owner:
                await ws_actor.send_json(ev)
        except Exception:
            pass
        action = str(pending.get("action") or "")
        payload = pending.get("payload")
        if action == "system_reload":
            ws = session_ws.get(str(session_id)) if isinstance(session_ws, dict) else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            lang = str(getattr(getattr(ws, "state", None), "user_lang", "") or "").strip() or "en"
            mode = "full"
            if isinstance(payload, dict):
                mode = str(payload.get("mode") or "full").strip().lower() or "full"
            try:
                await ws.send_json({"type": "text", "text": "reloading system"})
            except Exception:
                pass
            if mode in {"full", "all"}:
                if system_reload_impl is not None:
                    out = await system_reload_impl(ws)
                    try:
                        done_txt = "system reloaded" if lang != "th" else "รีโหลดระบบสำเร็จ"
                        await ws.send_json({"type": "text", "text": done_txt})
                    except Exception:
                        pass
                    return {"ok": True, "reloaded": True, "mode": mode, "result": out}
                sys_kv = await load_ws_system_kv(ws)
                macros = await macro_tools_force_reload_from_sheet(sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
                keys = sorted([str(k or "").strip() for k in (sys_kv or {}).keys()]) if isinstance(sys_kv, dict) else []
                try:
                    done_txt = "system reloaded" if lang != "th" else "รีโหลดระบบสำเร็จ"
                    await ws.send_json({"type": "text", "text": done_txt})
                except Exception:
                    pass
                return {"ok": True, "reloaded": True, "mode": mode, "sys_kv_keys": keys, "macros_count": len(macros or {})}
            # For now, partial modes are treated as full reload (safe/consistent).
            if system_reload_impl is not None:
                out2 = await system_reload_impl(ws)
                try:
                    done_txt = "system reloaded" if lang != "th" else "รีโหลดระบบสำเร็จ"
                    await ws.send_json({"type": "text", "text": done_txt})
                except Exception:
                    pass
                return {"ok": True, "reloaded": True, "mode": mode, "result": out2}
            sys_kv2 = await load_ws_system_kv(ws)
            macros2 = await macro_tools_force_reload_from_sheet(sys_kv=sys_kv2 if isinstance(sys_kv2, dict) else None)
            keys2 = sorted([str(k or "").strip() for k in (sys_kv2 or {}).keys()]) if isinstance(sys_kv2, dict) else []
            try:
                done_txt = "system reloaded" if lang != "th" else "รีโหลดระบบสำเร็จ"
                await ws.send_json({"type": "text", "text": done_txt})
            except Exception:
                pass
            return {"ok": True, "reloaded": True, "mode": mode, "sys_kv_keys": keys2, "macros_count": len(macros2 or {})}

        if action == "bundle_publish_macro_reload":
            ws = session_ws.get(str(session_id)) if isinstance(session_ws, dict) else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")

            macro_args = payload.get("macro") if isinstance(payload.get("macro"), dict) else None
            reload_mode = str(payload.get("reload_mode") or "full").strip().lower() or "full"
            if not isinstance(macro_args, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")

            # Execute macro upsert immediately (no additional Pending items).
            system_spreadsheet_id = deps["system_spreadsheet_id"]
            system_macros_sheet_name = deps["system_macros_sheet_name"]
            pick_sheets_tool_name = deps["pick_sheets_tool_name"]
            mcp_tools_call = deps["mcp_tools_call"]
            mcp_text_json = deps["mcp_text_json"]
            sys_kv0 = getattr(ws.state, "sys_kv", None)
            sys_kv_dict0 = sys_kv0 if isinstance(sys_kv0, dict) else None

            spreadsheet_id = str(system_spreadsheet_id() or "").strip()
            if not spreadsheet_id:
                raise HTTPException(status_code=400, detail="missing_system_spreadsheet_id")
            sheet_name = str(system_macros_sheet_name(sys_kv=sys_kv_dict0) or "").strip() or "macros"

            tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
            res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_name}!A:Z"})
            parsed = mcp_text_json(res)
            values = parsed.get("values") if isinstance(parsed, dict) else None
            data = parsed.get("data") if isinstance(parsed, dict) else None
            if not isinstance(values, list) and isinstance(data, dict):
                values = data.get("values")
            if not isinstance(values, list) or not values:
                raise HTTPException(status_code=400, detail="system_macros_sheet_empty")

            header = [str(c or "").strip().lower() for c in (values[0] if isinstance(values[0], list) else [])]
            idx: dict[str, int] = {}
            for i, col in enumerate(header):
                if col and col not in idx:
                    idx[col] = int(i)

            required_cols = ["name", "enabled", "description", "parameters_json", "steps_json"]
            missing = [c for c in required_cols if c not in idx]
            if missing:
                raise HTTPException(status_code=400, detail={"system_macros_sheet_missing_columns": missing})

            def _as_bool_cell(v: Any) -> bool:
                s = str(v or "").strip().lower()
                return s in {"1", "true", "t", "yes", "y", "on"}

            def _col_letter(col_idx0: int) -> str:
                n = int(col_idx0) + 1
                if n <= 0:
                    return "A"
                out = ""
                while n > 0:
                    n, r = divmod(n - 1, 26)
                    out = chr(ord("A") + r) + out
                return out or "A"

            def _cell(row: list[Any], col: str) -> Any:
                j = idx.get(str(col or "").strip().lower())
                if j is None or j < 0 or j >= len(row):
                    return ""
                return row[j]

            name = str(macro_args.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="missing_macro_name")

            found_row_num: int | None = None
            found_row: list[Any] | None = None
            for i, r in enumerate(values[1:], start=2):
                if not isinstance(r, list):
                    continue
                nm = str(_cell(r, "name") or "").strip()
                if nm == name:
                    found_row_num = int(i)
                    found_row = r
                    break

            enabled = macro_args.get("enabled")
            if enabled is None:
                enabled = True
            enabled_cell = "TRUE" if bool(enabled) else "FALSE"
            description = str(macro_args.get("description") or "").strip()
            parameters_json = str(macro_args.get("parameters_json") or "").strip()
            steps_json = str(macro_args.get("steps_json") or "").strip()
            if not steps_json:
                raise HTTPException(status_code=400, detail="missing_steps_json")

            max_col = max(idx[c] for c in required_cols)
            row_out: list[Any] = [""] * (max_col + 1)
            row_out[idx["name"]] = name
            row_out[idx["enabled"]] = enabled_cell
            row_out[idx["description"]] = description
            row_out[idx["parameters_json"]] = parameters_json
            row_out[idx["steps_json"]] = steps_json

            macro_write_result: Any
            if found_row_num is None:
                tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
                macro_write_result = await mcp_tools_call(
                    tool_append,
                    {
                        "spreadsheet_id": spreadsheet_id,
                        "range": f"{sheet_name}!A:Z",
                        "values": [row_out],
                        "value_input_option": "RAW",
                    },
                )
            else:
                tool_update = pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
                start_col = _col_letter(0)
                end_col = _col_letter(max_col)
                macro_write_result = await mcp_tools_call(
                    tool_update,
                    {
                        "spreadsheet_id": spreadsheet_id,
                        "range": f"{sheet_name}!{start_col}{found_row_num}:{end_col}{found_row_num}",
                        "values": [row_out],
                        "value_input_option": "RAW",
                    },
                )

            # Reload system after macro publish.
            try:
                await ws.send_json({"type": "text", "text": "reloading system"})
            except Exception:
                pass
            reload_result: Any
            if system_reload_impl is not None:
                reload_result = await system_reload_impl(ws)
            else:
                sys_kv = await load_ws_system_kv(ws)
                macros = await macro_tools_force_reload_from_sheet(sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
                keys = sorted([str(k or "").strip() for k in (sys_kv or {}).keys()]) if isinstance(sys_kv, dict) else []
                reload_result = {"ok": True, "sys_kv": sys_kv if isinstance(sys_kv, dict) else None, "sys_kv_keys": keys, "macros_count": len(macros or {})}
            try:
                lang = str(getattr(getattr(ws, "state", None), "user_lang", "") or "").strip() or "en"
                done_txt = "system reloaded" if lang != "th" else "รีโหลดระบบสำเร็จ"
                await ws.send_json({"type": "text", "text": done_txt})
            except Exception:
                pass

            return {
                "ok": True,
                "bundle": True,
                "macro": {
                    "name": name,
                    "enabled": _as_bool_cell(enabled_cell),
                    "sheet": sheet_name,
                    "spreadsheet_id": spreadsheet_id,
                    "row": found_row_num,
                },
                "macro_write_result": mcp_text_json(macro_write_result),
                "reload_mode": reload_mode,
                "reload_result": reload_result,
            }

        if action == "bundle_seed_macros":
            ws = session_ws.get(str(session_id)) if isinstance(session_ws, dict) else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")
            macros_in = payload.get("macros")
            reload_mode = str(payload.get("reload_mode") or "full").strip().lower() or "full"
            if not isinstance(macros_in, list):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")

            # Upsert each macro row, then reload once.
            system_spreadsheet_id = deps["system_spreadsheet_id"]
            system_macros_sheet_name = deps["system_macros_sheet_name"]
            pick_sheets_tool_name = deps["pick_sheets_tool_name"]
            mcp_tools_call = deps["mcp_tools_call"]
            mcp_text_json = deps["mcp_text_json"]
            sys_kv0 = getattr(ws.state, "sys_kv", None)
            sys_kv_dict0 = sys_kv0 if isinstance(sys_kv0, dict) else None

            spreadsheet_id = str(system_spreadsheet_id() or "").strip()
            if not spreadsheet_id:
                raise HTTPException(status_code=400, detail="missing_system_spreadsheet_id")
            sheet_name = str(system_macros_sheet_name(sys_kv=sys_kv_dict0) or "").strip() or "macros"

            tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
            res = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_name}!A:Z"})
            parsed = mcp_text_json(res)
            values = parsed.get("values") if isinstance(parsed, dict) else None
            data = parsed.get("data") if isinstance(parsed, dict) else None
            if not isinstance(values, list) and isinstance(data, dict):
                values = data.get("values")
            if not isinstance(values, list) or not values:
                raise HTTPException(status_code=400, detail="system_macros_sheet_empty")

            header = [str(c or "").strip().lower() for c in (values[0] if isinstance(values[0], list) else [])]
            idx: dict[str, int] = {}
            for i, col in enumerate(header):
                if col and col not in idx:
                    idx[col] = int(i)

            required_cols = ["name", "enabled", "description", "parameters_json", "steps_json"]
            missing = [c for c in required_cols if c not in idx]
            if missing:
                raise HTTPException(status_code=400, detail={"system_macros_sheet_missing_columns": missing})

            def _col_letter(col_idx0: int) -> str:
                n = int(col_idx0) + 1
                if n <= 0:
                    return "A"
                out = ""
                while n > 0:
                    n, r = divmod(n - 1, 26)
                    out = chr(ord("A") + r) + out
                return out or "A"

            def _cell(row: list[Any], col: str) -> Any:
                j = idx.get(str(col or "").strip().lower())
                if j is None or j < 0 or j >= len(row):
                    return ""
                return row[j]

            max_col = max(idx[c] for c in required_cols)
            tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
            tool_update = pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")

            writes: list[dict[str, Any]] = []
            for macro_args in macros_in:
                if not isinstance(macro_args, dict):
                    continue
                name = str(macro_args.get("name") or "").strip()
                if not name:
                    continue
                enabled = macro_args.get("enabled")
                if enabled is None:
                    enabled = True
                enabled_cell = "TRUE" if bool(enabled) else "FALSE"
                description = str(macro_args.get("description") or "").strip()
                parameters_json = str(macro_args.get("parameters_json") or "").strip()
                steps_json = str(macro_args.get("steps_json") or "").strip()
                if not steps_json:
                    continue

                found_row_num: int | None = None
                for i, r in enumerate(values[1:], start=2):
                    if not isinstance(r, list):
                        continue
                    nm = str(_cell(r, "name") or "").strip()
                    if nm == name:
                        found_row_num = int(i)
                        break

                row_out: list[Any] = [""] * (max_col + 1)
                row_out[idx["name"]] = name
                row_out[idx["enabled"]] = enabled_cell
                row_out[idx["description"]] = description
                row_out[idx["parameters_json"]] = parameters_json
                row_out[idx["steps_json"]] = steps_json

                if found_row_num is None:
                    res_w = await mcp_tools_call(
                        tool_append,
                        {
                            "spreadsheet_id": spreadsheet_id,
                            "range": f"{sheet_name}!A:Z",
                            "values": [row_out],
                            "value_input_option": "RAW",
                        },
                    )
                    writes.append({"name": name, "op": "append", "result": mcp_text_json(res_w)})
                else:
                    start_col = _col_letter(0)
                    end_col = _col_letter(max_col)
                    res_w = await mcp_tools_call(
                        tool_update,
                        {
                            "spreadsheet_id": spreadsheet_id,
                            "range": f"{sheet_name}!{start_col}{found_row_num}:{end_col}{found_row_num}",
                            "values": [row_out],
                            "value_input_option": "RAW",
                        },
                    )
                    writes.append({"name": name, "op": "update", "row": found_row_num, "result": mcp_text_json(res_w)})

            # Reload system after seeding.
            try:
                await ws.send_json({"type": "text", "text": "reloading system"})
            except Exception:
                pass
            reload_result: Any
            if system_reload_impl is not None:
                reload_result = await system_reload_impl(ws)
            else:
                sys_kv = await load_ws_system_kv(ws)
                macros = await macro_tools_force_reload_from_sheet(sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
                keys = sorted([str(k or "").strip() for k in (sys_kv or {}).keys()]) if isinstance(sys_kv, dict) else []
                reload_result = {"ok": True, "sys_kv": sys_kv if isinstance(sys_kv, dict) else None, "sys_kv_keys": keys, "macros_count": len(macros or {})}

            try:
                lang = str(getattr(getattr(ws, "state", None), "user_lang", "") or "").strip() or "en"
                done_txt = "system reloaded" if lang != "th" else "รีโหลดระบบสำเร็จ"
                await ws.send_json({"type": "text", "text": done_txt})
            except Exception:
                pass

            return {
                "ok": True,
                "bundle": True,
                "seeded": True,
                "count": len(writes),
                "writes": writes,
                "reload_mode": reload_mode,
                "reload_result": reload_result,
                "sheet": sheet_name,
                "spreadsheet_id": spreadsheet_id,
            }

        if action == "bundle_bootstrap_skills":
            ws = session_ws.get(str(session_id)) if isinstance(session_ws, dict) else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")

            system_spreadsheet_id = deps["system_spreadsheet_id"]
            system_skills_sheet_name = deps["system_skills_sheet_name"]
            pick_sheets_tool_name = deps["pick_sheets_tool_name"]
            mcp_tools_call = deps["mcp_tools_call"]
            mcp_text_json = deps["mcp_text_json"]

            sys_kv0 = getattr(ws.state, "sys_kv", None)
            sys_kv_dict0 = sys_kv0 if isinstance(sys_kv0, dict) else None
            spreadsheet_id = str(system_spreadsheet_id() or "").strip()
            if not spreadsheet_id:
                raise HTTPException(status_code=400, detail="missing_system_spreadsheet_id")
            sheet_name = str(system_skills_sheet_name(sys_kv=sys_kv_dict0) or "").strip() or "skills"
            seed_name = str(payload.get("seed_name") or "").strip() or "jarvis-skill-smoke-test"

            # Ensure the sheet tab exists.
            tool_meta = pick_sheets_tool_name("google_sheets_get_spreadsheet", "google_sheets_get_spreadsheet")
            meta_res = await mcp_tools_call(tool_meta, {"spreadsheet_id": spreadsheet_id})
            meta_parsed = mcp_text_json(meta_res)
            meta_data = meta_parsed.get("data") if isinstance(meta_parsed, dict) else None
            if not isinstance(meta_data, dict):
                meta_data = meta_parsed if isinstance(meta_parsed, dict) else {}
            sheets = meta_data.get("sheets") if isinstance(meta_data, dict) else None
            exists = False
            if isinstance(sheets, list):
                for s in sheets:
                    props = s.get("properties") if isinstance(s, dict) else None
                    title = str(props.get("title") or "") if isinstance(props, dict) else ""
                    if title.strip() == sheet_name:
                        exists = True
                        break

            create_result: Any = None
            if not exists:
                tool_bu = pick_sheets_tool_name("google_sheets_batch_update", "google-sheets_1mcp_google_sheets_batch_update")
                req = {"addSheet": {"properties": {"title": sheet_name}}}
                create_result = await mcp_tools_call(tool_bu, {"spreadsheet_id": spreadsheet_id, "requests": [req]})

            # Write header row.
            tool_upd = pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
            header = [["name", "enabled", "priority", "scope", "content"]]
            header_result = await mcp_tools_call(
                tool_upd,
                {
                    "spreadsheet_id": spreadsheet_id,
                    "range": f"{sheet_name}!A1:E1",
                    "values": header,
                    "value_input_option": "RAW",
                },
            )

            # Seed one example skill row.
            tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
            seed_row = [[seed_name, "TRUE", "10", "global", "This is a seeded Jarvis skill row. Replace content with SKILL.md-style instructions."]]
            seed_result = await mcp_tools_call(
                tool_append,
                {
                    "spreadsheet_id": spreadsheet_id,
                    "range": f"{sheet_name}!A:Z",
                    "values": seed_row,
                    "value_input_option": "RAW",
                },
            )

            # Reload system so the sheet is available immediately.
            try:
                await ws.send_json({"type": "text", "text": "reloading system"})
            except Exception:
                pass
            reload_result: Any
            if system_reload_impl is not None:
                reload_result = await system_reload_impl(ws)
            else:
                sys_kv = await load_ws_system_kv(ws)
                macros = await macro_tools_force_reload_from_sheet(sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
                keys = sorted([str(k or "").strip() for k in (sys_kv or {}).keys()]) if isinstance(sys_kv, dict) else []
                reload_result = {"ok": True, "sys_kv": sys_kv if isinstance(sys_kv, dict) else None, "sys_kv_keys": keys, "macros_count": len(macros or {})}

            try:
                lang = str(getattr(getattr(ws, "state", None), "user_lang", "") or "").strip() or "en"
                done_txt = "system reloaded" if lang != "th" else "รีโหลดระบบสำเร็จ"
                await ws.send_json({"type": "text", "text": done_txt})
            except Exception:
                pass

            return {
                "ok": True,
                "bundle": True,
                "action": "bootstrap_skills",
                "spreadsheet_id": spreadsheet_id,
                "sheet": sheet_name,
                "created": (not exists),
                "create_result": mcp_text_json(create_result) if create_result is not None else None,
                "header_result": mcp_text_json(header_result),
                "seed_result": mcp_text_json(seed_result),
                "seed_name": seed_name,
                "reload_result": reload_result,
            }

        if action == "bundle_bootstrap_news_skills":
            ws = session_ws.get(str(session_id)) if isinstance(session_ws, dict) else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")

            system_spreadsheet_id = deps["system_spreadsheet_id"]
            system_news_skills_sheet_name = deps["system_news_skills_sheet_name"]
            pick_sheets_tool_name = deps["pick_sheets_tool_name"]
            mcp_tools_call = deps["mcp_tools_call"]
            mcp_text_json = deps["mcp_text_json"]

            sys_kv0 = getattr(ws.state, "sys_kv", None)
            sys_kv_dict0 = sys_kv0 if isinstance(sys_kv0, dict) else None
            spreadsheet_id = str(system_spreadsheet_id() or "").strip()
            if not spreadsheet_id:
                raise HTTPException(status_code=400, detail="missing_system_spreadsheet_id")
            sheet_name = str(system_news_skills_sheet_name(sys_kv=sys_kv_dict0) or "").strip() or "skills_news"
            seed_name = str(payload.get("seed_name") or "").strip() or "jarvis-news-skill-smoke-test"

            # Ensure the sheet tab exists.
            tool_meta = pick_sheets_tool_name("google_sheets_get_spreadsheet", "google_sheets_get_spreadsheet")
            meta_res = await mcp_tools_call(tool_meta, {"spreadsheet_id": spreadsheet_id})
            meta_parsed = mcp_text_json(meta_res)
            meta_data = meta_parsed.get("data") if isinstance(meta_parsed, dict) else None
            if not isinstance(meta_data, dict):
                meta_data = meta_parsed if isinstance(meta_parsed, dict) else {}
            sheets = meta_data.get("sheets") if isinstance(meta_data, dict) else None
            exists = False
            if isinstance(sheets, list):
                for s in sheets:
                    props = s.get("properties") if isinstance(s, dict) else None
                    title = str(props.get("title") or "") if isinstance(props, dict) else ""
                    if title.strip() == sheet_name:
                        exists = True
                        break

            create_result: Any = None
            if not exists:
                tool_bu = pick_sheets_tool_name("google_sheets_batch_update", "google-sheets_1mcp_google_sheets_batch_update")
                req = {"addSheet": {"properties": {"title": sheet_name}}}
                create_result = await mcp_tools_call(tool_bu, {"spreadsheet_id": spreadsheet_id, "requests": [req]})

            # Write header row.
            tool_upd = pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
            header = [["match_type", "pattern", "handler", "arg_json", "enabled", "notes"]]
            header_result = await mcp_tools_call(
                tool_upd,
                {
                    "spreadsheet_id": spreadsheet_id,
                    "range": f"{sheet_name}!A1:F1",
                    "values": header,
                    "value_input_option": "RAW",
                },
            )

            # Seed one example rule row.
            tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
            seed_row = [["contains", "news tuning", "tool_call", "{\"tool\":\"news_tuning_suggest\",\"args\":{}}", "TRUE", seed_name]]
            seed_result = await mcp_tools_call(
                tool_append,
                {
                    "spreadsheet_id": spreadsheet_id,
                    "range": f"{sheet_name}!A:Z",
                    "values": seed_row,
                    "value_input_option": "RAW",
                },
            )

            # Reload system so routing can take effect immediately.
            try:
                await ws.send_json({"type": "text", "text": "reloading system"})
            except Exception:
                pass
            reload_result: Any
            if system_reload_impl is not None:
                reload_result = await system_reload_impl(ws)
            else:
                sys_kv = await load_ws_system_kv(ws)
                macros = await macro_tools_force_reload_from_sheet(sys_kv=sys_kv if isinstance(sys_kv, dict) else None)
                keys = sorted([str(k or "").strip() for k in (sys_kv or {}).keys()]) if isinstance(sys_kv, dict) else []
                reload_result = {"ok": True, "sys_kv": sys_kv if isinstance(sys_kv, dict) else None, "sys_kv_keys": keys, "macros_count": len(macros or {})}

            try:
                lang = str(getattr(getattr(ws, "state", None), "user_lang", "") or "").strip() or "en"
                done_txt = "system reloaded" if lang != "th" else "รีโหลดระบบสำเร็จ"
                await ws.send_json({"type": "text", "text": done_txt})
            except Exception:
                pass

            return {
                "ok": True,
                "bundle": True,
                "action": "bootstrap_news_skills",
                "spreadsheet_id": spreadsheet_id,
                "sheet": sheet_name,
                "created": (not exists),
                "create_result": mcp_text_json(create_result) if create_result is not None else None,
                "header_result": mcp_text_json(header_result),
                "seed_result": mcp_text_json(seed_result),
                "seed_name": seed_name,
                "reload_result": reload_result,
            }

        if action == "google_account_relink":
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")
            code_or_url = str(user_input.get("code_or_redirected_url") or "").strip()
            if not code_or_url:
                try:
                    last = deps.get("oauth_callback_last")
                except Exception:
                    last = None
                if isinstance(last, dict):
                    # Prefer full redirected URL (it may contain state + other params), fall back to code.
                    code_or_url = str(last.get("url") or "").strip() or str(last.get("code") or "").strip()
            if not code_or_url:
                raise HTTPException(status_code=400, detail="missing_code_or_redirected_url")
            res = await mcp_tools_call(
                "google-sheets_1mcp_google_account_relink_finish", {"code_or_redirected_url": code_or_url}
            )
            parsed = mcp_text_json(res)
            return parsed if isinstance(parsed, dict) else {"ok": True, "result": parsed}

        if action == "memo_update":
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")

            ws = session_ws.get(str(session_id)) if isinstance(session_ws, dict) else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")

            feature_enabled = deps["feature_enabled"]
            sys_kv_bool = deps["sys_kv_bool"]
            safe_int = deps["safe_int"]
            memo_sheet_cfg_from_sys_kv = deps["memo_sheet_cfg_from_sys_kv"]
            sheet_name_to_a1 = deps["sheet_name_to_a1"]
            sheet_get_header_row = deps["sheet_get_header_row"]
            idx_from_header = deps["idx_from_header"]
            memo_ensure_header = deps["memo_ensure_header"]
            pick_sheets_tool_name = deps["pick_sheets_tool_name"]
            datetime = deps["datetime"]
            timezone = deps["timezone"]

            sys_kv = getattr(ws.state, "sys_kv", None)
            if not feature_enabled("memo", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:memo")
            if not sys_kv_bool(sys_kv, "memo.enabled", False):
                raise HTTPException(status_code=403, detail="memo_disabled")

            memo_id = safe_int(payload.get("id"), 0)
            if memo_id <= 0:
                raise HTTPException(status_code=400, detail="missing_id")

            spreadsheet_id, sheet_name = memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
            if not spreadsheet_id:
                raise HTTPException(status_code=400, detail="missing_memo_ss")
            if not sheet_name:
                raise HTTPException(status_code=400, detail="missing_memo_sheet_name")
            sheet_a1 = sheet_name_to_a1(sheet_name, default="memo")

            header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
            # If the sheet was converted to a Google Sheets "Table" it may insert non-canonical columns in A:J
            # (e.g. "Tr"), or shift canonical columns beyond J. In either case, force canonical header.
            canonical = {
                "id",
                "date_time",
                "active",
                "status",
                "group",
                "subject",
                "memo",
                "result",
                "_created",
                "_updated",
            }
            try:
                lowered_first = [str(x or "").strip().lower() for x in (header or [])][:10]
                unknown = [c for c in lowered_first if c and c not in canonical]
            except Exception:
                unknown = []

            idx = idx_from_header(header)
            needs_force = False
            if unknown:
                needs_force = True
            if not idx:
                needs_force = True
            else:
                for k in canonical:
                    j = idx.get(k)
                    if j is None or not isinstance(j, int) or j < 0 or j >= 10:
                        needs_force = True
                        break

            if needs_force:
                await memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, force=True)

        if action == "news_tuning_apply":
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")
            if news_topics_upsert is None or news_sources_upsert is None:
                raise HTTPException(status_code=500, detail="missing_news_upsert_deps")

            topics_in = payload.get("topics") if isinstance(payload.get("topics"), list) else []
            sources_in = payload.get("sources") if isinstance(payload.get("sources"), list) else []

            ws = session_ws.get(str(session_id)) if isinstance(session_ws, dict) else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")
            sys_kv0 = getattr(ws.state, "sys_kv", None)
            sys_kv_dict0 = sys_kv0 if isinstance(sys_kv0, dict) else None

            results: dict[str, Any] = {"topics": [], "sources": []}
            for it in topics_in[:200]:
                if not isinstance(it, dict):
                    continue
                topic = str(it.get("topic") or it.get("name") or it.get("key") or "").strip()
                keywords = it.get("keywords") if isinstance(it.get("keywords"), list) else []
                limit = it.get("limit")
                headlines = it.get("headlines")
                enabled = it.get("enabled")
                res = await news_topics_upsert(
                    sys_kv=sys_kv_dict0,
                    topic=topic,
                    keywords=[str(x or "").strip() for x in keywords if str(x or "").strip()],
                    limit=int(limit) if limit is not None else None,
                    headlines=int(headlines) if headlines is not None else None,
                    enabled=bool(enabled) if enabled is not None else True,
                )
                results["topics"].append(res)

            for it in sources_in[:200]:
                if not isinstance(it, dict):
                    continue
                url = str(it.get("url") or "").strip()
                name = it.get("name")
                typ = it.get("type")
                tags = it.get("tags")
                enabled = it.get("enabled")
                res = await news_sources_upsert(
                    sys_kv=sys_kv_dict0,
                    url=url,
                    name=str(name).strip() if name is not None else None,
                    typ=str(typ).strip() if typ is not None else None,
                    tags=str(tags).strip() if tags is not None else None,
                    enabled=bool(enabled) if enabled is not None else True,
                )
                results["sources"].append(res)

            try:
                set_session_last_item(str(session_id), "news_tuning_apply", "news_tuning_apply", {"applied": True, "result": results})
            except Exception:
                pass
            return {"ok": True, "applied": True, "result": results}

        if action == "memo_update":
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")

            ws = session_ws.get(str(session_id)) if isinstance(session_ws, dict) else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")

            feature_enabled = deps["feature_enabled"]
            sys_kv_bool = deps["sys_kv_bool"]
            safe_int = deps["safe_int"]
            memo_sheet_cfg_from_sys_kv = deps["memo_sheet_cfg_from_sys_kv"]
            sheet_name_to_a1 = deps["sheet_name_to_a1"]
            sheet_get_header_row = deps["sheet_get_header_row"]
            idx_from_header = deps["idx_from_header"]
            memo_ensure_header = deps["memo_ensure_header"]
            pick_sheets_tool_name = deps["pick_sheets_tool_name"]
            datetime = deps["datetime"]
            timezone = deps["timezone"]

            sys_kv = getattr(ws.state, "sys_kv", None)
            if not feature_enabled("memo", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
                raise HTTPException(status_code=403, detail="feature_disabled:memo")
            if not sys_kv_bool(sys_kv, "memo.enabled", False):
                raise HTTPException(status_code=403, detail="memo_disabled")

            memo_id = safe_int(payload.get("id"), 0)
            if memo_id <= 0:
                raise HTTPException(status_code=400, detail="missing_id")

            spreadsheet_id, sheet_name = memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
            if not spreadsheet_id:
                raise HTTPException(status_code=400, detail="missing_memo_ss")
            if not sheet_name:
                raise HTTPException(status_code=400, detail="missing_memo_sheet_name")
            sheet_a1 = sheet_name_to_a1(sheet_name, default="memo")

            header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
            # If the sheet was converted to a Google Sheets "Table" it may insert non-canonical columns in A:J
            # (e.g. "Tr"), or shift canonical columns beyond J. In either case, force canonical header.
            canonical = {
                "id",
                "date_time",
                "active",
                "status",
                "group",
                "subject",
                "memo",
                "result",
                "_created",
                "_updated",
            }
            try:
                lowered_first = [str(x or "").strip().lower() for x in (header or [])][:10]
                unknown = [c for c in lowered_first if c and c not in canonical]
            except Exception:
                unknown = []

            idx = idx_from_header(header)
            needs_force = False
            if unknown:
                needs_force = True
            if not idx:
                needs_force = True
            else:
                for k in canonical:
                    j = idx.get(k)
                    if j is None or not isinstance(j, int) or j < 0 or j >= 10:
                        needs_force = True
                        break

            if needs_force:
                await memo_ensure_header(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, force=True)

            header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
            idx = idx_from_header(header)
            if not idx:
                raise HTTPException(status_code=400, detail="memo_sheet_missing_header")

            tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
            res_get = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_a1}!A2:Z"})
            parsed_get = mcp_text_json(res_get)
            data = parsed_get.get("data") if isinstance(parsed_get, dict) else None
            vals = parsed_get.get("values") if isinstance(parsed_get, dict) else None
            if not isinstance(vals, list) and isinstance(data, dict):
                vals = data.get("values")
            rows = vals if isinstance(vals, list) else []

            def _cell(row: list[Any], col: str) -> Any:
                j = idx.get(str(col or "").strip().lower())
                if j is None or j < 0 or j >= len(row):
                    return ""
                return row[j]

            row_num: int | None = None
            current: dict[str, Any] | None = None
            for i, r in enumerate(rows, start=2):
                if not isinstance(r, list):
                    continue
                v = str(_cell(r, "id") or "").strip()
                try:
                    rid = int(float(v)) if v else 0
                except Exception:
                    rid = 0
                if rid != int(memo_id):
                    continue
                row_num = int(i)
                current = {
                    "id": rid,
                    "date_time": str(_cell(r, "date_time") or ""),
                    "active": _cell(r, "active"),
                    "status": str(_cell(r, "status") or ""),
                    "group": str(_cell(r, "group") or ""),
                    "subject": str(_cell(r, "subject") or ""),
                    "memo": str(_cell(r, "memo") or ""),
                    "result": str(_cell(r, "result") or ""),
                    "_created": str(_cell(r, "_created") or ""),
                    "_updated": str(_cell(r, "_updated") or ""),
                }
                break

            if row_num is None or current is None:
                raise HTTPException(status_code=404, detail={"error": "memo_not_found", "id": int(memo_id)})

            now_dt = datetime.now(tz=timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

            out_row: list[Any] = [""] * 10

            def _set(col: str, value: Any) -> None:
                j = idx.get(str(col or "").strip().lower())
                if j is None or not isinstance(j, int) or j < 0 or j >= 10:
                    return
                out_row[j] = value

            for k in ["id", "date_time", "active", "status", "group", "subject", "memo", "result", "_created", "_updated"]:
                _set(k, current.get(k, ""))

            for k in ("memo", "group", "subject", "status", "result"):
                if k in payload:
                    _set(k, str(payload.get(k) or ""))
            if "active" in payload:
                _set("active", bool(payload.get("active")))
            _set("_updated", now_dt)

            tool_update = pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
            await mcp_tools_call(
                tool_update,
                {
                    "spreadsheet_id": spreadsheet_id,
                    "range": f"{sheet_a1}!A{row_num}:J{row_num}",
                    "values": [out_row],
                    "value_input_option": "USER_ENTERED",
                },
            )

            try:
                ws.state.last_memo = dict({**current, **{k: payload.get(k) for k in payload.keys() if k != "id"}})
            except Exception:
                pass
            return {"ok": True, "updated": True, "id": int(memo_id), "row": int(row_num)}

        if action == "skill_upsert":
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")

            ws = session_ws.get(str(session_id)) if isinstance(session_ws, dict) else None
            if ws is None:
                raise HTTPException(status_code=400, detail="missing_session_ws")

            system_spreadsheet_id = deps["system_spreadsheet_id"]
            system_skills_sheet_name = deps["system_skills_sheet_name"]
            pick_sheets_tool_name = deps["pick_sheets_tool_name"]
            mcp_tools_call = deps["mcp_tools_call"]
            mcp_text_json = deps["mcp_text_json"]
            safe_int = deps["safe_int"]

            sys_kv0 = getattr(ws.state, "sys_kv", None)
            sys_kv_dict0 = sys_kv0 if isinstance(sys_kv0, dict) else None
            spreadsheet_id = str(system_spreadsheet_id() or "").strip()
            if not spreadsheet_id:
                raise HTTPException(status_code=400, detail="missing_system_spreadsheet_id")
            sheet_name = str(system_skills_sheet_name(sys_kv=sys_kv_dict0) or "").strip() or "skills"

            tool_get = pick_sheets_tool_name("google_sheets_values_get", "google_sheets_values_get")
            res_get = await mcp_tools_call(tool_get, {"spreadsheet_id": spreadsheet_id, "range": f"{sheet_name}!A:Z"})
            parsed_get = mcp_text_json(res_get)
            values = parsed_get.get("values") if isinstance(parsed_get, dict) else None
            data = parsed_get.get("data") if isinstance(parsed_get, dict) else None
            if not isinstance(values, list) and isinstance(data, dict):
                values = data.get("values")
            if not isinstance(values, list) or not values:
                raise HTTPException(status_code=400, detail="skills_sheet_empty")

            header = [str(c or "").strip().lower() for c in (values[0] if isinstance(values[0], list) else [])]
            idx: dict[str, int] = {}
            for i, col in enumerate(header):
                if col and col not in idx:
                    idx[col] = int(i)

            required_cols = ["name", "enabled", "priority", "scope", "content"]
            missing = [c for c in required_cols if c not in idx]
            if missing:
                raise HTTPException(status_code=400, detail={"skills_sheet_missing_columns": missing})

            def _cell(row: list[Any], col: str) -> Any:
                j = idx.get(str(col or "").strip().lower())
                if j is None or j < 0 or j >= len(row):
                    return ""
                return row[j]

            def _col_letter(col_idx0: int) -> str:
                n = int(col_idx0) + 1
                if n <= 0:
                    return "A"
                out = ""
                while n > 0:
                    n, r = divmod(n - 1, 26)
                    out = chr(ord("A") + r) + out
                return out or "A"

            name = str(payload.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="missing_name")
            content = str(payload.get("content") or "")
            if not content.strip():
                raise HTTPException(status_code=400, detail="missing_content")

            enabled_raw = payload.get("enabled")
            enabled = True if enabled_raw is None else bool(enabled_raw)
            priority = int(safe_int(payload.get("priority"), 0))
            scope = str(payload.get("scope") or "global").strip() or "global"
            enabled_cell = "TRUE" if enabled else "FALSE"

            max_col = max(int(idx[c]) for c in required_cols)
            row_out: list[Any] = [""] * (max_col + 1)
            row_out[int(idx["name"])] = name
            row_out[int(idx["enabled"])] = enabled_cell
            row_out[int(idx["priority"])] = str(int(priority))
            row_out[int(idx["scope"])] = scope
            row_out[int(idx["content"])] = content

            found_row_num: int | None = None
            for i, r in enumerate(values[1:], start=2):
                if not isinstance(r, list):
                    continue
                nm = str(_cell(r, "name") or "").strip()
                if nm == name:
                    found_row_num = int(i)
                    break

            tool_update = pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
            tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")

            if found_row_num is not None:
                start_col = _col_letter(0)
                end_col = _col_letter(max_col)
                rng = f"{sheet_name}!{start_col}{found_row_num}:{end_col}{found_row_num}"
                res_upd = await mcp_tools_call(
                    tool_update,
                    {
                        "spreadsheet_id": spreadsheet_id,
                        "range": rng,
                        "values": [row_out],
                        "value_input_option": "RAW",
                    },
                )
                return {
                    "ok": True,
                    "updated": True,
                    "name": name,
                    "row": int(found_row_num),
                    "sheet": sheet_name,
                    "range": rng,
                    "response": mcp_text_json(res_upd),
                }

            res_app = await mcp_tools_call(
                tool_append,
                {
                    "spreadsheet_id": spreadsheet_id,
                    "range": f"{sheet_name}!A:Z",
                    "values": [row_out],
                    "value_input_option": "RAW",
                },
            )
            return {
                "ok": True,
                "created": True,
                "name": name,
                "sheet": sheet_name,
                "response": mcp_text_json(res_app),
            }
        if action == "mcp_tools_call":
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")
            mcp_name = str(payload.get("mcp_name") or "")
            mcp_args = payload.get("arguments")
            mcp_base = str(payload.get("mcp_base") or "").strip().lower()
            original_tool_name = str(payload.get("tool_name") or "").strip()
            if not mcp_name or not isinstance(mcp_args, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")
            if mcp_base == "aim":
                adapted = adapt_aim_tool_args(original_tool_name or "", dict(mcp_args))
                return await aim_mcp_tools_call(mcp_name, adapted)
            before_event: Optional[dict[str, Any]] = None
            event_id = str(mcp_args.get("event_id") or "").strip() or None
            if original_tool_name in ("google_calendar_update_event", "google_calendar_delete_event") and event_id:
                before_event = await google_calendar_fetch_event(event_id=event_id)

            before_task: Optional[dict[str, Any]] = None
            task_id = str(mcp_args.get("task_id") or "").strip() or None
            tasklist_id = str(mcp_args.get("tasklist_id") or "").strip() or None
            if original_tool_name in (
                "google_tasks_update_task",
                "google_tasks_complete_task",
                "google_tasks_delete_task",
            ) and task_id and tasklist_id:
                before_task = await google_tasks_fetch_task(tasklist_id=tasklist_id, task_id=task_id)

            forwarded_args = dict(mcp_args)
            if str(mcp_name or "").startswith("browser_"):
                forwarded_args = adapt_playwright_tool_args(original_tool_name, forwarded_args)
            res = await mcp_tools_call(mcp_name, forwarded_args)
            parsed = mcp_text_json(res)

            if original_tool_name == "google_calendar_create_event":
                created_event_id: Optional[str] = None
                if isinstance(parsed, dict):
                    data_obj = parsed.get("data") if isinstance(parsed.get("data"), dict) else None
                    if isinstance(data_obj, dict):
                        created_event_id = str(data_obj.get("id") or "").strip() or None
                after_event = await google_calendar_fetch_event(event_id=created_event_id) if created_event_id else None
                undo_id = google_calendar_undo_log("google_calendar_create_event", created_event_id, before=None, after=after_event)
                await undo_sheet_append(
                    {
                        "event": "recorded",
                        "confirmation_id": confirmation_id,
                        "undo_id": undo_id,
                        "scope": "google_calendar",
                        "action": "google_calendar_create_event",
                        "event_id": created_event_id,
                        "before": None,
                        "after": after_event,
                    }
                )
                if session_id and created_event_id:
                    set_session_last_item(str(session_id), "last_created", "calendar_event", {"event_id": created_event_id})
            elif original_tool_name == "google_calendar_update_event":
                after_event2 = await google_calendar_fetch_event(event_id=event_id) if event_id else None
                undo_id2 = google_calendar_undo_log("google_calendar_update_event", event_id, before=before_event, after=after_event2)
                await undo_sheet_append(
                    {
                        "event": "recorded",
                        "confirmation_id": confirmation_id,
                        "undo_id": undo_id2,
                        "scope": "google_calendar",
                        "action": "google_calendar_update_event",
                        "event_id": event_id,
                        "before": before_event,
                        "after": after_event2,
                    }
                )
                if session_id and event_id:
                    set_session_last_item(str(session_id), "last_modified", "calendar_event", {"event_id": event_id})
            elif original_tool_name == "google_calendar_delete_event":
                undo_id3 = google_calendar_undo_log("google_calendar_delete_event", event_id, before=before_event, after=None)
                await undo_sheet_append(
                    {
                        "event": "recorded",
                        "confirmation_id": confirmation_id,
                        "undo_id": undo_id3,
                        "scope": "google_calendar",
                        "action": "google_calendar_delete_event",
                        "event_id": event_id,
                        "before": before_event,
                        "after": None,
                    }
                )
                if session_id and event_id:
                    set_session_last_item(str(session_id), "last_modified", "calendar_event", {"event_id": event_id})

            if original_tool_name == "google_tasks_create_task":
                created_task_id: Optional[str] = None
                after_task: Optional[dict[str, Any]] = None
                if isinstance(parsed, dict):
                    data_obj2 = parsed.get("data") if isinstance(parsed.get("data"), dict) else None
                    if isinstance(data_obj2, dict):
                        created_task_id = str(data_obj2.get("id") or "").strip() or None
                        after_task = data_obj2
                tasklist_id2 = str(mcp_args.get("tasklist_id") or "").strip() or None
                if tasklist_id2 and created_task_id and after_task is None:
                    after_task = await google_tasks_fetch_task(tasklist_id=tasklist_id2, task_id=created_task_id)
                undo_id4 = google_tasks_undo_log("google_tasks_create_task", tasklist_id2, created_task_id, None, after_task)
                await undo_sheet_append(
                    {
                        "event": "recorded",
                        "confirmation_id": confirmation_id,
                        "undo_id": undo_id4,
                        "scope": "google_tasks",
                        "action": "google_tasks_create_task",
                        "tasklist_id": tasklist_id2,
                        "task_id": created_task_id,
                        "before": None,
                        "after": after_task,
                    }
                )
                if session_id and created_task_id:
                    set_session_last_item(
                        str(session_id),
                        "last_created",
                        "task",
                        {"task_id": created_task_id, "tasklist_id": tasklist_id2},
                    )
            elif original_tool_name in (
                "google_tasks_update_task",
                "google_tasks_complete_task",
                "google_tasks_delete_task",
            ):
                after_task2: Optional[dict[str, Any]] = None
                if original_tool_name != "google_tasks_delete_task" and task_id and tasklist_id:
                    after_task2 = await google_tasks_fetch_task(tasklist_id=tasklist_id, task_id=task_id)
                undo_id5 = google_tasks_undo_log(original_tool_name, tasklist_id, task_id, before_task, after_task2)
                await undo_sheet_append(
                    {
                        "event": "recorded",
                        "confirmation_id": confirmation_id,
                        "undo_id": undo_id5,
                        "scope": "google_tasks",
                        "action": original_tool_name,
                        "tasklist_id": tasklist_id,
                        "task_id": task_id,
                        "before": before_task,
                        "after": after_task2,
                    }
                )
                if session_id and task_id:
                    set_session_last_item(
                        str(session_id),
                        "last_modified",
                        "task",
                        {"task_id": task_id, "tasklist_id": tasklist_id},
                    )

            return res
        raise HTTPException(status_code=400, detail={"unknown_pending_action": action})

    if tool_name == "pending_cancel":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        cancel_pending_write = deps["cancel_pending_write"]
        cancel_pending_write_any_session = deps.get("cancel_pending_write_any_session")
        session_ws = deps.get("SESSION_WS")
        get_pending_write_any_session = deps.get("get_pending_write_any_session")
        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        owner_session_id: str | None = str(session_id)
        ok = cancel_pending_write(session_id, confirmation_id)
        if not ok and cancel_pending_write_any_session and isinstance(session_ws, dict):
            ws = session_ws.get(str(session_id))
            is_admin = bool(getattr(getattr(ws, "state", None), "is_admin", False)) if ws is not None else False
            if is_admin:
                if get_pending_write_any_session is not None:
                    try:
                        out_any = get_pending_write_any_session(confirmation_id)
                        if isinstance(out_any, dict):
                            owner_session_id = str(out_any.get("session_id") or "").strip() or None
                    except Exception:
                        pass
                ok = bool(cancel_pending_write_any_session(confirmation_id))
        if not ok:
            raise HTTPException(status_code=404, detail="pending_write_not_found")

        # Emit best-effort event (owner + actor session).
        try:
            ev = {"type": "pending_event", "event": "cancelled", "confirmation_id": confirmation_id}
            ws_owner = session_ws.get(str(owner_session_id)) if isinstance(session_ws, dict) and owner_session_id else None
            ws_actor = session_ws.get(str(session_id)) if isinstance(session_ws, dict) and session_id else None
            if ws_owner is not None:
                await ws_owner.send_json(ev)
            if ws_actor is not None and ws_actor is not ws_owner:
                await ws_actor.send_json(ev)
        except Exception:
            pass
        return {"ok": True}

    if tool_name == "pending_reassign":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        session_ws = deps.get("SESSION_WS")
        reassign_pending_write = deps.get("reassign_pending_write")
        get_pending_write_any_session = deps.get("get_pending_write_any_session")
        if not reassign_pending_write:
            raise HTTPException(status_code=500, detail="missing_reassign_pending_write")
        ws = session_ws.get(str(session_id)) if isinstance(session_ws, dict) else None
        is_admin = bool(getattr(getattr(ws, "state", None), "is_admin", False)) if ws is not None else False
        if not is_admin:
            raise HTTPException(status_code=403, detail="admin_required")
        confirmation_id = str(args.get("confirmation_id") or "").strip()
        new_session_id = str(args.get("new_session_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        if not new_session_id:
            raise HTTPException(status_code=400, detail="missing_new_session_id")

        prev_owner: str | None = None
        if get_pending_write_any_session is not None:
            try:
                out_any = get_pending_write_any_session(confirmation_id)
                if isinstance(out_any, dict):
                    prev_owner = str(out_any.get("session_id") or "").strip() or None
            except Exception:
                prev_owner = None

        ok = bool(reassign_pending_write(confirmation_id, new_session_id))
        if not ok:
            raise HTTPException(status_code=404, detail="pending_write_not_found")

        # Emit best-effort event (prev owner, new owner, actor).
        try:
            ev = {
                "type": "pending_event",
                "event": "reassigned",
                "confirmation_id": confirmation_id,
                "new_session_id": new_session_id,
                "prev_session_id": prev_owner,
            }
            if isinstance(session_ws, dict):
                ws_prev = session_ws.get(str(prev_owner)) if prev_owner else None
                ws_new = session_ws.get(str(new_session_id)) if new_session_id else None
                ws_actor = session_ws.get(str(session_id)) if session_id else None
                if ws_prev is not None:
                    await ws_prev.send_json(ev)
                if ws_new is not None and ws_new is not ws_prev:
                    await ws_new.send_json(ev)
                if ws_actor is not None and ws_actor is not ws_prev and ws_actor is not ws_new:
                    await ws_actor.send_json(ev)
        except Exception:
            pass
        return {"ok": True}

    mcp_tool_map = deps["MCP_TOOL_MAP"]
    meta = mcp_tool_map.get(tool_name) if isinstance(mcp_tool_map, dict) else None
    if not meta:
        raise HTTPException(status_code=400, detail={"unknown_tool": tool_name})

    mcp_name = str(meta.get("mcp_name") or "")
    if not mcp_name:
        raise HTTPException(status_code=500, detail="mcp_tool_missing_mapping")

    requires_confirmation = bool(meta.get("requires_confirmation"))
    mcp_base = str(meta.get("mcp_base") or "").strip().lower()

    if requires_confirmation:
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        create_pending_write = deps["create_pending_write"]
        pending_payload = {"mcp_name": mcp_name, "arguments": dict(args), "mcp_base": mcp_base, "tool_name": tool_name}
        confirmation_id = create_pending_write(
            session_id,
            action="mcp_tools_call",
            payload=pending_payload,
        )
        await _emit_pending_awaiting_user(session_id0=str(session_id), confirmation_id=confirmation_id, action="mcp_tools_call", payload=pending_payload)
        return {
            "requires_confirmation": True,
            "confirmation_id": confirmation_id,
            "action": tool_name,
            "payload": args,
        }

    if mcp_base == "aim":
        adapt_aim_tool_args = deps["adapt_aim_tool_args"]
        aim_mcp_tools_call = deps["aim_mcp_tools_call"]
        get_user_timezone = deps["get_user_timezone"]
        default_user_id = deps["DEFAULT_USER_ID"]
        parse_time_from_text = deps["parse_time_from_text"]
        google_calendar_create_reminder_event = deps["google_calendar_create_reminder_event"]
        datetime = deps["datetime"]
        timezone = deps["timezone"]
        logger = deps.get("logger")

        adapted = adapt_aim_tool_args(tool_name, dict(args))
        result = await aim_mcp_tools_call(mcp_name, adapted)

        if tool_name == "aim_memory_store":
            try:
                entities = adapted.get("entities")
                if isinstance(entities, list) and entities:
                    ent0 = entities[0] if isinstance(entities[0], dict) else {}
                    title = str(ent0.get("name") or "Reminder").strip() or "Reminder"
                    obs = ent0.get("observations")
                    source_text = ""
                    if isinstance(obs, list) and obs:
                        source_text = str(obs[0])

                    tz = get_user_timezone(default_user_id)
                    now = datetime.now(tz=timezone.utc)
                    due_at_utc, _ = parse_time_from_text(source_text, now, tz)
                    if due_at_utc is not None:
                        cal = await google_calendar_create_reminder_event(
                            title=title,
                            due_at_utc=due_at_utc,
                            tz=tz,
                            source_text=source_text,
                        )
                        return {"aim": result, "calendar": cal}
            except Exception as e:
                try:
                    if logger is not None:
                        logger.warning("reminder_create_failed error=%s", e)
                except Exception:
                    pass
        return result

    mcp_tools_call = deps["mcp_tools_call"]
    adapt_playwright_tool_args = deps["adapt_playwright_tool_args"]

    forwarded_args = dict(args)
    if str(mcp_name or "").startswith("browser_"):
        forwarded_args = adapt_playwright_tool_args(tool_name, forwarded_args)
    return await mcp_tools_call(mcp_name, forwarded_args)
