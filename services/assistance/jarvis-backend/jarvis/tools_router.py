from __future__ import annotations

from typing import Any, Optional


async def handle_mcp_tool_call(session_id: Optional[str], tool_name: str, args: dict[str, Any], *, deps: dict[str, Any]) -> Any:
    HTTPException = deps["HTTPException"]

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
            row: list[Any] = []
            _set(row, "id", memo_id)
            if active is None:
                _set(row, "active", True)
            else:
                _set(row, "active", bool(active))
            _set(row, "group", group)
            _set(row, "subject", subject)
            _set(row, "memo", memo_txt)
            _set(row, "status", status)
            _set(row, "result", result)
            _set(row, "date_time", now_dt)
            _set(row, "_created", now_dt)
            _set(row, "_updated", now_dt)

            tool_append = pick_sheets_tool_name("google_sheets_values_append", "google_sheets_values_append")
            res = await mcp_tools_call(
                tool_append,
                {
                    "spreadsheet_id": spreadsheet_id,
                    "range": f"{sheet_a1}!A:Z",
                    "values": [row],
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

    if tool_name == "pending_confirm":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")

        pop_pending_write = deps["pop_pending_write"]
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
        pending = pop_pending_write(session_id, confirmation_id)
        if not pending:
            raise HTTPException(status_code=404, detail="pending_write_not_found")
        action = str(pending.get("action") or "")
        payload = pending.get("payload")
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
