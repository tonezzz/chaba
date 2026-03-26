from typing import Any, Optional, Literal

from pydantic import BaseModel, Field


class GoogleTasksSequentialItem(BaseModel):
    task_id: str
    title: str
    status: str
    notes: str = ""
    next_step_text: Optional[str] = None
    next_step_index: Optional[int] = None


class GoogleTasksSequentialSummaryResponse(BaseModel):
    ok: bool = True
    tasklist_id: str
    tasklist_title: str
    tasks: list[GoogleTasksSequentialItem]
    template: Optional[list[str]] = None
    debug: Optional[dict[str, Any]] = None


class GoogleTasksCreateTaskRequest(BaseModel):
    tasklist_id: Optional[str] = None
    tasklist_title: Optional[str] = None
    title: str
    notes: str = ""
    due: Optional[str] = None
    confirm: bool = False


class GoogleTasksUpdateTaskRequest(BaseModel):
    tasklist_id: Optional[str] = None
    tasklist_title: Optional[str] = None
    task_id: str
    title: Optional[str] = None
    notes: Optional[str] = None
    due: Optional[str] = None
    status: Optional[str] = None
    confirm: bool = False


class GoogleTasksCompleteTaskRequest(BaseModel):
    tasklist_id: Optional[str] = None
    tasklist_title: Optional[str] = None
    task_id: str
    confirm: bool = False


class GoogleTasksDeleteTaskRequest(BaseModel):
    tasklist_id: Optional[str] = None
    tasklist_title: Optional[str] = None
    task_id: str
    confirm: bool = False


class GoogleTasksWriteResponse(BaseModel):
    ok: bool = True
    result: dict[str, Any]


class GoogleTasksUndoItem(BaseModel):
    undo_id: str
    created_at: int
    action: str
    tasklist_id: Optional[str] = None
    task_id: Optional[str] = None


class GoogleTasksUndoListResponse(BaseModel):
    ok: bool = True
    items: list[GoogleTasksUndoItem]


class GoogleTasksUndoLastRequest(BaseModel):
    n: int = 1
    confirm: bool = False


class GoogleTasksUndoResponse(BaseModel):
    ok: bool = True
    undone: int
    results: list[dict[str, Any]]


class GoogleCalendarUndoItem(BaseModel):
    undo_id: str
    created_at: int
    action: str
    event_id: Optional[str] = None


class GoogleCalendarUndoListResponse(BaseModel):
    ok: bool = True
    items: list[GoogleCalendarUndoItem]


class GoogleCalendarUndoLastRequest(BaseModel):
    n: int = 1
    confirm: bool = False


class GoogleCalendarUndoResponse(BaseModel):
    ok: bool = True
    undone: int
    results: list[dict[str, Any]]
