"""
Sequential Tasks API Router
Handles checklist/sequential task operations.
"""
from typing import Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from checklist_v0 import next_actionable_step, parse_checklist_steps
from checklist_mutation_v0 import (
    find_checklist_step_indices_by_text,
    mark_all_checklist_steps_done,
    mark_checklist_step_done,
    mark_checklist_step_done_by_text,
)
from tasks_sequential_v0 import suggest_next_step_from_task, suggest_template_from_completed_tasks

router = APIRouter()


class SequentialApplyRequest(BaseModel):
    notes: str = Field(default="")
    step_index: int = Field(ge=0)


class SequentialApplyResponse(BaseModel):
    ok: bool
    changed: bool
    notes: str


class SequentialApplyByTextRequest(BaseModel):
    notes: str = Field(default="")
    step_text: str = Field(default="")


class SequentialApplyByTextResponse(BaseModel):
    ok: bool
    changed: bool
    notes: str
    matched_step_index: Optional[int] = None


class SequentialApplyAllRequest(BaseModel):
    notes: str = Field(default="")


class SequentialApplyAllResponse(BaseModel):
    ok: bool
    changed: bool
    changed_count: int
    notes: str


class SequentialApplyAndSuggestRequest(BaseModel):
    mode: Optional[str] = Field(default="suggest")
    notes: str = Field(default="")
    step_index: Optional[int] = Field(default=None, ge=0)
    step_text: str = Field(default="")
    step_index_hint: Optional[int] = Field(default=None, ge=0)
    completed_tasks: Optional[list[dict[str, Any]]] = None


class SequentialSuggestRequest(BaseModel):
    task: dict[str, Any] = Field(default_factory=dict)
    completed_tasks: Optional[list[dict[str, Any]]] = None


class SequentialSuggestResponse(BaseModel):
    ok: bool = True
    next_step_text: Optional[str] = None
    next_step_index: Optional[int] = None
    template: Optional[list[str]] = None


class SequentialApplyAndSuggestResponse(BaseModel):
    ok: bool
    mode: str
    notes: str
    changed: bool
    changed_count: Optional[int] = None
    matched_step_index: Optional[int] = None
    next_step_text: Optional[str] = None
    next_step_index: Optional[int] = None
    template: Optional[list[str]] = None


@router.post("/tasks/sequential/apply", response_model=SequentialApplyResponse)
def tasks_sequential_apply(req: SequentialApplyRequest) -> SequentialApplyResponse:
    updated, changed = mark_checklist_step_done(req.notes, req.step_index)
    return SequentialApplyResponse(ok=True, changed=changed, notes=updated)


@router.post("/tasks/sequential/apply_by_text", response_model=SequentialApplyByTextResponse)
def tasks_sequential_apply_by_text(req: SequentialApplyByTextRequest) -> SequentialApplyByTextResponse:
    updated, changed, matched_idx = mark_checklist_step_done_by_text(req.notes, req.step_text)
    return SequentialApplyByTextResponse(ok=True, changed=changed, notes=updated, matched_step_index=matched_idx)


@router.post("/tasks/sequential/apply_all", response_model=SequentialApplyAllResponse)
def tasks_sequential_apply_all(req: SequentialApplyAllRequest) -> SequentialApplyAllResponse:
    updated, changed, changed_count = mark_all_checklist_steps_done(req.notes)
    return SequentialApplyAllResponse(ok=True, changed=changed, changed_count=changed_count, notes=updated)


@router.post("/tasks/sequential/suggest", response_model=SequentialSuggestResponse)
def tasks_sequential_suggest(req: SequentialSuggestRequest) -> SequentialSuggestResponse:
    task = req.task if isinstance(req.task, dict) else {}
    suggestion = suggest_next_step_from_task(task)
    
    template: Optional[list[str]] = None
    if req.completed_tasks is not None:
        template = suggest_template_from_completed_tasks(req.completed_tasks)
    
    return SequentialSuggestResponse(
        ok=True,
        next_step_text=suggestion.next_step_text,
        next_step_index=suggestion.next_step_index,
        template=template,
    )


@router.post("/tasks/sequential/apply_and_suggest", response_model=SequentialApplyAndSuggestResponse)
def tasks_sequential_apply_and_suggest(req: SequentialApplyAndSuggestRequest) -> SequentialApplyAndSuggestResponse:
    mode = str(req.mode or "suggest")
    notes_in = str(req.notes or "")

    updated_notes = notes_in
    changed = False
    changed_count: Optional[int] = None
    matched_step_index: Optional[int] = None

    if mode == "suggest":
        pass
    elif mode == "index":
        if req.step_index is None:
            raise HTTPException(status_code=400, detail="missing_step_index")
        updated_notes, changed = mark_checklist_step_done(updated_notes, int(req.step_index))
    elif mode == "text":
        step_text = str(req.step_text or "").strip()
        if not step_text:
            raise HTTPException(status_code=400, detail="missing_step_text")
        matches = find_checklist_step_indices_by_text(updated_notes, step_text)
        if len(matches) >= 2:
            hint = req.step_index_hint
            if hint is not None and int(hint) in matches:
                matched_step_index = int(hint)
                updated_notes, changed = mark_checklist_step_done(updated_notes, matched_step_index)
            else:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "ambiguous_step_text": True,
                        "step_text": step_text,
                        "match_indices": matches,
                    },
                )
        else:
            updated_notes, changed, matched_step_index = mark_checklist_step_done_by_text(updated_notes, step_text)
    elif mode == "all":
        updated_notes, changed, cnt = mark_all_checklist_steps_done(updated_notes)
        changed_count = cnt
    else:
        raise HTTPException(status_code=400, detail="invalid_mode")

    suggestion = suggest_next_step_from_task({"notes": updated_notes})
    template: Optional[list[str]] = None
    if req.completed_tasks is not None:
        template = suggest_template_from_completed_tasks(req.completed_tasks)

    return SequentialApplyAndSuggestResponse(
        ok=True,
        mode=mode,
        notes=updated_notes,
        changed=changed,
        changed_count=changed_count,
        matched_step_index=matched_step_index,
        next_step_text=suggestion.next_step_text,
        next_step_index=suggestion.next_step_index,
        template=template,
    )
