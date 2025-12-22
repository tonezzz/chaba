from __future__ import annotations

import base64
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = Field("0.0.0.0", alias="WEBTOPS_CP_HOST")
    port: int = Field(3005, alias="WEBTOPS_CP_PORT")

    # Control panel basic auth (admin-only)
    cp_username: str = Field("admin", alias="WEBTOPS_CP_USERNAME")
    cp_password: str = Field("", alias="WEBTOPS_CP_PASSWORD")

    # Downstream mcp-webtops connection
    webtops_base_url: str = Field("http://mcp-webtops:8091", alias="WEBTOPS_CP_WEBTOPS_BASE_URL")
    webtops_admin_token: str = Field("", alias="WEBTOPS_ADMIN_TOKEN")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()  # type: ignore[call-arg]

app = FastAPI(title="webtops-cp")


def _basic_auth_challenge() -> HTTPException:
    # Triggers browser login prompt
    return HTTPException(
        status_code=401,
        detail="Missing basic auth",
        headers={"WWW-Authenticate": 'Basic realm="webtops-cp"'},
    )


def _require_cp_auth(authorization: Optional[str]) -> None:
    if not settings.cp_password:
        raise HTTPException(status_code=503, detail="WEBTOPS_CP_PASSWORD not set")

    if not authorization or not authorization.lower().startswith("basic "):
        raise _basic_auth_challenge()

    try:
        decoded = base64.b64decode(authorization.split(" ", 1)[1].strip()).decode("utf-8")
    except Exception:
        raise _basic_auth_challenge()

    if ":" not in decoded:
        raise _basic_auth_challenge()

    user, pwd = decoded.split(":", 1)
    if user != settings.cp_username or pwd != settings.cp_password:
        raise _basic_auth_challenge()


def _require_webtops_token() -> str:
    if not settings.webtops_admin_token:
        raise HTTPException(status_code=503, detail="WEBTOPS_ADMIN_TOKEN not set (server-side)")
    return settings.webtops_admin_token


async def _webtops_invoke(tool: str, arguments: Dict[str, Any], require_admin: bool = False) -> Dict[str, Any]:
    url = settings.webtops_base_url.rstrip("/") + "/invoke"
    headers: Dict[str, str] = {}
    if require_admin:
        token = _require_webtops_token()
        headers["Authorization"] = f"Bearer {token}"
    payload = {"tool": tool, "arguments": arguments}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"webtops_invoke_failed: HTTP {resp.status_code}: {resp.text}")
        return resp.json()


class CreateSessionRequest(BaseModel):
    user_id: str
    ttl_minutes: Optional[float] = None
    profile: Optional[str] = None


class RenameSessionRequest(BaseModel):
    name: str


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, authorization: Optional[str] = Header(default=None)) -> HTMLResponse:
    _require_cp_auth(authorization)

    html = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Webtops Control Panel</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; }
    .row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
    input { padding: 8px 10px; border: 1px solid #ddd; border-radius: 8px; }
    button { padding: 8px 10px; border: 1px solid #222; background: #111; color: #fff; border-radius: 8px; cursor: pointer; }
    button.secondary { background: #fff; color: #111; }
    table { width: 100%; border-collapse: collapse; margin-top: 16px; }
    th, td { text-align: left; border-bottom: 1px solid #eee; padding: 10px 6px; }
    code { background: #f6f6f6; padding: 2px 6px; border-radius: 6px; }
    .muted { color: #666; }
  </style>
</head>
<body>
  <h1>Webtops Control Panel</h1>
  <div class="row">
    <label>User</label>
    <input id="user" placeholder="user_id" value="tony" />
    <label>Profile</label>
    <select id="profile">
      <option value="default">default</option>
      <option value="windsurf" selected>windsurf</option>
    </select>
    <label>TTL (min)</label>
    <input id="ttl" placeholder="optional" />
    <button onclick="createSession()">Create session</button>
    <button class="secondary" onclick="refresh()">Refresh</button>
    <span id="status" class="muted"></span>
  </div>

  <table>
    <thead>
      <tr>
        <th>Session</th>
        <th>Name</th>
        <th>User</th>
        <th>Created</th>
        <th>Profile</th>
        <th>Status</th>
        <th>Access</th>
        <th>Backend</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>

<script>
async function api(path, opts) {
  const res = await fetch(path, opts || {});
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || ('HTTP ' + res.status));
  }
  return await res.json();
}

function setStatus(msg) {
  document.getElementById('status').textContent = msg;
}

function esc(s) {
  return String(s || '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
}

function fmtTs(ts) {
  if (!ts) return '';
  return String(ts).replace('T', ' ').replace('Z', ' UTC');
}

async function refresh() {
  setStatus('Loading...');
  const data = await api('/api/sessions');
  const rows = document.getElementById('rows');
  rows.innerHTML = '';
  for (const s of (data.sessions || [])) {
    const access = s.access_url || '';
    const backend = (s.backend && s.backend.type) ? s.backend.type : '';
    const containerId = (s.backend && s.backend.container_id) ? s.backend.container_id : '';
    const vol = (s.backend && s.backend.volume_id) ? s.backend.volume_id : '';
    const name = s.name || '';

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><code>${esc(s.session_id)}</code></td>
      <td>${esc(name)}</td>
      <td>${esc(s.user_id)}</td>
      <td>${esc(fmtTs(s.created_at))}</td>
      <td>${esc(s.profile)}</td>
      <td>${esc(s.status)}</td>
      <td>${access ? `<a href="${esc(access)}" target="_blank">Open</a>` : ''}</td>
      <td>${esc(backend)}<div class="muted" style="margin-top:4px">${esc(containerId ? ('ctr: ' + containerId.slice(0,12)) : '')}${esc(vol ? (' vol: ' + vol) : '')}</div></td>
      <td>
        <button class="secondary" onclick="renameSession('${esc(s.session_id)}','${esc(name)}')">Rename</button>
        <button class="secondary" onclick="stopSession('${esc(s.session_id)}')">Stop</button>
        <button onclick="deleteSession('${esc(s.session_id)}')">Delete</button>
      </td>
    `;
    rows.appendChild(tr);
  }
  setStatus('');
}

async function renameSession(sessionId, currentName) {
  const name = prompt('Rename session ' + sessionId + ' to:', currentName || '');
  if (name === null) return;
  const trimmed = String(name || '').trim();
  if (!trimmed) return;
  setStatus('Renaming...');
  await api(`/api/sessions/${sessionId}/rename`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: trimmed })
  });
  await refresh();
}

async function createSession() {
  const user = document.getElementById('user').value;
  const profile = document.getElementById('profile').value;
  const ttlStr = document.getElementById('ttl').value;
  const ttl = ttlStr ? Number(ttlStr) : null;
  setStatus('Creating...');
  await api('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: user, ttl_minutes: ttl, profile: profile })
  });
  await refresh();
}

async function stopSession(sessionId) {
  setStatus('Stopping...');
  await api(`/api/sessions/${sessionId}/stop`, { method: 'POST' });
  await refresh();
}

async function deleteSession(sessionId) {
  if (!confirm('Delete session ' + sessionId + '? This will remove the container and volume.')) return;
  setStatus('Deleting...');
  await api(`/api/sessions/${sessionId}`, { method: 'DELETE' });
  await refresh();
}

refresh();
</script>
</body>
</html>"""

    return HTMLResponse(content=html)


@app.get("/api/sessions")
async def api_list_sessions(authorization: Optional[str] = Header(default=None)) -> JSONResponse:
    _require_cp_auth(authorization)
    data = await _webtops_invoke("list_sessions", {"filter": {}}, require_admin=False)
    sessions = (data.get("result") or {}).get("sessions") or []
    return JSONResponse({"sessions": sessions})


@app.post("/api/sessions")
async def api_create_session(payload: CreateSessionRequest = Body(...), authorization: Optional[str] = Header(default=None)) -> JSONResponse:
    _require_cp_auth(authorization)
    options: Dict[str, Any] = {}
    if payload.ttl_minutes is not None:
        options["ttl_minutes"] = payload.ttl_minutes
    if payload.profile:
        options["profile"] = payload.profile

    data = await _webtops_invoke("start_session", {"user_id": payload.user_id, "options": options}, require_admin=False)
    return JSONResponse(data)


@app.post("/api/sessions/{session_id}/stop")
async def api_stop_session(session_id: str, authorization: Optional[str] = Header(default=None)) -> JSONResponse:
    _require_cp_auth(authorization)
    data = await _webtops_invoke("stop_session", {"session_id": session_id}, require_admin=False)
    return JSONResponse(data)


@app.post("/api/sessions/{session_id}/rename")
async def api_rename_session(
    session_id: str,
    payload: RenameSessionRequest = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _require_cp_auth(authorization)
    data = await _webtops_invoke(
        "rename_session",
        {"session_id": session_id, "name": payload.name},
        require_admin=True,
    )
    return JSONResponse(data)


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str, authorization: Optional[str] = Header(default=None)) -> JSONResponse:
    _require_cp_auth(authorization)
    data = await _webtops_invoke("delete_session", {"session_id": session_id}, require_admin=True)
    return JSONResponse(data)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
