from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import fitz  # PyMuPDF
import pytesseract
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from PIL import Image

APP_NAME = "mcp-doc-archiver"
APP_VERSION = "0.1.0"

PORT = int(os.getenv("PORT", "8066"))

DATA_DIR = Path(os.getenv("DOC_ARCHIVER_DATA_DIR", "/data")).resolve()
DB_PATH = Path(os.getenv("DOC_ARCHIVER_DB_PATH", str(DATA_DIR / "sqlite" / "doc-archiver.sqlite"))).resolve()
ARTIFACT_DIR = Path(os.getenv("DOC_ARCHIVER_ARTIFACT_DIR", str(DATA_DIR / "artifacts"))).resolve()

MCP_RAG_BASE_URL = (os.getenv("DOC_ARCHIVER_MCP_RAG_URL") or "http://mcp-rag:8055").strip().rstrip("/")
OPENAI_BASE_URL = (os.getenv("DOC_ARCHIVER_OPENAI_BASE_URL") or "http://mcp-openai-gateway:8181").strip().rstrip("/")
OPENAI_MODEL = (os.getenv("DOC_ARCHIVER_OPENAI_MODEL") or "glama-default").strip()

HTTP_TIMEOUT = float(os.getenv("DOC_ARCHIVER_TIMEOUT_SECONDS", "60"))


def _utc_ms() -> int:
    return int(time.time() * 1000)


def _ensure_dirs() -> None:
    (DATA_DIR / "sqlite").mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    _ensure_dirs()
    with _db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                created_at_ms INTEGER NOT NULL,
                filename TEXT,
                mime_type TEXT,
                sha256 TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                doc_group TEXT NOT NULL,
                labels_json TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_uri TEXT,
                extracted_text TEXT,
                status TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                FOREIGN KEY(doc_id) REFERENCES documents(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extractions (
                id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                extracted_json TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                FOREIGN KEY(doc_id) REFERENCES documents(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_extractions_doc_kind ON extractions(doc_id, kind)"
        )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_labels(labels: str) -> List[str]:
    raw = [part.strip() for part in (labels or "").split(",") if part.strip()]
    uniq: List[str] = []
    seen = set()
    for x in raw:
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
    return uniq


def _doc_dir(doc_id: str) -> Path:
    return ARTIFACT_DIR / doc_id


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _extract_text_from_pdf(pdf_bytes: bytes) -> Tuple[str, Dict[str, Any]]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = doc.page_count
    text_parts: List[str] = []
    for i in range(pages):
        page = doc.load_page(i)
        txt = (page.get_text("text") or "").strip()
        if txt:
            text_parts.append(txt)

    text = "\n\n".join(text_parts).strip()

    meta: Dict[str, Any] = {"pages": pages, "mode": "text"}

    if len(text) >= 200:
        return text, meta

    ocr_parts: List[str] = []
    for i in range(pages):
        page = doc.load_page(i)
        pix = page.get_pixmap(dpi=220)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        ocr = (pytesseract.image_to_string(img) or "").strip()
        if ocr:
            ocr_parts.append(ocr)

    ocr_text = "\n\n".join(ocr_parts).strip()
    meta["mode"] = "ocr" if ocr_text else "empty"
    return ocr_text, meta


def _extract_text_from_image(image_bytes: bytes) -> Tuple[str, Dict[str, Any]]:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    ocr = (pytesseract.image_to_string(img) or "").strip()
    return ocr, {"mode": "ocr"}


def _extract_text(filename: str, mime_type: str, data: bytes) -> Tuple[str, Dict[str, Any]]:
    name = (filename or "").lower()
    mt = (mime_type or "").lower()

    if mt == "application/pdf" or name.endswith(".pdf"):
        return _extract_text_from_pdf(data)

    if mt.startswith("image/") or any(name.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
        try:
            import io
        except Exception:
            raise
        img = Image.open(io.BytesIO(data)).convert("RGB")
        ocr = (pytesseract.image_to_string(img) or "").strip()
        return ocr, {"mode": "ocr"}

    try:
        text = data.decode("utf-8")
    except Exception:
        text = data.decode("utf-8", errors="ignore")

    return (text or "").strip(), {"mode": "text"}


def _chunk_text(text: str, *, max_chars: int = 900, overlap: int = 120) -> List[str]:
    cleaned = re.sub(r"\r\n?", "\n", text or "").strip()
    if not cleaned:
        return []

    paras = [p.strip() for p in re.split(r"\n\n+", cleaned) if p.strip()]
    chunks: List[str] = []
    buf = ""
    for p in paras:
        if not buf:
            buf = p
        elif len(buf) + 2 + len(p) <= max_chars:
            buf = buf + "\n\n" + p
        else:
            chunks.append(buf)
            if overlap > 0 and len(buf) > overlap:
                tail = buf[-overlap:]
                buf = tail + "\n\n" + p
            else:
                buf = p

    if buf:
        chunks.append(buf)

    final: List[str] = []
    for c in chunks:
        c2 = c.strip()
        if c2:
            final.append(c2)
    return final


async def _rag_invoke(tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{MCP_RAG_BASE_URL}/invoke"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(url, json={"tool": tool, "arguments": arguments})
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=r.text or f"rag_http_{r.status_code}")
        return r.json()


async def _openai_chat(messages: List[Dict[str, str]], temperature: float = 0.2) -> Dict[str, Any]:
    url = f"{OPENAI_BASE_URL}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": float(temperature),
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(url, json=payload)
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=r.text or f"openai_http_{r.status_code}")
        return r.json()


def _extract_content(resp: Dict[str, Any]) -> str:
    try:
        return str(resp["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return ""


async def _index_doc(doc_id: str) -> int:
    with _db() as conn:
        doc = conn.execute(
            "SELECT id, filename, doc_group, labels_json FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if not doc:
            raise HTTPException(status_code=404, detail="doc_not_found")

        rows = conn.execute(
            "SELECT id, chunk_index, text FROM chunks WHERE doc_id = ? ORDER BY chunk_index ASC",
            (doc_id,),
        ).fetchall()

    labels: List[str] = []
    try:
        labels = json.loads(doc["labels_json"]) or []
    except Exception:
        labels = []

    items: List[Dict[str, Any]] = []
    for r in rows:
        items.append(
            {
                "id": str(r["id"]),
                "text": str(r["text"]),
                "metadata": {
                    "doc_id": str(doc_id),
                    "chunk_id": str(r["id"]),
                    "chunk_index": int(r["chunk_index"]),
                    "group": str(doc["doc_group"]),
                    "labels": labels,
                    "filename": doc["filename"],
                },
            }
        )

    if not items:
        raise HTTPException(status_code=400, detail="no_chunks")

    res = await _rag_invoke("upsert_text", {"items": items})

    with _db() as conn:
        conn.execute("UPDATE documents SET status = ? WHERE id = ?", ("indexed", doc_id))

    return int(((res.get("result") or {}).get("upserted") or 0))


class IngestResponse(BaseModel):
    doc_id: str
    sha256: str
    doc_group: str
    labels: List[str]
    extracted_chars: int
    chunks: int
    indexed: bool = False
    index_error: Optional[str] = None


class DocInfo(BaseModel):
    id: str
    created_at_ms: int
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    sha256: str
    doc_type: str
    doc_group: str
    labels: List[str]
    status: str


class ListDocsResponse(BaseModel):
    items: List[DocInfo]


class IndexResponse(BaseModel):
    doc_id: str
    upserted: int


class ChatScope(BaseModel):
    groups: List[str] = Field(default_factory=list)
    labels: List[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    query: str
    scope: ChatScope = Field(default_factory=ChatScope)
    top_k: int = 10


class Citation(BaseModel):
    doc_id: str
    chunk_id: str
    score: float
    snippet: str
    group: Optional[str] = None
    labels: List[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    citations: List[Citation]


class ExtractRequest(BaseModel):
    doc_id: str
    kind: str = Field("invoice", description="invoice|bank_slip|meeting_report")


class ExtractResponse(BaseModel):
    doc_id: str
    kind: str
    extracted: Dict[str, Any]


class StoredExtraction(BaseModel):
    id: str
    doc_id: str
    kind: str
    extracted: Dict[str, Any]
    created_at_ms: int


class ListExtractionsResponse(BaseModel):
    items: List[StoredExtraction]


class AuditScope(BaseModel):
    groups: List[str] = Field(default_factory=list)
    labels: List[str] = Field(default_factory=list)


class ExtractionQueryRequest(BaseModel):
    scope: AuditScope = Field(default_factory=AuditScope)
    kind: str = "invoice"
    group_by: str = "vendor"
    sum_field: str = "total"


class ExtractionQueryRow(BaseModel):
    key: str
    sum: float
    count: int
    doc_ids: List[str] = Field(default_factory=list)


class ExtractionQueryResponse(BaseModel):
    kind: str
    group_by: str
    sum_field: str
    rows: List[ExtractionQueryRow]


class AuditCompareRequest(BaseModel):
    left: AuditScope
    right: AuditScope
    left_kind: str = "invoice"
    right_kind: str = "bank_slip"
    left_field: str = "total"
    right_field: str = "amount"
    tolerance: float = 0.0
    auto_extract_missing: bool = True
    max_auto_extract_docs: int = 24


class AuditCompareResponse(BaseModel):
    left_total: float
    right_total: float
    delta: float
    ok: bool
    left_docs: List[str] = Field(default_factory=list)
    right_docs: List[str] = Field(default_factory=list)


app = FastAPI(title=APP_NAME, version=APP_VERSION)


@app.on_event("startup")
def _startup() -> None:
    _init_db()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "ragUrl": MCP_RAG_BASE_URL,
        "openaiUrl": OPENAI_BASE_URL,
        "timestampMs": _utc_ms(),
    }


@app.get("/docs/", response_class=HTMLResponse)
def docs_ui() -> str:
    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Doc Archiver</title>
  <style>
    :root{color-scheme:dark;--bg:#0b1020;--panel:#111a33;--border:rgba(255,255,255,.12);--accent:#7ef2c9;--subtle:#b4bad8;}
    body{margin:0;font-family:Segoe UI,system-ui,sans-serif;background:var(--bg);color:#f4f7ff;padding:18px;}
    .wrap{max-width:1100px;margin:0 auto;display:flex;flex-direction:column;gap:14px;}
    .card{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:14px;}
    h1{margin:0;font-size:22px;}
    label{font-size:12px;color:var(--subtle);display:block;margin-bottom:6px;}
    input,select,textarea{width:100%;border-radius:12px;border:1px solid rgba(255,255,255,.14);background:rgba(0,0,0,.25);color:#f4f7ff;padding:10px;}
    button{border:1px solid rgba(126,242,201,.5);background:rgba(4,10,24,.9);color:var(--accent);border-radius:999px;padding:10px 14px;font-weight:600;cursor:pointer;}
    button:disabled{opacity:.5;cursor:wait;}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
    .row{display:flex;gap:10px;align-items:end;}
    .row > div{flex:1;}
    .mono{font-family:Consolas,Menlo,monospace;font-size:12px;color:rgba(180,186,216,.95);white-space:pre-wrap;}
    .cit{border-top:1px solid rgba(255,255,255,.1);padding-top:10px;margin-top:10px;}
    a{color:var(--accent);text-decoration:none;}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"card\">
      <h1>Document archiver (MVP)</h1>
      <div style=\"margin-top:6px;color:var(--subtle)\">Upload docs, label/group them, then chat with citations.</div>
      <div style=\"margin-top:6px\"><a href=\"/chat/\">Back to chat</a></div>
    </div>

    <div class=\"card\">
      <div class=\"grid\">
        <div>
          <label>Group</label>
          <input id=\"group\" placeholder=\"e.g. 2025-q4\" />
        </div>
        <div>
          <label>Labels (comma separated)</label>
          <input id=\"labels\" placeholder=\"invoice,bank,meeting\" />
        </div>
      </div>
      <div class=\"row\" style=\"margin-top:10px\">
        <div>
          <label>Doc type</label>
          <select id=\"doctype\">
            <option value=\"invoice\">invoice</option>
            <option value=\"bank_slip\">bank_slip</option>
            <option value=\"meeting_report\">meeting_report</option>
            <option value=\"general\">general</option>
          </select>
        </div>
        <div>
          <label>Upload</label>
          <input id=\"file\" type=\"file\" />
        </div>
        <div style=\"flex:0 0 auto\">
          <button id=\"uploadBtn\" type=\"button\">Ingest</button>
        </div>
      </div>
      <div id=\"ingestStatus\" class=\"mono\" style=\"margin-top:10px\"></div>
      <div id=\"uploadOut\" class=\"mono\" style=\"margin-top:10px\"></div>
    </div>

    <div class=\"card\">
      <div class=\"row\">
        <div>
          <label>Doc ID</label>
          <input id=\"docId\" placeholder=\"paste a doc_id from the list\" />
        </div>
        <div style=\"flex:0 0 auto\">
          <button id=\"indexBtn\" type=\"button\">Index</button>
        </div>
      </div>
      <div id=\"indexOut\" class=\"mono\" style=\"margin-top:10px\"></div>
    </div>

    <div class=\"card\">
      <div class=\"row\">
        <div>
          <label>Search scope groups (comma)</label>
          <input id=\"scopeGroups\" placeholder=\"2025-q4,2025-q3\" />
        </div>
        <div>
          <label>Search scope labels (comma)</label>
          <input id=\"scopeLabels\" placeholder=\"invoice,bank\" />
        </div>
      </div>
      <div style=\"margin-top:10px\">
        <label>Ask</label>
        <textarea id=\"query\" rows=\"3\" placeholder=\"What is the total amount paid to vendor X in Q4?\"></textarea>
      </div>
      <div style=\"margin-top:10px\">
        <button id=\"askBtn\" type=\"button\">Chat</button>
      </div>
      <div id=\"chatOut\" class=\"mono\" style=\"margin-top:10px\"></div>
      <div id=\"cits\" class=\"mono cit\" style=\"display:none\"></div>
    </div>

    <div class=\"card\">
      <div class=\"row\" style=\"justify-content:space-between\">
        <div style=\"flex:1\">
          <label>Documents</label>
          <div class=\"mono\" id=\"docsOut\">Loading…</div>
        </div>
        <div style=\"flex:0 0 auto\">
          <button id=\"refreshBtn\" type=\"button\">Refresh</button>
        </div>
      </div>
    </div>

  </div>

<script type=\"module\">
  const api = (path) => `/docs/api${path}`;
  const $ = (id) => document.getElementById(id);
  const splitCSV = (v) => String(v||'').split(',').map(x=>x.trim()).filter(Boolean);

  const uploadBtn = $('uploadBtn');
  const indexBtn = $('indexBtn');
  const askBtn = $('askBtn');
  const refreshBtn = $('refreshBtn');

  const renderDocs = async () => {
    const out = $('docsOut');
    out.textContent = 'Loading…';
    const r = await fetch(api('/docs'), { cache: 'no-store' });
    const data = await r.json();
    out.textContent = JSON.stringify(data, null, 2);
  };

  refreshBtn.addEventListener('click', renderDocs);

  uploadBtn.addEventListener('click', async () => {
    const file = $('file').files?.[0];
    if (!file) return;
    uploadBtn.disabled = true;
    $('uploadOut').textContent = 'Uploading…';
    $('ingestStatus').textContent = '';
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('doc_group', $('group').value || 'default');
      fd.append('labels', $('labels').value || '');
      fd.append('doc_type', $('doctype').value || 'general');
      const r = await fetch(api('/ingest'), { method: 'POST', body: fd });
      const data = await r.json();
      if (data?.indexed) {
        $('ingestStatus').textContent = 'Index: OK';
      } else if (data?.index_error) {
        $('ingestStatus').textContent = 'Index: FAILED - ' + String(data.index_error);
      } else {
        $('ingestStatus').textContent = 'Index: (not attempted)';
      }
      $('uploadOut').textContent = JSON.stringify(data, null, 2);
      if (data?.doc_id) {
        $('docId').value = data.doc_id;
      }
      await renderDocs();
    } catch (e) {
      $('uploadOut').textContent = String(e);
    } finally {
      uploadBtn.disabled = false;
    }
  });

  indexBtn.addEventListener('click', async () => {
    const docId = ($('docId').value || '').trim();
    if (!docId) return;
    indexBtn.disabled = true;
    $('indexOut').textContent = 'Indexing…';
    try {
      const r = await fetch(api(`/docs/${encodeURIComponent(docId)}/index`), { method: 'POST' });
      const data = await r.json();
      $('indexOut').textContent = JSON.stringify(data, null, 2);
      await renderDocs();
    } catch (e) {
      $('indexOut').textContent = String(e);
    } finally {
      indexBtn.disabled = false;
    }
  });

  askBtn.addEventListener('click', async () => {
    askBtn.disabled = true;
    $('chatOut').textContent = 'Thinking…';
    $('cits').style.display = 'none';
    try {
      const payload = {
        query: $('query').value || '',
        scope: { groups: splitCSV($('scopeGroups').value), labels: splitCSV($('scopeLabels').value) },
        top_k: 10
      };
      const r = await fetch(api('/chat'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const data = await r.json();
      $('chatOut').textContent = data.answer || '';
      $('cits').style.display = 'block';
      $('cits').textContent = 'CITATIONS\n' + JSON.stringify(data.citations || [], null, 2);
    } catch (e) {
      $('chatOut').textContent = String(e);
    } finally {
      askBtn.disabled = false;
    }
  });

  renderDocs();
</script>
</body>
</html>"""


@app.get("/docs/api/docs", response_model=ListDocsResponse)
def list_docs() -> ListDocsResponse:
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, created_at_ms, filename, mime_type, sha256, doc_type, doc_group, labels_json, status FROM documents ORDER BY created_at_ms DESC LIMIT 200"
        ).fetchall()

    items: List[DocInfo] = []
    for r in rows:
        labels = []
        try:
            labels = json.loads(r["labels_json"]) or []
        except Exception:
            labels = []
        items.append(
            DocInfo(
                id=str(r["id"]),
                created_at_ms=int(r["created_at_ms"]),
                filename=r["filename"],
                mime_type=r["mime_type"],
                sha256=str(r["sha256"]),
                doc_type=str(r["doc_type"]),
                doc_group=str(r["doc_group"]),
                labels=[str(x) for x in labels if isinstance(x, str)],
                status=str(r["status"]),
            )
        )

    return ListDocsResponse(items=items)


@app.post("/docs/api/ingest", response_model=IngestResponse)
async def ingest(
    file: UploadFile = File(...),
    doc_group: str = Form("default"),
    labels: str = Form(""),
    doc_type: str = Form("general"),
) -> IngestResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty_file")

    doc_id = str(uuid.uuid4())
    sha256 = _sha256_bytes(raw)
    label_list = _safe_labels(labels)

    name = file.filename or "upload"
    mime = file.content_type or "application/octet-stream"

    text, meta = _extract_text(name, mime, raw)

    ddir = _doc_dir(doc_id)
    ddir.mkdir(parents=True, exist_ok=True)
    _write_bytes(ddir / "source.bin", raw)
    _write_text(ddir / "extracted.txt", text)
    _write_text(ddir / "extract_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))

    now = _utc_ms()
    with _db() as conn:
        conn.execute(
            "INSERT INTO documents (id, created_at_ms, filename, mime_type, sha256, doc_type, doc_group, labels_json, source_kind, source_uri, extracted_text, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc_id,
                now,
                name,
                mime,
                sha256,
                (doc_type or "general").strip() or "general",
                (doc_group or "default").strip() or "default",
                json.dumps(label_list, ensure_ascii=False),
                "upload",
                None,
                text,
                "ingested",
            ),
        )

    chunks = _chunk_text(text)
    inserted = 0
    with _db() as conn:
        for idx, chunk in enumerate(chunks):
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{idx}"))
            conn.execute(
                "INSERT OR REPLACE INTO chunks (id, doc_id, chunk_index, text, created_at_ms) VALUES (?, ?, ?, ?, ?)",
                (chunk_id, doc_id, idx, chunk, now),
            )
            inserted += 1

    indexed = False
    index_error: Optional[str] = None
    if inserted > 0:
        try:
            await _index_doc(doc_id)
            indexed = True
        except Exception:
            indexed = False
            index_error = "index_failed"

    return IngestResponse(
        doc_id=doc_id,
        sha256=sha256,
        doc_group=(doc_group or "default").strip() or "default",
        labels=label_list,
        extracted_chars=len(text or ""),
        chunks=inserted,
        indexed=indexed,
        index_error=index_error,
    )


@app.post("/docs/api/docs/{doc_id}/index", response_model=IndexResponse)
async def index_doc(doc_id: str) -> IndexResponse:
    upserted = await _index_doc(doc_id)
    return IndexResponse(doc_id=doc_id, upserted=upserted)


@app.post("/docs/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="empty_query")

    limit = max(1, min(int(req.top_k or 10), 30))

    raw = await _rag_invoke("search_text", {"query": query, "limit": max(10, limit * 4)})
    results = ((raw.get("result") or {}).get("results") or [])

    want_groups = {g.strip() for g in (req.scope.groups or []) if g.strip()}
    want_labels = {l.strip().lower() for l in (req.scope.labels or []) if l.strip()}

    picked: List[Citation] = []

    for hit in results:
        payload = hit.get("payload") or {}
        group = str(payload.get("group") or "")
        labels = payload.get("labels") or []
        if not isinstance(labels, list):
            labels = []
        label_norm = {str(x).lower() for x in labels if isinstance(x, str)}

        if want_groups and group not in want_groups:
            continue
        if want_labels and not (label_norm & want_labels):
            continue

        doc_id = str(payload.get("doc_id") or "")
        chunk_id = str(payload.get("chunk_id") or payload.get("id") or hit.get("id") or "")
        text = str(payload.get("text") or "")
        snippet = text[:360].replace("\n", " ")
        try:
            score = float(hit.get("score") or 0)
        except Exception:
            score = 0.0

        if doc_id and chunk_id:
            picked.append(
                Citation(
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                    score=score,
                    snippet=snippet,
                    group=group or None,
                    labels=[str(x) for x in labels if isinstance(x, str)],
                )
            )
        if len(picked) >= limit:
            break

    context_lines: List[str] = []
    for i, c in enumerate(picked, start=1):
        context_lines.append(
            f"[{i}] doc_id={c.doc_id} chunk_id={c.chunk_id} group={c.group or ''} labels={','.join(c.labels)}\n{c.snippet}"
        )

    system = (
        "You are an assistant that answers questions using the provided document excerpts. "
        "If you use an excerpt, cite it as [n] where n matches the excerpt number. "
        "If the answer is not in the excerpts, say you cannot find it in the selected document set."
    )

    user = "Question: " + query + "\n\n" + "Excerpts:\n" + ("\n\n".join(context_lines) if context_lines else "(none)")

    resp = await _openai_chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
    )

    answer = _extract_content(resp)
    return ChatResponse(answer=answer, citations=picked)


@app.post("/docs/api/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest) -> ExtractResponse:
    kind = (req.kind or "invoice").strip()
    if kind not in ("invoice", "bank_slip", "meeting_report"):
        raise HTTPException(status_code=400, detail="invalid_kind")

    with _db() as conn:
        doc = conn.execute(
            "SELECT id, extracted_text, filename, doc_group, labels_json FROM documents WHERE id = ?",
            (req.doc_id,),
        ).fetchone()
        if not doc:
            raise HTTPException(status_code=404, detail="doc_not_found")

    text = (doc["extracted_text"] or "").strip()
    text = text[:12000]

    if kind == "invoice":
        schema_hint = "Return JSON with keys: vendor, invoice_no, invoice_date, currency, subtotal, tax, total, due_date, payment_terms. Use null if unknown."
    elif kind == "bank_slip":
        schema_hint = "Return JSON with keys: bank, payer, payee, amount, currency, date, reference, account_last4. Use null if unknown."
    else:
        schema_hint = "Return JSON with keys: title, meeting_date, attendees, decisions, action_items. Use null if unknown."

    sys = "You extract structured data from a single document. Output ONLY valid JSON." 
    user = f"Document filename: {doc['filename']}\nGroup: {doc['doc_group']}\nText:\n{text}\n\nTask: {schema_hint}"

    resp = await _openai_chat(
        [
            {"role": "system", "content": sys},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
    )

    content = _extract_content(resp)
    extracted: Dict[str, Any] = {}
    try:
        extracted = json.loads(content)
        if not isinstance(extracted, dict):
            extracted = {"raw": content}
    except Exception:
        extracted = {"raw": content}

    now = _utc_ms()
    extraction_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"extract:{req.doc_id}:{kind}:{now}"))
    with _db() as conn:
        conn.execute(
            "INSERT INTO extractions (id, doc_id, kind, extracted_json, created_at_ms) VALUES (?, ?, ?, ?, ?)",
            (extraction_id, req.doc_id, kind, json.dumps(extracted, ensure_ascii=False), now),
        )

    return ExtractResponse(doc_id=req.doc_id, kind=kind, extracted=extracted)


@app.get("/docs/api/docs/{doc_id}/extractions", response_model=ListExtractionsResponse)
def list_extractions(doc_id: str) -> ListExtractionsResponse:
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, doc_id, kind, extracted_json, created_at_ms FROM extractions WHERE doc_id = ? ORDER BY created_at_ms DESC",
            (doc_id,),
        ).fetchall()

    items: List[StoredExtraction] = []
    for r in rows:
        try:
            parsed = json.loads(r["extracted_json"]) if r["extracted_json"] else {}
        except Exception:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {"raw": r["extracted_json"]}
        items.append(
            StoredExtraction(
                id=str(r["id"]),
                doc_id=str(r["doc_id"]),
                kind=str(r["kind"]),
                extracted=parsed,
                created_at_ms=int(r["created_at_ms"]),
            )
        )
    return ListExtractionsResponse(items=items)


@app.post("/docs/api/extractions/query", response_model=ExtractionQueryResponse)
def query_extractions(req: ExtractionQueryRequest) -> ExtractionQueryResponse:
    kind = (req.kind or "invoice").strip()
    group_by = (req.group_by or "vendor").strip()
    sum_field = (req.sum_field or "total").strip()

    where, args = _scope_where(req.scope)
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT d.id AS doc_id, e.extracted_json AS extracted_json
            FROM documents d
            JOIN extractions e ON e.doc_id = d.id
            WHERE """
            + where
            + " AND e.kind = ?",
            [*args, kind],
        ).fetchall()

    grouped: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            parsed = json.loads(r["extracted_json"]) if r["extracted_json"] else {}
        except Exception:
            parsed = {}
        if not isinstance(parsed, dict):
            continue

        key = _coerce_str(parsed.get(group_by)) or "(unknown)"
        val = _coerce_float(parsed.get(sum_field))
        if val is None:
            continue

        rec = grouped.get(key)
        if not rec:
            rec = {"sum": 0.0, "count": 0, "doc_ids": []}
            grouped[key] = rec
        rec["sum"] = float(rec["sum"]) + float(val)
        rec["count"] = int(rec["count"]) + 1
        rec["doc_ids"].append(str(r["doc_id"]))

    out_rows: List[ExtractionQueryRow] = []
    for k, rec in grouped.items():
        out_rows.append(
            ExtractionQueryRow(
                key=str(k),
                sum=float(rec["sum"]),
                count=int(rec["count"]),
                doc_ids=[str(x) for x in rec["doc_ids"]],
            )
        )
    out_rows.sort(key=lambda x: x.sum, reverse=True)

    return ExtractionQueryResponse(kind=kind, group_by=group_by, sum_field=sum_field, rows=out_rows)


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None
    s = str(value).strip()
    if not s:
        return None
    s = re.sub(r"[^0-9.\-]", "", s)
    if not s or s in ("-", "."):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _scope_where(scope: AuditScope) -> Tuple[str, List[Any]]:
    where = "1=1"
    args: List[Any] = []
    groups = [g.strip() for g in (scope.groups or []) if g.strip()]
    labels = [l.strip().lower() for l in (scope.labels or []) if l.strip()]
    if groups:
        where += " AND d.doc_group IN (" + ",".join(["?"] * len(groups)) + ")"
        args.extend(groups)
    if labels:
        parts = []
        for l in labels:
            parts.append("LOWER(d.labels_json) LIKE ?")
            args.append(f"%{l}%")
        where += " AND (" + " OR ".join(parts) + ")"
    return where, args


def _coerce_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s


def _list_doc_ids_for_scope(scope: AuditScope) -> List[str]:
    where, args = _scope_where(scope)
    with _db() as conn:
        rows = conn.execute(
            "SELECT d.id AS doc_id FROM documents d WHERE " + where + " ORDER BY d.created_at_ms DESC",
            args,
        ).fetchall()
    return [str(r["doc_id"]) for r in rows]


async def _extract_doc_and_store(doc_id: str, kind: str) -> Dict[str, Any]:
    with _db() as conn:
        doc = conn.execute(
            "SELECT id, extracted_text, filename, doc_group FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if not doc:
            raise HTTPException(status_code=404, detail="doc_not_found")

    text = (doc["extracted_text"] or "").strip()[:12000]

    if kind == "invoice":
        schema_hint = "Return JSON with keys: vendor, invoice_no, invoice_date, currency, subtotal, tax, total, due_date, payment_terms. Use null if unknown."
    elif kind == "bank_slip":
        schema_hint = "Return JSON with keys: bank, payer, payee, amount, currency, date, reference, account_last4. Use null if unknown."
    else:
        schema_hint = "Return JSON with keys: title, meeting_date, attendees, decisions, action_items. Use null if unknown."

    sys = "You extract structured data from a single document. Output ONLY valid JSON."
    user = f"Document filename: {doc['filename']}\nGroup: {doc['doc_group']}\nText:\n{text}\n\nTask: {schema_hint}"

    resp = await _openai_chat(
        [
            {"role": "system", "content": sys},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
    )

    content = _extract_content(resp)
    extracted: Dict[str, Any] = {}
    try:
        extracted = json.loads(content)
        if not isinstance(extracted, dict):
            extracted = {"raw": content}
    except Exception:
        extracted = {"raw": content}

    now = _utc_ms()
    extraction_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"extract:{doc_id}:{kind}:{now}"))
    with _db() as conn:
        conn.execute(
            "INSERT INTO extractions (id, doc_id, kind, extracted_json, created_at_ms) VALUES (?, ?, ?, ?, ?)",
            (extraction_id, doc_id, kind, json.dumps(extracted, ensure_ascii=False), now),
        )

    return extracted


def _has_extraction(doc_id: str, kind: str) -> bool:
    with _db() as conn:
        row = conn.execute(
            "SELECT 1 FROM extractions WHERE doc_id = ? AND kind = ? LIMIT 1",
            (doc_id, kind),
        ).fetchone()
    return bool(row)


@app.post("/docs/api/audit/compare", response_model=AuditCompareResponse)
async def audit_compare(req: AuditCompareRequest) -> AuditCompareResponse:
    left_where, left_args = _scope_where(req.left)
    right_where, right_args = _scope_where(req.right)

    left_kind = (req.left_kind or "invoice").strip()
    right_kind = (req.right_kind or "bank_slip").strip()
    left_field = (req.left_field or "total").strip()
    right_field = (req.right_field or "amount").strip()
    tol = float(req.tolerance or 0.0)

    if bool(req.auto_extract_missing):
        cap = max(0, min(int(req.max_auto_extract_docs or 0), 200))
        left_ids = _list_doc_ids_for_scope(req.left)
        right_ids = _list_doc_ids_for_scope(req.right)
        missing: List[Tuple[str, str]] = []
        for did in left_ids:
            if not _has_extraction(did, left_kind):
                missing.append((did, left_kind))
        for did in right_ids:
            if not _has_extraction(did, right_kind):
                missing.append((did, right_kind))

        for did, kind in missing[:cap]:
            try:
                await _extract_doc_and_store(did, kind)
            except Exception:
                continue

    def _sum_for(where: str, args: List[Any], kind: str, field: str) -> Tuple[float, List[str]]:
        with _db() as conn:
            rows = conn.execute(
                """
                SELECT d.id AS doc_id, e.extracted_json AS extracted_json
                FROM documents d
                JOIN extractions e ON e.doc_id = d.id
                WHERE """
                + where
                + " AND e.kind = ?",
                [*args, kind],
            ).fetchall()

        total = 0.0
        used: List[str] = []
        for r in rows:
            try:
                parsed = json.loads(r["extracted_json"]) if r["extracted_json"] else {}
            except Exception:
                parsed = {}
            if not isinstance(parsed, dict):
                continue
            v = _coerce_float(parsed.get(field))
            if v is None:
                continue
            total += v
            used.append(str(r["doc_id"]))
        return total, used

    left_total, left_docs = _sum_for(left_where, left_args, left_kind, left_field)
    right_total, right_docs = _sum_for(right_where, right_args, right_kind, right_field)

    delta = left_total - right_total
    ok = abs(delta) <= tol

    return AuditCompareResponse(
        left_total=float(left_total),
        right_total=float(right_total),
        delta=float(delta),
        ok=bool(ok),
        left_docs=left_docs,
        right_docs=right_docs,
    )
