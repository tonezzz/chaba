from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

APP_NAME = "mcp-meeting"
APP_VERSION = "0.1.0"

logging.basicConfig(level=os.getenv("MEETING_LOG_LEVEL", "INFO"))
LOGGER = logging.getLogger(APP_NAME)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TranscriptEntry:
    text: str
    speaker: Optional[str] = None
    source: str = "manual"
    created_at: datetime = field(default_factory=utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload


@dataclass
class MeetingSession:
    session_id: str
    title: Optional[str] = None
    participants: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    archived: bool = False
    language_hint: Optional[str] = None
    summary: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    entries: List[TranscriptEntry] = field(default_factory=list)

    def as_dict(self, *, include_entries: bool = False, entry_limit: Optional[int] = None) -> Dict[str, Any]:
        data = {
            "session_id": self.session_id,
            "title": self.title,
            "participants": self.participants,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "archived": self.archived,
            "language_hint": self.language_hint,
            "summary": self.summary,
            "tags": self.tags,
            "entry_count": len(self.entries),
        }
        if include_entries:
            entries = self.entries[-entry_limit:] if entry_limit else self.entries
            data["entries"] = [entry.as_dict() for entry in entries]
        return data


class MeetingManager:
    def __init__(self, *, max_segments: int = 1000, storage_path: Optional[str] = None) -> None:
        self._sessions: Dict[str, MeetingSession] = {}
        self._lock = asyncio.Lock()
        self._max_segments = max_segments
        self._storage_path = self._prepare_storage_path(storage_path)
        if self._storage_path:
            self._load_from_disk()

    def _prepare_storage_path(self, storage_path: Optional[str]) -> Optional[Path]:
        if not storage_path:
            return None
        try:
            path = Path(storage_path).expanduser()
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("invalid storage path %s: %s", storage_path, exc)
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def start_session(
        self,
        session_id: str,
        *,
        title: Optional[str],
        participants: Optional[List[str]],
        language_hint: Optional[str],
        tags: Optional[List[str]] = None,
    ) -> MeetingSession:
        if not session_id:
            raise ValueError("session_id is required")
        async with self._lock:
            session = self._sessions.get(session_id)
            now = utcnow()
            if session:
                if title:
                    session.title = title
                if participants:
                    session.participants = participants
                if language_hint:
                    session.language_hint = language_hint
                if tags is not None:
                    session.tags = tags
                session.archived = False
                session.updated_at = now
                self._save_to_disk_locked()
                return session

            session = MeetingSession(
                session_id=session_id,
                title=title,
                participants=participants or [],
                language_hint=language_hint,
                tags=tags or [],
            )
            self._sessions[session_id] = session
            self._save_to_disk_locked()
            return session

    async def archive_session(self, session_id: str, reason: Optional[str] = None) -> MeetingSession:
        async with self._lock:
            session = self._require_session_unlocked(session_id)
            session.archived = True
            if reason:
                session.summary = (session.summary or "").strip() + ("\n" if session.summary else "") + f"Closed: {reason}"
            session.updated_at = utcnow()
            self._save_to_disk_locked()
            return session

    async def append_entry(
        self,
        session_id: str,
        *,
        text: str,
        speaker: Optional[str],
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TranscriptEntry:
        if not text:
            raise ValueError("text is required")
        async with self._lock:
            session = self._require_session_unlocked(session_id)
            if session.archived:
                raise ValueError("session is archived")
            entry = TranscriptEntry(text=text.strip(), speaker=speaker, source=source, metadata=metadata or {})
            session.entries.append(entry)
            if len(session.entries) > self._max_segments:
                overflow = len(session.entries) - self._max_segments
                session.entries = session.entries[overflow:]
            session.updated_at = utcnow()
            self._save_to_disk_locked()
            return entry

    async def list_sessions(self, *, include_archived: bool) -> List[Dict[str, Any]]:
        async with self._lock:
            payload: List[Dict[str, Any]] = []
            for session in self._sessions.values():
                if not include_archived and session.archived:
                    continue
                payload.append(session.as_dict(include_entries=False))
            payload.sort(key=lambda item: item["updated_at"], reverse=True)
            return payload

    async def meeting_notes(
        self,
        session_id: str,
        *,
        entry_limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        async with self._lock:
            session = self._require_session_unlocked(session_id)
            return session.as_dict(include_entries=True, entry_limit=entry_limit)

    async def summarize_session(self, session_id: str, *, max_entries: int) -> str:
        async with self._lock:
            session = self._require_session_unlocked(session_id)
            if not session.entries:
                summary = "No transcript has been captured yet."
            else:
                relevant = session.entries[-max_entries:]
                lines = []
                for entry in relevant:
                    speaker = entry.speaker or "speaker"
                    snippet = entry.text.strip()
                    if len(snippet) > 280:
                        snippet = snippet[:277] + "..."
                    lines.append(f"- {speaker}: {snippet}")
                summary = "\n".join(lines)
            session.summary = summary
            session.updated_at = utcnow()
            self._save_to_disk_locked()
            return summary

    async def set_summary(self, session_id: str, summary: str) -> str:
        async with self._lock:
            session = self._require_session_unlocked(session_id)
            session.summary = (summary or "").strip() or None
            session.updated_at = utcnow()
            self._save_to_disk_locked()
            return session.summary or ""

    async def _get_session(self, session_id: str) -> MeetingSession:
        async with self._lock:
            return self._require_session_unlocked(session_id)

    def _require_session_unlocked(self, session_id: str) -> MeetingSession:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        return session

    def _load_from_disk(self) -> None:
        if not self._storage_path:
            return
        if not self._storage_path.exists():
            LOGGER.info("meeting storage file not found, a new one will be created at %s", self._storage_path)
            return
        try:
            raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("failed to load meeting storage: %s", exc)
            return

        sessions: Dict[str, MeetingSession] = {}
        for session_id, payload in raw.items():
            try:
                session = MeetingSession(
                    session_id=session_id,
                    title=payload.get("title"),
                    participants=list(payload.get("participants") or []),
                    created_at=self._parse_datetime(payload.get("created_at")),
                    updated_at=self._parse_datetime(payload.get("updated_at")),
                    archived=bool(payload.get("archived")),
                    language_hint=payload.get("language_hint"),
                    summary=payload.get("summary"),
                    tags=list(payload.get("tags") or []),
                )
                entries_payload = payload.get("entries") or []
                for entry_payload in entries_payload:
                    entry = TranscriptEntry(
                        text=entry_payload.get("text", ""),
                        speaker=entry_payload.get("speaker"),
                        source=entry_payload.get("source", "manual"),
                        metadata=entry_payload.get("metadata") or {},
                        created_at=self._parse_datetime(entry_payload.get("created_at")),
                    )
                    session.entries.append(entry)
                sessions[session_id] = session
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("failed to hydrate meeting session %s: %s", session_id, exc)
        self._sessions = sessions
        LOGGER.info("loaded %d meeting sessions from %s", len(self._sessions), self._storage_path)

    def _save_to_disk_locked(self) -> None:
        if not self._storage_path:
            return
        try:
            snapshot = {
                session_id: session.as_dict(include_entries=True)
                for session_id, session in self._sessions.items()
            }
            temp_path = self._storage_path.with_name(self._storage_path.name + ".tmp")
            temp_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            temp_path.replace(self._storage_path)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("failed to save meeting storage: %s", exc)

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> datetime:
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                LOGGER.warning("invalid datetime string in storage: %s", value)
        return utcnow()


class InvokeRequest(BaseModel):
    tool: str = Field(..., description="Tool name exposed via MCP")
    arguments: Dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    session_count: int
    stt_status: str
    stt_detail: Optional[Any] = None
    stt_url: Optional[str] = None
    timestamp: datetime = Field(default_factory=utcnow)


class MeetingService:
    def __init__(self) -> None:
        max_segments = int(os.getenv("MEETING_MAX_SEGMENTS", "1200"))
        storage_path = (os.getenv("MEETING_STORAGE_PATH") or "").strip() or None
        self.manager = MeetingManager(max_segments=max_segments, storage_path=storage_path)
        self._stt_url = (os.getenv("MEETING_STT_URL") or os.getenv("STT_GPU_URL") or os.getenv("STT_URL") or "").strip()
        self._stt_health_path = os.getenv("MEETING_STT_HEALTH_PATH", "/health")
        self._stt_timeout = float(os.getenv("MEETING_STT_TIMEOUT_SECONDS", "45"))
        self.default_language = os.getenv("MEETING_DEFAULT_LANGUAGE")
        self.default_whisper_model = os.getenv("MEETING_DEFAULT_WHISPER_MODEL")
        self.summary_window = int(os.getenv("MEETING_SUMMARY_MAX_ENTRIES", "20"))

        self._llm_base_url = (os.getenv("MEETING_LLM_BASE_URL") or "").strip().rstrip("/")
        self._llm_api_key = (os.getenv("MEETING_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        self._llm_model = (os.getenv("MEETING_LLM_MODEL") or "glama-default").strip() or "glama-default"
        self._llm_temperature = float(os.getenv("MEETING_LLM_TEMPERATURE", "0.2"))
        self._llm_timeout = float(os.getenv("MEETING_LLM_TIMEOUT_SECONDS", "60"))
        self._summary_use_llm_default = (os.getenv("MEETING_SUMMARY_USE_LLM") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    @property
    def stt_url(self) -> str:
        return self._stt_url

    def llm_ready(self) -> bool:
        return bool(self._llm_base_url)

    async def summarize_with_llm(
        self,
        session_id: str,
        *,
        max_entries: int,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        session = await self.manager._get_session(session_id)
        entries = session.entries[-max_entries:] if max_entries else session.entries
        if not entries:
            return "No transcript has been captured yet."

        lines: List[str] = []
        for entry in entries:
            speaker = (entry.speaker or "speaker").strip() or "speaker"
            text = (entry.text or "").strip()
            if not text:
                continue
            if len(text) > 1200:
                text = text[:1197] + "..."
            lines.append(f"{speaker}: {text}")

        transcript = "\n".join(lines).strip() or "(empty)"

        system_prompt = (
            "You are a meeting assistant. Summarize the meeting transcript into a concise, actionable note. "
            "Prefer bullet points. Include: decisions, action items (with owners if present), open questions, and key context. "
            "Do not invent facts."
        )
        user_prompt = f"Meeting transcript (most recent {len(entries)} entries):\n\n{transcript}\n\nReturn the summary." 

        payload: Dict[str, Any] = {
            "model": (model or self._llm_model).strip() or self._llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._llm_temperature if temperature is None else float(temperature),
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)

        url = self._llm_base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self._llm_api_key:
            headers["Authorization"] = f"Bearer {self._llm_api_key}"

        async with httpx.AsyncClient(timeout=self._llm_timeout) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"llm_error:{response.status_code}")

        try:
            data = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="llm_invalid_json") from exc

        choices = data.get("choices") or []
        content = ""
        if choices and isinstance(choices, list):
            msg = (choices[0] or {}).get("message") or {}
            content = (msg.get("content") or "").strip()

        if not content:
            raise HTTPException(status_code=502, detail="llm_empty")

        return content

    async def transcribe_and_store(
        self,
        session_id: str,
        *,
        audio_base64: str,
        speaker: Optional[str],
        filename: Optional[str],
        whisper_model: Optional[str],
        language: Optional[str],
    ) -> Dict[str, Any]:
        audio_bytes, inferred_filename = self._decode_audio(audio_base64, filename)
        transcript = await self._invoke_stt(audio_bytes, inferred_filename, whisper_model, language)
        text = (transcript.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=502, detail="transcription_empty")
        metadata = {
            "language": transcript.get("language"),
            "model": transcript.get("model"),
            "chars": len(text),
        }
        entry = await self.manager.append_entry(
            session_id,
            text=text,
            speaker=speaker,
            source="audio",
            metadata=metadata,
        )
        return {
            "entry": entry,
            "transcript": transcript,
        }

    async def stt_health(self) -> Tuple[str, Optional[Any]]:
        if not self._stt_url:
            return "unconfigured", None
        target = self._stt_url.rstrip("/") + self._stt_health_path
        try:
            async with httpx.AsyncClient(timeout=self._stt_timeout) as client:
                response = await client.get(target)
        except httpx.RequestError as exc:
            return "error", str(exc)
        if response.status_code >= 400:
            return "error", f"HTTP {response.status_code}"
        detail: Any
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        return "ok", detail

    async def _invoke_stt(
        self,
        audio_bytes: bytes,
        filename: str,
        whisper_model: Optional[str],
        language: Optional[str],
    ) -> Dict[str, Any]:
        stt_url = self._stt_url
        if not stt_url:
            raise HTTPException(status_code=503, detail="meeting_stt_unconfigured")
        endpoint = stt_url.rstrip("/") + "/transcribe"
        files = {
            "file": (filename, audio_bytes, mimetypes.guess_type(filename)[0] or "application/octet-stream"),
        }
        form: Dict[str, Any] = {}
        if whisper_model or self.default_whisper_model:
            form["whisper_model"] = whisper_model or self.default_whisper_model
        if language or self.default_language:
            form["language"] = language or self.default_language
        try:
            async with httpx.AsyncClient(timeout=self._stt_timeout) as client:
                response = await client.post(endpoint, files=files, data=form)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"stt_unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"stt_error:{response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="stt_invalid_json") from exc
        return payload

    @staticmethod
    def _decode_audio(encoded: str, filename: Optional[str]) -> Tuple[bytes, str]:
        if not encoded or not isinstance(encoded, str):
            raise HTTPException(status_code=400, detail="audio_base64 is required")
        payload = encoded.strip()
        if payload.startswith("data:"):
            _, _, payload = payload.partition(",")
        try:
            raw = base64.b64decode(payload, validate=False)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="audio_base64_invalid") from exc
        inferred = filename or "chunk.webm"
        return raw, inferred


meeting_service = MeetingService()
app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def tool_start_meeting(arguments: Dict[str, Any]) -> Dict[str, Any]:
    session_id = _require_str(arguments, "session_id")
    participants = _coerce_list(arguments.get("participants"), "participants")
    tags = _coerce_list(arguments.get("tags"), "tags")
    session = await meeting_service.manager.start_session(
        session_id,
        title=arguments.get("title"),
        participants=participants,
        language_hint=arguments.get("language"),
        tags=tags,
    )
    return session.as_dict(include_entries=False)


async def tool_end_meeting(arguments: Dict[str, Any]) -> Dict[str, Any]:
    session_id = _require_str(arguments, "session_id")
    session = await meeting_service.manager.archive_session(session_id, reason=arguments.get("reason"))
    return session.as_dict(include_entries=False)


async def tool_append_transcript(arguments: Dict[str, Any]) -> Dict[str, Any]:
    session_id = _require_str(arguments, "session_id")
    text = _require_str(arguments, "text")
    speaker = arguments.get("speaker")
    entry = await meeting_service.manager.append_entry(
        session_id,
        text=text,
        speaker=speaker,
        source="manual",
        metadata={"source": arguments.get("source_label", "manual")},
    )
    return entry.as_dict()


async def tool_ingest_audio_chunk(arguments: Dict[str, Any]) -> Dict[str, Any]:
    session_id = _require_str(arguments, "session_id")
    audio_payload = _require_str(arguments, "audio_base64")
    result = await meeting_service.transcribe_and_store(
        session_id,
        audio_base64=audio_payload,
        speaker=arguments.get("speaker"),
        filename=arguments.get("filename"),
        whisper_model=arguments.get("whisper_model"),
        language=arguments.get("language"),
    )
    return {
        "transcript": result["transcript"],
        "entry": result["entry"].as_dict(),
    }


async def tool_get_meeting_notes(arguments: Dict[str, Any]) -> Dict[str, Any]:
    session_id = _require_str(arguments, "session_id")
    limit = arguments.get("entry_limit")
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="entry_limit must be numeric")
    return await meeting_service.manager.meeting_notes(session_id, entry_limit=limit)


async def tool_summarize_meeting(arguments: Dict[str, Any]) -> Dict[str, Any]:
    session_id = _require_str(arguments, "session_id")
    max_entries = arguments.get("max_entries") or meeting_service.summary_window
    try:
        max_entries = int(max_entries)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="max_entries must be numeric")

    use_llm_value = arguments.get("use_llm")
    use_llm = meeting_service._summary_use_llm_default
    if use_llm_value is not None:
        use_llm = bool(use_llm_value)

    model = arguments.get("llm_model")
    temperature = arguments.get("llm_temperature")
    max_tokens = arguments.get("llm_max_tokens")

    summary: str
    summary_source = "heuristic"
    if use_llm and meeting_service.llm_ready():
        try:
            temp_value: Optional[float] = None
            if temperature is not None:
                temp_value = float(temperature)
            tokens_value: Optional[int] = None
            if max_tokens is not None:
                tokens_value = int(max_tokens)
            summary = await meeting_service.summarize_with_llm(
                session_id,
                max_entries=max_entries,
                model=str(model) if model is not None else None,
                temperature=temp_value,
                max_tokens=tokens_value,
            )
            await meeting_service.manager.set_summary(session_id, summary)
            summary_source = "llm"
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("llm summary failed, falling back to heuristic: %s", exc)
            summary = await meeting_service.manager.summarize_session(session_id, max_entries=max_entries)
    else:
        summary = await meeting_service.manager.summarize_session(session_id, max_entries=max_entries)

    return {
        "session_id": session_id,
        "summary": summary,
        "entries_considered": max_entries,
        "source": summary_source,
        "llm_ready": meeting_service.llm_ready(),
    }


async def tool_list_sessions(arguments: Dict[str, Any]) -> Dict[str, Any]:
    include_archived = bool(arguments.get("include_archived"))
    sessions = await meeting_service.manager.list_sessions(include_archived=include_archived)
    return {"sessions": sessions}


def _require_str(payload: Dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"{key} is required")
    return value.strip()


def _coerce_list(value: Any, field_name: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    raise HTTPException(status_code=400, detail=f"{field_name} must be a list")


tool_registry: Dict[str, Any] = {
    "start_meeting": tool_start_meeting,
    "end_meeting": tool_end_meeting,
    "append_transcript": tool_append_transcript,
    "ingest_audio_chunk": tool_ingest_audio_chunk,
    "get_meeting_notes": tool_get_meeting_notes,
    "summarize_meeting": tool_summarize_meeting,
    "list_sessions": tool_list_sessions,
}


tool_schemas: Dict[str, Dict[str, Any]] = {
    "start_meeting": {
        "name": "start_meeting",
        "description": "Create or resume a meeting session before ingesting audio/text.",
        "input_schema": {
            "type": "object",
            "required": ["session_id"],
            "properties": {
                "session_id": {"type": "string", "description": "Stable meeting identifier (calendar event id, etc.)"},
                "title": {"type": "string"},
                "participants": {"type": "array", "items": {"type": "string"}},
                "language": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    "end_meeting": {
        "name": "end_meeting",
        "description": "Archive a meeting session and optionally explain why it ended.",
        "input_schema": {
            "type": "object",
            "required": ["session_id"],
            "properties": {
                "session_id": {"type": "string"},
                "reason": {"type": "string"},
            },
        },
    },
    "append_transcript": {
        "name": "append_transcript",
        "description": "Append a manual text snippet to the meeting transcript.",
        "input_schema": {
            "type": "object",
            "required": ["session_id", "text"],
            "properties": {
                "session_id": {"type": "string"},
                "text": {"type": "string"},
                "speaker": {"type": "string"},
                "source_label": {"type": "string"},
            },
        },
    },
    "ingest_audio_chunk": {
        "name": "ingest_audio_chunk",
        "description": "Transcribe an audio chunk via Whisper and append it to the meeting notes.",
        "input_schema": {
            "type": "object",
            "required": ["session_id", "audio_base64"],
            "properties": {
                "session_id": {"type": "string"},
                "audio_base64": {"type": "string", "description": "Base64 or data URL encoded audio"},
                "speaker": {"type": "string"},
                "filename": {"type": "string"},
                "whisper_model": {"type": "string"},
                "language": {"type": "string"},
            },
        },
    },
    "get_meeting_notes": {
        "name": "get_meeting_notes",
        "description": "Fetch the structured transcript for a meeting.",
        "input_schema": {
            "type": "object",
            "required": ["session_id"],
            "properties": {
                "session_id": {"type": "string"},
                "entry_limit": {"type": "integer", "minimum": 1},
            },
        },
    },
    "summarize_meeting": {
        "name": "summarize_meeting",
        "description": "Generate a meeting summary (heuristic by default; can optionally use an OpenAI-compatible LLM gateway).",
        "input_schema": {
            "type": "object",
            "required": ["session_id"],
            "properties": {
                "session_id": {"type": "string"},
                "max_entries": {"type": "integer", "minimum": 1},
                "use_llm": {"type": "boolean", "description": "If true, attempt LLM summary then fall back to heuristic."},
                "llm_model": {"type": "string", "description": "Override MEETING_LLM_MODEL for this request."},
                "llm_temperature": {"type": "number"},
                "llm_max_tokens": {"type": "integer", "minimum": 1},
            },
        },
    },
    "list_sessions": {
        "name": "list_sessions",
        "description": "List active (and optional archived) meeting sessions maintained by the service.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_archived": {"type": "boolean"},
            },
        },
    },
}


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    stt_status, stt_detail = await meeting_service.stt_health()
    session_count = len(await meeting_service.manager.list_sessions(include_archived=True))
    status = "ok" if stt_status in {"ok", "unconfigured"} else "error"
    return HealthResponse(
        status=status,
        session_count=session_count,
        stt_status=stt_status,
        stt_detail=stt_detail,
        stt_url=meeting_service.stt_url or None,
    )


@app.get("/sessions")
async def sessions(include_archived: bool = False) -> Dict[str, Any]:
    entries = await meeting_service.manager.list_sessions(include_archived=include_archived)
    return {"sessions": entries}


@app.get("/sessions/{session_id}")
async def session_detail(session_id: str, entry_limit: Optional[int] = None) -> Dict[str, Any]:
    return await meeting_service.manager.meeting_notes(session_id, entry_limit=entry_limit)


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
async def ui() -> HTMLResponse:
    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>mcp-meeting</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; padding: 16px; }
    .wrap { max-width: 1100px; margin: 0 auto; }
    h1 { margin: 0 0 8px; font-size: 20px; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    @media (max-width: 900px) { .row { grid-template-columns: 1fr; } }
    .card { border: 1px solid rgba(127,127,127,0.35); border-radius: 10px; padding: 12px; }
    label { display: block; font-size: 12px; opacity: .8; margin-top: 10px; }
    input, textarea, select { width: 100%; box-sizing: border-box; padding: 8px; border-radius: 8px; border: 1px solid rgba(127,127,127,0.35); background: transparent; }
    textarea { min-height: 92px; resize: vertical; }
    .btns { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    button { padding: 8px 10px; border-radius: 8px; border: 1px solid rgba(127,127,127,0.35); background: rgba(127,127,127,0.12); cursor: pointer; }
    button.primary { background: rgba(0,120,255,0.22); border-color: rgba(0,120,255,0.45); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
    pre { white-space: pre-wrap; word-break: break-word; margin: 0; }
    .small { font-size: 12px; opacity: .8; }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    @media (max-width: 600px) { .grid2 { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<div class="wrap">
  <h1>mcp-meeting console</h1>
  <div class="small">Calls <span class="mono">/invoke</span> and <span class="mono">/sessions</span> on this server.</div>

  <div class="row" style="margin-top: 12px;">
    <div class="card">
      <div class="grid2">
        <div>
          <label>Session ID</label>
          <input id="sessionId" placeholder="e.g. standup-2026-01-11"/>
        </div>
        <div>
          <label>Speaker (optional)</label>
          <input id="speaker" placeholder="e.g. chaba"/>
        </div>
      </div>

      <label>Title (start_meeting)</label>
      <input id="title" placeholder="Optional meeting title"/>

      <div class="grid2">
        <div>
          <label>Participants (comma-separated)</label>
          <input id="participants" placeholder="alice,bob"/>
        </div>
        <div>
          <label>Tags (comma-separated)</label>
          <input id="tags" placeholder="work,planning"/>
        </div>
      </div>

      <label>Append text (append_transcript)</label>
      <textarea id="text" placeholder="Paste a note or transcript snippet..."></textarea>

      <div class="grid2">
        <div>
          <label>Summary max_entries</label>
          <input id="maxEntries" type="number" min="1" value="20"/>
        </div>
        <div>
          <label>Summary mode</label>
          <select id="summaryMode">
            <option value="heuristic" selected>heuristic</option>
            <option value="llm">llm (if configured)</option>
          </select>
        </div>
      </div>

      <div class="btns">
        <button class="primary" onclick="startMeeting()">start_meeting</button>
        <button onclick="endMeeting()">end_meeting</button>
        <button onclick="appendText()">append_transcript</button>
        <button onclick="summarize()">summarize_meeting</button>
        <button onclick="refreshSessions()">list_sessions</button>
      </div>
    </div>

    <div class="card">
      <div class="small" style="margin-bottom: 8px;">Response</div>
      <pre id="out" class="mono">(no output yet)</pre>
    </div>
  </div>

  <div class="card" style="margin-top: 12px;">
    <div class="small" style="margin-bottom: 8px;">Sessions</div>
    <pre id="sessions" class="mono">(click list_sessions)</pre>
  </div>
</div>

<script>
  const $ = (id) => document.getElementById(id);

  function csvToList(v) {
    const s = (v || '').trim();
    if (!s) return [];
    return s.split(',').map(x => x.trim()).filter(Boolean);
  }

  async function invoke(tool, argumentsObj) {
    const res = await fetch('/invoke', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool, arguments: argumentsObj || {} })
    });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { data = text; }
    $('out').textContent = JSON.stringify({ ok: res.ok, status: res.status, data }, null, 2);
    if (!res.ok) throw new Error(typeof data === 'string' ? data : JSON.stringify(data));
    return data;
  }

  async function startMeeting() {
    const session_id = $('sessionId').value.trim();
    await invoke('start_meeting', {
      session_id,
      title: $('title').value || undefined,
      participants: csvToList($('participants').value),
      tags: csvToList($('tags').value),
    });
    await refreshSessions();
  }

  async function endMeeting() {
    const session_id = $('sessionId').value.trim();
    await invoke('end_meeting', { session_id });
    await refreshSessions();
  }

  async function appendText() {
    const session_id = $('sessionId').value.trim();
    const text = $('text').value;
    await invoke('append_transcript', {
      session_id,
      text,
      speaker: $('speaker').value || undefined,
    });
  }

  async function summarize() {
    const session_id = $('sessionId').value.trim();
    const max_entries = parseInt($('maxEntries').value || '20', 10);
    const use_llm = $('summaryMode').value === 'llm';
    await invoke('summarize_meeting', { session_id, max_entries, use_llm });
  }

  async function refreshSessions() {
    const include_archived = true;
    const res = await fetch('/sessions?include_archived=' + String(include_archived));
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { data = text; }
    $('sessions').textContent = JSON.stringify(data, null, 2);
  }
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.post("/invoke")
async def invoke(request: InvokeRequest) -> Any:
    handler = tool_registry.get(request.tool)
    if not handler:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{request.tool}'")
    result = await handler(request.arguments)
    return result


@app.get("/.well-known/mcp.json")
async def manifest() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "Meeting assistant MCP service that ingests audio chunks, stores transcripts, and emits lightweight summaries.",
        "capabilities": {
            "tools": list(tool_schemas.values()),
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=os.getenv("MCP_HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8008")))
