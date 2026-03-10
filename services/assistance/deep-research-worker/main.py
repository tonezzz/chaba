import os
import time
import json
import sqlite3
import logging
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from google import genai


load_dotenv()

logger = logging.getLogger("deep-research-worker")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="deep-research-worker", version="0.1.0")

PORT = int(os.getenv("PORT") or "8030")

SESSION_DB_PATH = os.getenv("DEEP_RESEARCH_DB", "/app/deep_research.sqlite")

GEMINI_API_KEY = str(os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY") or "").strip()

DEEP_RESEARCH_AGENT = str(os.getenv("DEEP_RESEARCH_AGENT") or "deep-research-pro-preview-12-2025").strip()

# Polling defaults
DEFAULT_POLL_SECONDS = max(2, int(os.getenv("DEEP_RESEARCH_POLL_SECONDS") or "10"))


def _require_api_key() -> str:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="missing_gemini_api_key")
    return GEMINI_API_KEY


def _init_db() -> None:
    os.makedirs(os.path.dirname(SESSION_DB_PATH) or ".", exist_ok=True)
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS research_jobs (
              job_id TEXT PRIMARY KEY,
              interaction_id TEXT NOT NULL,
              agent TEXT NOT NULL,
              query TEXT NOT NULL,
              status TEXT NOT NULL,
              result_text TEXT,
              citations_json TEXT,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_research_jobs_updated ON research_jobs(updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_research_jobs_status ON research_jobs(status)")
        conn.commit()


def _now_ts() -> int:
    return int(time.time())


def _job_id() -> str:
    return f"dr_{_now_ts()}_{os.urandom(6).hex()}"


def _db_get_job(job_id: str) -> Optional[dict[str, Any]]:
    _init_db()
    jid = str(job_id or "").strip()
    if not jid:
        return None
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            """
            SELECT job_id, interaction_id, agent, query, status, result_text, citations_json, created_at, updated_at
            FROM research_jobs WHERE job_id = ? LIMIT 1
            """,
            (jid,),
        )
        row = cur.fetchone()
    if not row:
        return None
    (
        job_id_v,
        interaction_id,
        agent,
        query,
        status,
        result_text,
        citations_json,
        created_at,
        updated_at,
    ) = row
    citations: Any = None
    if citations_json:
        try:
            citations = json.loads(citations_json)
        except Exception:
            citations = citations_json
    return {
        "job_id": job_id_v,
        "interaction_id": interaction_id,
        "agent": agent,
        "query": query,
        "status": status,
        "result_text": result_text,
        "citations": citations,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _db_upsert_job(
    *,
    job_id: str,
    interaction_id: str,
    agent: str,
    query: str,
    status: str,
    result_text: Optional[str] = None,
    citations: Any = None,
) -> None:
    _init_db()
    now = _now_ts()
    citations_json = None
    if citations is not None:
        try:
            citations_json = json.dumps(citations, ensure_ascii=False)
        except Exception:
            citations_json = json.dumps(str(citations), ensure_ascii=False)

    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO research_jobs(
              job_id, interaction_id, agent, query, status, result_text, citations_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
              interaction_id=excluded.interaction_id,
              agent=excluded.agent,
              query=excluded.query,
              status=excluded.status,
              result_text=excluded.result_text,
              citations_json=excluded.citations_json,
              updated_at=excluded.updated_at
            """,
            (
                job_id,
                interaction_id,
                agent,
                query,
                status,
                result_text,
                citations_json,
                now,
                now,
            ),
        )
        conn.commit()


def _extract_text_and_citations(interaction: Any) -> tuple[Optional[str], Any]:
    # google-genai returns rich objects; we only use a couple fields.
    status = getattr(interaction, "status", None)
    _ = status

    outputs = getattr(interaction, "outputs", None)
    text_out: Optional[str] = None
    citations_out: Any = None

    if isinstance(outputs, list) and outputs:
        last = outputs[-1]
        # Most examples show .text on the last output.
        t = getattr(last, "text", None)
        if isinstance(t, str) and t.strip():
            text_out = t.strip()
        # Citations: docs mention `citations` in response; depending on SDK version,
        # it may appear on output or interaction.
        c1 = getattr(last, "citations", None)
        if c1 is not None:
            citations_out = c1

    if citations_out is None:
        c2 = getattr(interaction, "citations", None)
        if c2 is not None:
            citations_out = c2

    return text_out, citations_out


class StartRequest(BaseModel):
    query: str = Field(min_length=3, max_length=20000)
    agent: Optional[str] = None


class FollowupRequest(BaseModel):
    previous_interaction_id: str = Field(min_length=6, max_length=200)
    question: str = Field(min_length=1, max_length=20000)
    agent: Optional[str] = None


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "deep-research-worker"}


@app.post("/deep-research/start")
def deep_research_start(req: StartRequest = Body(...)) -> dict[str, Any]:
    _require_api_key()
    query = str(req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="missing_query")

    agent = str(req.agent or "").strip() or DEEP_RESEARCH_AGENT

    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        interaction = client.interactions.create(
            input=query,
            agent=agent,
            background=True,
            store=True,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail={"deep_research_start_failed": str(e)})

    interaction_id = str(getattr(interaction, "id", "") or "").strip()
    if not interaction_id:
        raise HTTPException(status_code=502, detail="missing_interaction_id")

    job_id = _job_id()
    status = str(getattr(interaction, "status", "in_progress") or "in_progress")
    _db_upsert_job(job_id=job_id, interaction_id=interaction_id, agent=agent, query=query, status=status)

    return {"ok": True, "job_id": job_id, "interaction_id": interaction_id, "status": status, "agent": agent}


@app.get("/deep-research/jobs/{job_id}")
def deep_research_job(job_id: str) -> dict[str, Any]:
    job = _db_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    return {"ok": True, "job": job}


@app.post("/deep-research/poll/{job_id}")
def deep_research_poll(job_id: str) -> dict[str, Any]:
    _require_api_key()
    job = _db_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")

    interaction_id = str(job.get("interaction_id") or "").strip()
    agent = str(job.get("agent") or "").strip() or DEEP_RESEARCH_AGENT

    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        interaction = client.interactions.get(interaction_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail={"deep_research_poll_failed": str(e)})

    status = str(getattr(interaction, "status", "") or "").strip() or "unknown"
    text_out, citations_out = _extract_text_and_citations(interaction)

    if status in ("completed", "failed", "cancelled"):
        _db_upsert_job(
            job_id=str(job["job_id"]),
            interaction_id=interaction_id,
            agent=agent,
            query=str(job.get("query") or ""),
            status=status,
            result_text=text_out,
            citations=citations_out,
        )
    else:
        _db_upsert_job(
            job_id=str(job["job_id"]),
            interaction_id=interaction_id,
            agent=agent,
            query=str(job.get("query") or ""),
            status=status,
        )

    out_job = _db_get_job(job_id)
    return {"ok": True, "job": out_job, "status": status}


@app.post("/deep-research/wait/{job_id}")
def deep_research_wait(job_id: str, timeout_seconds: int = 60) -> dict[str, Any]:
    # Blocking convenience endpoint (do not use from Jarvis websocket handler directly).
    _require_api_key()
    job = _db_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")

    deadline = time.time() + max(1, min(int(timeout_seconds or 60), 600))
    last: Optional[dict[str, Any]] = None
    while time.time() < deadline:
        res = deep_research_poll(job_id)
        last = res.get("job") if isinstance(res, dict) else None
        st = str(res.get("status") or "")
        if st in ("completed", "failed", "cancelled"):
            break
        time.sleep(DEFAULT_POLL_SECONDS)
    return {"ok": True, "job": last}


@app.post("/deep-research/followup")
def deep_research_followup(req: FollowupRequest = Body(...)) -> dict[str, Any]:
    _require_api_key()
    prev_id = str(req.previous_interaction_id or "").strip()
    question = str(req.question or "").strip()
    agent = str(req.agent or "").strip() or DEEP_RESEARCH_AGENT

    if not prev_id:
        raise HTTPException(status_code=400, detail="missing_previous_interaction_id")
    if not question:
        raise HTTPException(status_code=400, detail="missing_question")

    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        interaction = client.interactions.create(
            input=question,
            agent=agent,
            previous_interaction_id=prev_id,
            background=True,
            store=True,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail={"deep_research_followup_failed": str(e)})

    interaction_id = str(getattr(interaction, "id", "") or "").strip()
    if not interaction_id:
        raise HTTPException(status_code=502, detail="missing_interaction_id")

    job_id = _job_id()
    status = str(getattr(interaction, "status", "in_progress") or "in_progress")
    _db_upsert_job(job_id=job_id, interaction_id=interaction_id, agent=agent, query=question, status=status)

    return {
        "ok": True,
        "job_id": job_id,
        "interaction_id": interaction_id,
        "status": status,
        "agent": agent,
        "previous_interaction_id": prev_id,
    }
