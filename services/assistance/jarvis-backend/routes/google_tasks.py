from __future__ import annotations

from typing import Any, Optional, Callable, Awaitable

from fastapi import APIRouter, HTTPException

from google_schemas import (
    GoogleTasksSequentialItem,
    GoogleTasksSequentialSummaryResponse,
    GoogleTasksCreateTaskRequest,
    GoogleTasksCompleteTaskRequest,
    GoogleTasksDeleteTaskRequest,
    GoogleTasksUpdateTaskRequest,
    GoogleTasksWriteResponse,
    GoogleTasksUndoItem,
    GoogleTasksUndoLastRequest,
    GoogleTasksUndoListResponse,
    GoogleTasksUndoResponse,
)


def create_router(
    *,
    mcp_tool_map: dict[str, dict[str, Any]],
    mcp_tools_call: Callable[[str, dict[str, Any]], Awaitable[Any]],
    mcp_tools_call_with_progress: Optional[Callable[[Any, str, dict[str, Any], str], Awaitable[Any]]] = None,
    mcp_text_json: Callable[[Any], Any],
    require_confirmation: Callable[[bool, str, Any], None],
    resolve_tasklist: Callable[[Optional[str], Optional[str]], Awaitable[tuple[Optional[str], str]]],
    fetch_task: Callable[[str, str], Awaitable[Optional[dict[str, Any]]]],
    undo_log: Callable[[str, Optional[str], Optional[str], Any, Any], str],
    undo_sheet_append: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
    undo_list: Callable[[int], list[dict[str, Any]]],
    undo_pop_last: Callable[[int], list[dict[str, Any]]],
    parse_checklist_steps: Callable[[str], list[Any]],
    next_actionable_step: Callable[[list[Any]], Any],
    suggest_template_from_completed_tasks: Callable[[list[dict[str, Any]]], Optional[list[str]]],
) -> APIRouter:
    router = APIRouter()

    @router.get("/google-tasks/sequential/summary", response_model=GoogleTasksSequentialSummaryResponse)
    async def google_tasks_sequential_summary(
        tasklist_id: Optional[str] = None,
        tasklist_title: Optional[str] = None,
        max_results: int = 50,
        show_completed: bool = True,
        only_incomplete: bool = False,
        only_with_notes: bool = False,
        only_with_checklists: bool = False,
        include_notes: bool = True,
        debug: bool = False,
    ) -> GoogleTasksSequentialSummaryResponse:
        auth_meta = mcp_tool_map.get("google_tasks_auth_status") if isinstance(mcp_tool_map, dict) else None
        list_tasklists_meta = mcp_tool_map.get("google_tasks_list_tasklists") if isinstance(mcp_tool_map, dict) else None
        list_tasks_meta = mcp_tool_map.get("google_tasks_list_tasks") if isinstance(mcp_tool_map, dict) else None

        if not isinstance(auth_meta, dict) or not isinstance(list_tasklists_meta, dict) or not isinstance(list_tasks_meta, dict):
            raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")

        auth_tool = str(auth_meta.get("mcp_name") or "").strip()
        list_tasklists_tool = str(list_tasklists_meta.get("mcp_name") or "").strip()
        list_tasks_tool = str(list_tasks_meta.get("mcp_name") or "").strip()
        if not auth_tool or not list_tasklists_tool or not list_tasks_tool:
            raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")

        try:
            auth_res = await mcp_tools_call(auth_tool, {})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail={"google_tasks_auth_status_failed": str(e)})

        auth_parsed = mcp_text_json(auth_res)
        if isinstance(auth_parsed, dict):
            if not bool(auth_parsed.get("ok", True)):
                raise HTTPException(status_code=401, detail="google_tasks_not_authenticated")

        chosen_tasklist_id = str(tasklist_id or "").strip()
        desired_tasklist_title = str(tasklist_title or "").strip()
        chosen_tasklist_title = ""
        debug_meta: dict[str, Any] = {}

        if not chosen_tasklist_id or desired_tasklist_title:
            try:
                tl_res = await mcp_tools_call(list_tasklists_tool, {})
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=502, detail={"google_tasks_list_tasklists_failed": str(e)})

            tl_parsed = mcp_text_json(tl_res)
            if isinstance(tl_parsed, dict):
                data_obj = tl_parsed.get("data")
                if isinstance(data_obj, dict):
                    tl_parsed = data_obj
            tasklists = None
            if isinstance(tl_parsed, dict):
                tasklists = tl_parsed.get("tasklists")
                if not isinstance(tasklists, list):
                    tasklists = tl_parsed.get("items")
                if not isinstance(tasklists, list):
                    tasklists = tl_parsed.get("lists")
            if not isinstance(tasklists, list) or not tasklists:
                raise HTTPException(status_code=404, detail="google_tasks_no_tasklists")

            debug_meta["tasklists_count"] = len(tasklists)

            if desired_tasklist_title:
                wanted = desired_tasklist_title.casefold()
                match = None
                for tl in tasklists:
                    if not isinstance(tl, dict):
                        continue
                    title = str(tl.get("title") or "").strip()
                    if title.casefold() == wanted:
                        match = tl
                        break
                if match is None:
                    raise HTTPException(status_code=404, detail="google_tasks_tasklist_title_not_found")
                chosen_tasklist_id = str(match.get("id") or "").strip()
                chosen_tasklist_title = str(match.get("title") or "").strip()
                if not chosen_tasklist_id:
                    raise HTTPException(status_code=502, detail="google_tasks_tasklist_missing_id")
                debug_meta["tasklist_selected_by"] = "title"
            else:
                if not chosen_tasklist_id:
                    tl0 = tasklists[0] if isinstance(tasklists[0], dict) else {}
                    chosen_tasklist_id = str(tl0.get("id") or "").strip()
                    chosen_tasklist_title = str(tl0.get("title") or "").strip()
                    if not chosen_tasklist_id:
                        raise HTTPException(status_code=502, detail="google_tasks_tasklist_missing_id")
                    debug_meta["tasklist_selected_by"] = "first"
                else:
                    for tl in tasklists:
                        if not isinstance(tl, dict):
                            continue
                        if str(tl.get("id") or "").strip() == chosen_tasklist_id:
                            chosen_tasklist_title = str(tl.get("title") or "").strip()
                            break
                    debug_meta["tasklist_selected_by"] = "id"

        if not chosen_tasklist_id:
            raise HTTPException(status_code=400, detail="missing_tasklist_id")

        args: dict[str, Any] = {
            "tasklist_id": chosen_tasklist_id,
            "max_results": int(max(1, min(100, int(max_results or 50)))),
            "show_completed": bool(show_completed),
        }

        try:
            tasks_res = await mcp_tools_call(list_tasks_tool, args)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail={"google_tasks_list_tasks_failed": str(e)})

        tasks_parsed = mcp_text_json(tasks_res)
        if isinstance(tasks_parsed, dict):
            data_obj = tasks_parsed.get("data")
            if isinstance(data_obj, dict):
                tasks_parsed = data_obj
        tasks_raw = None
        if isinstance(tasks_parsed, dict):
            tasks_raw = tasks_parsed.get("tasks")
            if not isinstance(tasks_raw, list):
                tasks_raw = tasks_parsed.get("items")
        if not isinstance(tasks_raw, list):
            tasks_raw = []

        items: list[GoogleTasksSequentialItem] = []
        completed_for_template: list[dict[str, Any]] = []
        filters: list[str] = []
        if only_incomplete:
            filters.append("only_incomplete")
        if only_with_notes:
            filters.append("only_with_notes")
        if only_with_checklists:
            filters.append("only_with_checklists")
        if not include_notes:
            filters.append("include_notes=false")

        debug_meta["tasks_raw_count"] = len(tasks_raw)
        debug_meta["filters"] = filters

        for t in tasks_raw:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("id") or t.get("task_id") or "").strip()
            title = str(t.get("title") or "").strip()
            status = str(t.get("status") or "").strip() or "needsAction"
            notes = str(t.get("notes") or "")

            if only_incomplete and status == "completed":
                continue
            if only_with_notes and not str(notes).strip():
                continue

            has_checklist = False
            next_step_text: Optional[str] = None
            next_step_index: Optional[int] = None
            if notes:
                steps = parse_checklist_steps(notes)
                has_checklist = bool(steps)
                next_step = next_actionable_step(steps)
                if next_step is not None:
                    try:
                        next_step_text = str(getattr(next_step, "text", "") or "")
                    except Exception:
                        next_step_text = None
                    for i, s in enumerate(steps):
                        if s == next_step:
                            next_step_index = i
                            break
            if only_with_checklists and not has_checklist:
                continue

            items.append(
                GoogleTasksSequentialItem(
                    task_id=tid,
                    title=title,
                    status=status,
                    notes=notes if include_notes else "",
                    next_step_text=next_step_text,
                    next_step_index=next_step_index,
                )
            )
            if status == "completed":
                completed_for_template.append({"notes": notes})

        template = suggest_template_from_completed_tasks(completed_for_template) if completed_for_template else None

        return GoogleTasksSequentialSummaryResponse(
            ok=True,
            tasklist_id=chosen_tasklist_id,
            tasklist_title=chosen_tasklist_title,
            tasks=items,
            template=template,
            debug=debug_meta if debug else None,
        )

    @router.post("/google-tasks/tasks/create", response_model=GoogleTasksWriteResponse)
    async def google_tasks_create_task(req: GoogleTasksCreateTaskRequest) -> GoogleTasksWriteResponse:
        title = str(req.title or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="missing_title")

        action = "google_tasks_create_task"
        preview_payload: dict[str, Any] = {
            "tasklist_id": (str(req.tasklist_id or "").strip() or None),
            "tasklist_title": (str(req.tasklist_title or "").strip() or None),
            "title": title,
            "notes": str(req.notes or ""),
            "due": str(req.due).strip() if req.due else None,
        }
        preview_payload = {k: v for k, v in preview_payload.items() if v is not None}
        require_confirmation(bool(req.confirm), action, preview_payload)

        tasklist_id_resolved, _ = await resolve_tasklist(req.tasklist_id, req.tasklist_title)
        payload: dict[str, Any] = {
            "tasklist_id": tasklist_id_resolved,
            "title": title,
            "notes": str(req.notes or ""),
            "due": str(req.due).strip() if req.due else None,
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        meta = mcp_tool_map.get(action) if isinstance(mcp_tool_map, dict) else None
        if not isinstance(meta, dict):
            raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")
        mcp_name = str(meta.get("mcp_name") or "").strip()
        if not mcp_name:
            raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")

        res = await mcp_tools_call(mcp_name, payload)
        parsed = mcp_text_json(res)
        created_task_id = ""
        after: Any = None
        if isinstance(parsed, dict):
            data_obj = parsed.get("data")
            if isinstance(data_obj, dict):
                after = data_obj
                created_task_id = str(data_obj.get("id") or "").strip()

        undo_id = undo_log("google_tasks_create_task", tasklist_id_resolved, created_task_id or None, None, after)
        if undo_sheet_append is not None:
            try:
                await undo_sheet_append(
                    {
                        "event": "recorded",
                        "undo_id": undo_id,
                        "scope": "google_tasks",
                        "action": "google_tasks_create_task",
                        "tasklist_id": tasklist_id_resolved,
                        "task_id": created_task_id or None,
                        "before": None,
                        "after": after,
                    }
                )
            except Exception:
                pass
        return GoogleTasksWriteResponse(ok=True, result=parsed if isinstance(parsed, dict) else {"raw": parsed})

    @router.post("/google-tasks/tasks/complete", response_model=GoogleTasksWriteResponse)
    async def google_tasks_complete_task(req: GoogleTasksCompleteTaskRequest) -> GoogleTasksWriteResponse:
        task_id = str(req.task_id or "").strip()
        if not task_id:
            raise HTTPException(status_code=400, detail="missing_task_id")

        action = "google_tasks_complete_task"
        preview_payload: dict[str, Any] = {
            "tasklist_id": (str(req.tasklist_id or "").strip() or None),
            "tasklist_title": (str(req.tasklist_title or "").strip() or None),
            "task_id": task_id,
        }
        preview_payload = {k: v for k, v in preview_payload.items() if v is not None}
        require_confirmation(bool(req.confirm), action, preview_payload)

        tasklist_id_resolved, _ = await resolve_tasklist(req.tasklist_id, req.tasklist_title)
        before = await fetch_task(str(tasklist_id_resolved or ""), task_id) if tasklist_id_resolved else None
        payload: dict[str, Any] = {"tasklist_id": tasklist_id_resolved, "task_id": task_id}
        payload = {k: v for k, v in payload.items() if v is not None}

        meta = mcp_tool_map.get(action) if isinstance(mcp_tool_map, dict) else None
        if not isinstance(meta, dict):
            raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")
        mcp_name = str(meta.get("mcp_name") or "").strip()
        if not mcp_name:
            raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")

        res = await mcp_tools_call(mcp_name, payload)
        parsed = mcp_text_json(res)
        after = await fetch_task(str(tasklist_id_resolved or ""), task_id) if tasklist_id_resolved else None
        undo_id = undo_log("google_tasks_complete_task", tasklist_id_resolved, task_id, before, after)
        if undo_sheet_append is not None:
            try:
                await undo_sheet_append(
                    {
                        "event": "recorded",
                        "undo_id": undo_id,
                        "scope": "google_tasks",
                        "action": "google_tasks_complete_task",
                        "tasklist_id": tasklist_id_resolved,
                        "task_id": task_id,
                        "before": before,
                        "after": after,
                    }
                )
            except Exception:
                pass
        return GoogleTasksWriteResponse(ok=True, result=parsed if isinstance(parsed, dict) else {"raw": parsed})

    @router.post("/google-tasks/tasks/delete", response_model=GoogleTasksWriteResponse)
    async def google_tasks_delete_task(req: GoogleTasksDeleteTaskRequest) -> GoogleTasksWriteResponse:
        task_id = str(req.task_id or "").strip()
        if not task_id:
            raise HTTPException(status_code=400, detail="missing_task_id")

        action = "google_tasks_delete_task"
        preview_payload: dict[str, Any] = {
            "tasklist_id": (str(req.tasklist_id or "").strip() or None),
            "tasklist_title": (str(req.tasklist_title or "").strip() or None),
            "task_id": task_id,
        }
        preview_payload = {k: v for k, v in preview_payload.items() if v is not None}
        require_confirmation(bool(req.confirm), action, preview_payload)

        tasklist_id_resolved, _ = await resolve_tasklist(req.tasklist_id, req.tasklist_title)
        before = await fetch_task(str(tasklist_id_resolved or ""), task_id) if tasklist_id_resolved else None
        payload: dict[str, Any] = {"tasklist_id": tasklist_id_resolved, "task_id": task_id}
        payload = {k: v for k, v in payload.items() if v is not None}

        meta = mcp_tool_map.get(action) if isinstance(mcp_tool_map, dict) else None
        if not isinstance(meta, dict):
            raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")
        mcp_name = str(meta.get("mcp_name") or "").strip()
        if not mcp_name:
            raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")

        res = await mcp_tools_call(mcp_name, payload)
        parsed = mcp_text_json(res)
        undo_id = undo_log("google_tasks_delete_task", tasklist_id_resolved, task_id, before, None)
        if undo_sheet_append is not None:
            try:
                await undo_sheet_append(
                    {
                        "event": "recorded",
                        "undo_id": undo_id,
                        "scope": "google_tasks",
                        "action": "google_tasks_delete_task",
                        "tasklist_id": tasklist_id_resolved,
                        "task_id": task_id,
                        "before": before,
                        "after": None,
                    }
                )
            except Exception:
                pass
        return GoogleTasksWriteResponse(ok=True, result=parsed if isinstance(parsed, dict) else {"raw": parsed})

    @router.post("/google-tasks/tasks/update", response_model=GoogleTasksWriteResponse)
    async def google_tasks_update_task(req: GoogleTasksUpdateTaskRequest) -> GoogleTasksWriteResponse:
        task_id = str(req.task_id or "").strip()
        if not task_id:
            raise HTTPException(status_code=400, detail="missing_task_id")

        action = "google_tasks_update_task"
        preview_payload: dict[str, Any] = {
            "tasklist_id": (str(req.tasklist_id or "").strip() or None),
            "tasklist_title": (str(req.tasklist_title or "").strip() or None),
            "task_id": task_id,
            "title": (str(req.title).strip() if req.title is not None else None),
            "notes": (str(req.notes) if req.notes is not None else None),
            "due": str(req.due).strip() if req.due else None,
            "status": (str(req.status).strip() if req.status is not None else None),
        }
        preview_payload = {k: v for k, v in preview_payload.items() if v is not None}
        require_confirmation(bool(req.confirm), action, preview_payload)

        tasklist_id_resolved, _ = await resolve_tasklist(req.tasklist_id, req.tasklist_title)
        before = await fetch_task(str(tasklist_id_resolved or ""), task_id) if tasklist_id_resolved else None
        payload: dict[str, Any] = {
            "tasklist_id": tasklist_id_resolved,
            "task_id": task_id,
            "title": (str(req.title).strip() if req.title is not None else None),
            "notes": (str(req.notes) if req.notes is not None else None),
            "due": str(req.due).strip() if req.due else None,
            "status": (str(req.status).strip() if req.status is not None else None),
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        meta = mcp_tool_map.get(action) if isinstance(mcp_tool_map, dict) else None
        if not isinstance(meta, dict):
            raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")
        mcp_name = str(meta.get("mcp_name") or "").strip()
        if not mcp_name:
            raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")

        res = await mcp_tools_call(mcp_name, payload)
        parsed = mcp_text_json(res)
        after = await fetch_task(str(tasklist_id_resolved or ""), task_id) if tasklist_id_resolved else None
        undo_id = undo_log("google_tasks_update_task", tasklist_id_resolved, task_id, before, after)
        if undo_sheet_append is not None:
            try:
                await undo_sheet_append(
                    {
                        "event": "recorded",
                        "undo_id": undo_id,
                        "scope": "google_tasks",
                        "action": "google_tasks_update_task",
                        "tasklist_id": tasklist_id_resolved,
                        "task_id": task_id,
                        "before": before,
                        "after": after,
                    }
                )
            except Exception:
                pass
        return GoogleTasksWriteResponse(ok=True, result=parsed if isinstance(parsed, dict) else {"raw": parsed})

    @router.get("/google-tasks/undo/list", response_model=GoogleTasksUndoListResponse)
    async def google_tasks_undo_list(limit: int = 10) -> GoogleTasksUndoListResponse:
        items = undo_list(limit)
        return GoogleTasksUndoListResponse(ok=True, items=[GoogleTasksUndoItem(**i) for i in items])

    @router.post("/google-tasks/undo/last", response_model=GoogleTasksUndoResponse)
    async def google_tasks_undo_last(req: GoogleTasksUndoLastRequest) -> GoogleTasksUndoResponse:
        n = max(1, min(int(req.n or 1), 50))
        action = "google_tasks_undo_last"
        require_confirmation(bool(req.confirm), action, {"n": n})

        popped = undo_pop_last(n)
        results: list[dict[str, Any]] = []

        for item in popped:
            orig_action = str(item.get("action") or "")
            tasklist_id = str(item.get("tasklist_id") or "").strip() or None
            task_id = str(item.get("task_id") or "").strip() or None
            before = item.get("before")
            undo_id = item.get("undo_id")

            if orig_action == "google_tasks_create_task" and tasklist_id and task_id:
                meta = mcp_tool_map.get("google_tasks_delete_task") if isinstance(mcp_tool_map, dict) else None
                mcp_name = str(meta.get("mcp_name") or "").strip() if isinstance(meta, dict) else ""
                if not mcp_name:
                    raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")
                res = await mcp_tools_call(mcp_name, {"tasklist_id": tasklist_id, "task_id": task_id})
                result_obj = {"undo_id": undo_id, "undone": "delete_created_task", "result": mcp_text_json(res)}
                results.append(result_obj)
                if undo_sheet_append is not None:
                    try:
                        await undo_sheet_append(
                            {
                                "event": "executed",
                                "undo_id": undo_id,
                                "scope": "google_tasks",
                                "action": orig_action,
                                "tasklist_id": tasklist_id,
                                "task_id": task_id,
                                "status": "ok",
                                "result": result_obj,
                            }
                        )
                    except Exception:
                        pass
                continue

            if orig_action in ("google_tasks_update_task", "google_tasks_complete_task") and tasklist_id and task_id and isinstance(before, dict):
                meta = mcp_tool_map.get("google_tasks_update_task") if isinstance(mcp_tool_map, dict) else None
                mcp_name = str(meta.get("mcp_name") or "").strip() if isinstance(meta, dict) else ""
                if not mcp_name:
                    raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")
                payload: dict[str, Any] = {"tasklist_id": tasklist_id, "task_id": task_id}
                for k in ("title", "notes", "due", "status"):
                    if k in before:
                        payload[k] = before.get(k)
                payload = {k: v for k, v in payload.items() if v is not None}
                res = await mcp_tools_call(mcp_name, payload)
                result_obj = {"undo_id": undo_id, "undone": "revert_task", "result": mcp_text_json(res)}
                results.append(result_obj)
                if undo_sheet_append is not None:
                    try:
                        await undo_sheet_append(
                            {
                                "event": "executed",
                                "undo_id": undo_id,
                                "scope": "google_tasks",
                                "action": orig_action,
                                "tasklist_id": tasklist_id,
                                "task_id": task_id,
                                "status": "ok",
                                "result": result_obj,
                            }
                        )
                    except Exception:
                        pass
                continue

            if orig_action == "google_tasks_delete_task" and tasklist_id and isinstance(before, dict):
                meta = mcp_tool_map.get("google_tasks_create_task") if isinstance(mcp_tool_map, dict) else None
                mcp_name = str(meta.get("mcp_name") or "").strip() if isinstance(meta, dict) else ""
                if not mcp_name:
                    raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")
                payload = {
                    "tasklist_id": tasklist_id,
                    "title": str(before.get("title") or ""),
                    "notes": str(before.get("notes") or ""),
                    "due": before.get("due"),
                }
                payload = {k: v for k, v in payload.items() if v is not None and str(v) != ""}
                res = await mcp_tools_call(mcp_name, payload)
                result_obj = {"undo_id": undo_id, "undone": "recreate_deleted_task", "result": mcp_text_json(res)}
                results.append(result_obj)
                if undo_sheet_append is not None:
                    try:
                        await undo_sheet_append(
                            {
                                "event": "executed",
                                "undo_id": undo_id,
                                "scope": "google_tasks",
                                "action": orig_action,
                                "tasklist_id": tasklist_id,
                                "task_id": task_id,
                                "status": "ok",
                                "result": result_obj,
                            }
                        )
                    except Exception:
                        pass
                continue

            result_obj = {"undo_id": undo_id, "skipped": True, "reason": "insufficient_undo_data", "action": orig_action}
            results.append(result_obj)
            if undo_sheet_append is not None:
                try:
                    await undo_sheet_append(
                        {
                            "event": "executed",
                            "undo_id": undo_id,
                            "scope": "google_tasks",
                            "action": orig_action,
                            "tasklist_id": tasklist_id,
                            "task_id": task_id,
                            "status": "skipped",
                            "result": result_obj,
                        }
                    )
                except Exception:
                    pass

        return GoogleTasksUndoResponse(ok=True, undone=len(results), results=results)

    return router
