from __future__ import annotations

from typing import Any, Callable, Awaitable, Optional

from fastapi import APIRouter, HTTPException

from google_schemas import (
    GoogleTasksSequentialItem,
    GoogleTasksSequentialSummaryResponse,
    GoogleTasksCreateTaskRequest,
    GoogleTasksCompleteTaskRequest,
    GoogleTasksDeleteTaskRequest,
    GoogleTasksUpdateTaskRequest,
    GoogleTasksWriteResponse,
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

        try:
            list_tasklists_res = await mcp_tools_call(list_tasklists_tool, {"maxResults": max_results})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail={"google_tasks_list_tasklists_failed": str(e)})

        try:
            list_tasks_res = await mcp_tools_call(list_tasks_tool, {
                "maxResults": max_results,
                "showCompleted": show_completed,
                "showHidden": False,
                "pageToken": None,
            })
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail={"google_tasks_list_tasks_failed": str(e)})

        tasklist_id_resolved, _ = await resolve_tasklist(tasklist_id, tasklist_title)
        if not tasklist_id_resolved:
            raise HTTPException(status_code=400, detail="tasklist_not_found")

        # Build summary
        items: list[GoogleTasksSequentialItem] = []
        if isinstance(list_tasklists_res, dict) and isinstance(list_tasklists_res.get("items"), list):
            for item in list_tasklists_res["items"]:
                items.append(GoogleTasksSequentialItem(
                    id=item.get("id"),
                    title=item.get("title"),
                    updated=item.get("updated"),
                    self_link=item.get("selfLink"),
                    position=item.get("position"),
                    notes=item.get("notes") if item.get("notes") else "",
                    status=item.get("status"),
                    due=item.get("due"),
                    completed=item.get("completed"),
                ))

        if isinstance(list_tasks_res, dict) and isinstance(list_tasks_res.get("items"), list):
            for item in list_tasks_res["items"]:
                items.append(GoogleTasksSequentialItem(
                    id=item.get("id"),
                    title=item.get("title"),
                    updated=item.get("updated"),
                    self_link=item.get("selfLink"),
                    position=item.get("position"),
                    notes=item.get("notes") if item.get("notes") else "",
                    status=item.get("status"),
                    due=item.get("due"),
                    completed=item.get("completed"),
                ))

        return GoogleTasksSequentialSummaryResponse(
            ok=True,
            tasklist_id=tasklist_id_resolved,
            tasklist_title=_,
            items=items,
        )

    @router.post("/google-tasks/tasks/create", response_model=GoogleTasksWriteResponse)
    async def google_tasks_create_task(req: GoogleTasksCreateTaskRequest) -> GoogleTasksWriteResponse:
        tasklist_id = str(req.tasklist_id or "").strip() or None
        tasklist_title = str(req.tasklist_title or "").strip() or None
        title = str(req.title or "").strip()
        notes = str(req.notes or "").strip()
        due = str(req.due or "").strip() or None

        if not title:
            raise HTTPException(status_code=400, detail="missing_title")

        action = "google_tasks_create_task"
        preview_payload: dict[str, Any] = {
            "tasklist_id": tasklist_id,
            "tasklist_title": tasklist_title,
            "title": title,
            "notes": notes,
            "due": due,
        }
        preview_payload = {k: v for k, v in preview_payload.items() if v is not None}
        require_confirmation(bool(req.confirm), action, preview_payload)

        tasklist_id_resolved, _ = await resolve_tasklist(req.tasklist_id, req.tasklist_title)
        payload: dict[str, Any] = {"tasklist_id": tasklist_id_resolved, "title": title}
        if notes:
            payload["notes"] = notes
        if due:
            payload["due"] = due
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
        payload: dict[str, Any] = {"tasklist_id": tasklist_id_resolved, "task_id": task_id, "status": "completed"}
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
            raise HTTPException(status_code=500, detail="google_tasks_not_configured")

        res = await mcp_tools_call(mcp_name, payload)
        parsed = mcp_text_json(res)
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
            "title": (str(req.title or "").strip() or None),
            "notes": (str(req.notes or "").strip() or None),
            "due": (str(req.due or "").strip() or None),
            "status": (str(req.status or "").strip() or None),
        }
        preview_payload = {k: v for k, v in preview_payload.items() if v is not None}
        require_confirmation(bool(req.confirm), action, preview_payload)

        tasklist_id_resolved, _ = await resolve_tasklist(req.tasklist_id, req.tasklist_title)
        before = await fetch_task(str(tasklist_id_resolved or ""), task_id) if tasklist_id_resolved else None
        payload: dict[str, Any] = {"tasklist_id": tasklist_id_resolved, "task_id": task_id}
        for k in ["title", "notes", "due", "status"]:
            payload[k] = getattr(req, k, None) if getattr(req, k, None) is not None else None
        payload = {k: v for k, v in payload.items() if v is not None}

        meta = mcp_tool_map.get(action) if isinstance(mcp_tool_map, dict) else None
        if not isinstance(meta, dict):
            raise HTTPException(status_code=500, detail="google_tasks_tools_not_configured")
        mcp_name = str(meta.get("mcp_name") or "").strip()
        if not mcp_name:
            raise HTTPException(status_code=500, detail="google_tasks_not_configured")

        res = await mcp_tools_call(mcp_name, payload)
        parsed = mcp_text_json(res)
        return GoogleTasksWriteResponse(ok=True, result=parsed if isinstance(parsed, dict) else {"raw": parsed})

    return router
