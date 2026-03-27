from __future__ import annotations

import json
from typing import Any, Optional


async def handle_mcp_tool_call(session_id: Optional[str], tool_name: str, args: dict[str, Any], *, deps: dict[str, Any]) -> Any:
    HTTPException = deps["HTTPException"]

    if tool_name == "memo_header_assess":
        session_ws = deps["SESSION_WS"]
        feature_enabled = deps["feature_enabled"]
        sys_kv_bool = deps["sys_kv_bool"]
        memo_sheet_cfg_from_sys_kv = deps["memo_sheet_cfg_from_sys_kv"]
        sheet_name_to_a1 = deps["sheet_name_to_a1"]
        sheet_get_header_row = deps["sheet_get_header_row"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        sys_kv = getattr(ws.state, "sys_kv", None)
        if not feature_enabled("memo", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
            raise HTTPException(status_code=403, detail="feature_disabled:memo")
        if not sys_kv_bool(sys_kv, "memo.enabled", False):
            raise HTTPException(status_code=403, detail="memo_disabled")

        spreadsheet_id, sheet_name = memo_sheet_cfg_from_sys_kv(sys_kv if isinstance(sys_kv, dict) else None)
        if not spreadsheet_id:
            raise HTTPException(status_code=400, detail="missing_memo_ss")
        if not sheet_name:
            raise HTTPException(status_code=400, detail="missing_memo_sheet_name")

        sheet_a1 = sheet_name_to_a1(sheet_name, default="memo")
        header = await sheet_get_header_row(spreadsheet_id=spreadsheet_id, sheet_a1=sheet_a1, max_cols="J")
        got = [str(x or "").strip().lower() for x in (header or [])]
        expected = [
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
        ]

        ok = got[: len(expected)] == expected
        if not ok:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "memo_header_mismatch",
                    "spreadsheet_id": spreadsheet_id,
                    "sheet": sheet_name,
                    "got": got,
                    "expected": expected,
                },
            )

        return {"ok": True, "spreadsheet_id": spreadsheet_id, "sheet": sheet_name, "header": expected}

    if tool_name == "memo_assess":
        session_ws = deps["SESSION_WS"]
        feature_enabled = deps["feature_enabled"]
        sys_kv_bool = deps["sys_kv_bool"]
        safe_int = deps["safe_int"]
        gemini_summarize_text = deps["gemini_summarize_text"]

        ws = session_ws.get(str(session_id)) if session_id else None
        if ws is None:
            raise HTTPException(status_code=400, detail="missing_session_ws")

        sys_kv = getattr(ws.state, "sys_kv", None)
        if not feature_enabled("memo", sys_kv=sys_kv if isinstance(sys_kv, dict) else None, default=True):
            raise HTTPException(status_code=403, detail="feature_disabled:memo")
        if not sys_kv_bool(sys_kv, "memo.enabled", False):
            raise HTTPException(status_code=403, detail="memo_disabled")

        memo_id = safe_int(args.get("id"), 0)
        memo_txt = str(args.get("memo") or "").strip()
        if not memo_txt and memo_id > 0:
            try:
                last_memo = getattr(ws.state, "last_memo", None)
            except Exception:
                last_memo = None
            if isinstance(last_memo, dict):
                try:
                    last_id = safe_int(last_memo.get("id"), 0)
                except Exception:
                    last_id = 0
                if last_id == int(memo_id):
                    memo_txt = str(last_memo.get("memo") or "").strip()
                    # Use current fields as defaults when not provided.
                    if "group" not in args:
                        args = {**args, "group": last_memo.get("group")}
                    if "subject" not in args:
                        args = {**args, "subject": last_memo.get("subject")}
                    if "status" not in args:
                        args = {**args, "status": last_memo.get("status")}
                    if "result" not in args:
                        args = {**args, "result": last_memo.get("result")}
        if not memo_txt:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "memo_missing_text",
                    "hint": "Call memo_assess with memo text, or first load a memo by id (e.g. `memo 61`) then call memo_assess with that same id.",
                },
            )

        payload = {
            "id": memo_id if memo_id > 0 else None,
            "memo": memo_txt,
            "group": str(args.get("group") or "").strip(),
            "subject": str(args.get("subject") or "").strip(),
            "status": str(args.get("status") or "").strip(),
            "result": str(args.get("result") or "").strip(),
        }

        sys_kv = getattr(ws.state, "sys_kv", None)
        model_primary = ""
        model_fallbacks: list[str] = []
        if isinstance(sys_kv, dict):
            try:
                model_primary = str(sys_kv.get("gemini.text.model_toolcall") or "").strip()
            except Exception:
                model_primary = ""
            try:
                raw_fb = sys_kv.get("gemini.text.fallback_models_json")
                if isinstance(raw_fb, str) and raw_fb.strip():
                    parsed_fb = json.loads(raw_fb)
                    if isinstance(parsed_fb, list):
                        model_fallbacks = [str(x or "").strip() for x in parsed_fb if str(x or "").strip()]
            except Exception:
                pass

        candidates: list[str | None] = []
        candidates.append(model_primary or None)
        candidates.extend([m for m in model_fallbacks if m])
        if not any(candidates):
            candidates = [None]

        system_instruction = (
            "You are an operations assistant. Given a memo entry, propose improved fields and a cleaned memo text. "
            "Return ONLY valid JSON with keys: memo, group, subject, status, result, rationale. "
            "Never include markdown, code fences, or commentary. "
            "Keep changes minimal and do not invent facts."
        )
        last_err: Exception | None = None
        txt: Any = None
        for cand in candidates:
            try:
                txt = await gemini_summarize_text(
                    system_instruction=system_instruction,
                    prompt=json.dumps(payload, ensure_ascii=False),
                    model=str(cand) if cand else None,
                )
                last_err = None
                break
            except Exception as e:
                last_err = e
                # Common failure mode: upstream LLM quota exhausted (HTTP 429).
                if isinstance(e, HTTPException) and int(getattr(e, "status_code", 0) or 0) == 429:
                    memo_clean = "\n".join([ln.strip() for ln in memo_txt.splitlines()]).strip()
                    memo_one_line = " ".join(memo_clean.split())
                    subject_guess = str(args.get("subject") or "").strip()
                    if not subject_guess:
                        subject_guess = memo_one_line[:80].strip()
                    group_guess = str(args.get("group") or "").strip() or "general"
                    status_guess = str(args.get("status") or "").strip() or "new"
                    result_guess = str(args.get("result") or "").strip()
                    parsed_fallback = {
                        "memo": memo_clean,
                        "group": group_guess,
                        "subject": subject_guess,
                        "status": status_guess,
                        "result": result_guess,
                        "rationale": "fallback: quota_exhausted (429) - heuristic suggestion; please retry later for LLM-quality assessment",
                        "degraded": True,
                    }
                    out_fb: dict[str, Any] = {"ok": True, "suggestion": parsed_fallback}
                    if memo_id > 0:
                        out_fb["id"] = memo_id
                    return out_fb
                continue

        if last_err is not None:
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "memo_assess_failed",
                    "detail": str(last_err),
                    "models_tried": [str(x) for x in candidates if x],
                },
            )
        raw = str(txt or "")
        s = raw.strip()
        if s.startswith("```"):
            s = s.strip("`")
            s = s.strip()
            if s.lower().startswith("json"):
                s = s[4:].strip()
        try:
            parsed = json.loads(s)
        except Exception:
            raise HTTPException(status_code=502, detail={"error": "memo_assess_invalid_json", "raw": raw[:800]})
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=502, detail={"error": "memo_assess_invalid_json", "raw": raw[:800]})

        out: dict[str, Any] = {"ok": True, "suggestion": parsed}
        if memo_id > 0:
            out["id"] = memo_id
        return out

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
        return {"ok": True, "queued": True, "confirmation_id": confirmation_id, "id": int(memo_id)}

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
            raise HTTPException(status_code=403, detail={"error": "action_not_allowed", "action": action})

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
        return {
            "ok": True,
            "queued": True,
            "confirmation_id": confirmation_id,
            "action": action,
            "supported_actions": supported_actions,
        }

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
        confirmation_id = create_pending_write(str(session_id), "system_reload", {"mode": mode})
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
        confirmation_id = create_pending_write(
            str(session_id),
            "bundle_publish_macro_reload",
            {"macro": macro_args, "reload_mode": mode},
        )
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
            confirmation_id = create_pending_write(
                str(session_id),
                action="mcp_tools_call",
                payload={
                    "mcp_name": tool_append,
                    "arguments": {
                        "spreadsheet_id": spreadsheet_id,
                        "range": f"{sheet_name}!A:Z",
                        "values": [row_out],
                        "value_input_option": "RAW",
                    },
                    "mcp_base": "",
                    "tool_name": "google_sheets_values_append",
                },
            )
            return {"ok": True, "queued": True, "action": "insert", "name": name, "confirmation_id": confirmation_id}

        tool_update = pick_sheets_tool_name("google_sheets_values_update", "google_sheets_values_update")
        start_col = _col_letter(0)
        end_col = _col_letter(max_col)
        confirmation_id2 = create_pending_write(
            str(session_id),
            action="mcp_tools_call",
            payload={
                "mcp_name": tool_update,
                "arguments": {
                    "spreadsheet_id": spreadsheet_id,
                    "range": f"{sheet_name}!{start_col}{found_row_num}:{end_col}{found_row_num}",
                    "values": [row_out],
                    "value_input_option": "RAW",
                },
                "mcp_base": "",
                "tool_name": "google_sheets_values_update",
            },
        )
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
        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        out = get_pending_write(str(session_id), confirmation_id)
        if not out:
            raise HTTPException(status_code=404, detail="pending_write_not_found")
        return out

    if tool_name == "pending_preview":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        get_pending_write = deps["get_pending_write"]
        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        item = get_pending_write(str(session_id), confirmation_id)
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
        else:
            preview["risk"] = "high"
            preview["summary"] = action or "pending"

        return preview

    if tool_name == "pending_confirm":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")

        pop_pending_write = deps["pop_pending_write"]
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

        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        user_input = args.get("input") if isinstance(args.get("input"), dict) else {}
        pending = pop_pending_write(session_id, confirmation_id)
        if not pending:
            raise HTTPException(status_code=404, detail="pending_write_not_found")
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

        if action == "google_account_relink":
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")
            code_or_url = str(user_input.get("code_or_redirected_url") or "").strip()
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
        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        ok = cancel_pending_write(session_id, confirmation_id)
        if not ok:
            raise HTTPException(status_code=404, detail="pending_write_not_found")
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
        confirmation_id = create_pending_write(
            session_id,
            action="mcp_tools_call",
            payload={"mcp_name": mcp_name, "arguments": dict(args), "mcp_base": mcp_base, "tool_name": tool_name},
        )
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
