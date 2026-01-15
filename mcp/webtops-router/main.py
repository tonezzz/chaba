from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

import asyncio

import websockets


logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    host: str = Field("0.0.0.0", alias="ROUTER_HOST")
    port: int = Field(3001, alias="ROUTER_PORT")
    base_path: str = Field("/webtop", alias="ROUTER_BASE_PATH")
    admin_token: str = Field(..., alias="ROUTER_ADMIN_TOKEN")
    state_file: str = Field("/state/router.json", alias="ROUTER_STATE_FILE")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()  # type: ignore[call-arg]
app = FastAPI(title="webtops-router", version="0.1.0")

_session_map: Dict[str, str] = {}


_FAVICON_ICO_B64 = (
    "AAABAAEAEBAAAAEAIABoBAAAFgAAACgAAAAQAAAAIAAAAAEAIAAAAAAAAAQAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAgICAAP///wD///8A////AP///wD///8A////AP///wD///8A////AP///"
    "wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////"
    "AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A"
    "////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A"
)


def _load_state() -> None:
    path = Path(settings.state_file)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, str):
                    _session_map[k] = v
    except Exception:
        # Keep state best-effort for skeleton.
        return


def _save_state() -> None:
    path = Path(settings.state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = f"{settings.state_file}.tmp"
    Path(tmp).write_text(json.dumps(_session_map, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, settings.state_file)


def require_admin(authorization: Optional[str]) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid admin token")
    provided = authorization.split(" ", 1)[1].strip()
    if provided != settings.admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")


class SessionRoute(BaseModel):
    upstream: str = Field(..., description="Upstream base URL, e.g. http://webtops-sess-abc123:3000")


@app.on_event("startup")
async def _startup() -> None:
    _load_state()


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "sessions": len(_session_map)}


@app.api_route("/favicon.ico", methods=["GET", "HEAD"])
async def favicon() -> Response:
    return Response(
        content=base64.b64decode(_FAVICON_ICO_B64),
        media_type="image/x-icon",
        headers={"cache-control": "public, max-age=86400"},
    )


@app.get("/admin/sessions")
async def admin_list_sessions(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    require_admin(authorization)
    return {"sessions": [{"session_id": k, "upstream": v} for k, v in _session_map.items()]}


@app.put("/admin/sessions/{session_id}")
async def admin_put_session(
    session_id: str,
    payload: SessionRoute,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_admin(authorization)
    _session_map[session_id] = payload.upstream.rstrip("/")
    _save_state()
    return {"ok": True, "session_id": session_id, "upstream": _session_map[session_id]}


@app.delete("/admin/sessions/{session_id}")
async def admin_delete_session(session_id: str, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    require_admin(authorization)
    existed = session_id in _session_map
    _session_map.pop(session_id, None)
    _save_state()
    return {"ok": True, "deleted": existed, "session_id": session_id}


@app.websocket("/{base_path}/{session_id}/websockets")
@app.websocket("/{base_path}/{session_id}/websockets/")
@app.websocket("/{base_path}/{session_id}/websocket")
@app.websocket("/{base_path}/{session_id}/websocket/")
async def proxy_websockets(websocket: WebSocket, base_path: str, session_id: str) -> None:
    try:
        # Enforce base path matches settings.
        if "/" + base_path.strip("/") != settings.base_path.rstrip("/"):
            await websocket.accept()
            await websocket.close(code=1008)
            return

        upstream = _session_map.get(session_id)
        if not upstream:
            await websocket.accept()
            await websocket.close(code=1008)
            return

        upstream = upstream.rstrip("/")
        upstream_ws_url = upstream.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/websocket"
        if websocket.url.query:
            upstream_ws_url = f"{upstream_ws_url}?{websocket.url.query}"

        # Prepare headers and subprotocol negotiation.
        extra_headers = []
        for name in ("cookie", "origin"):
            val = websocket.headers.get(name)
            if val:
                extra_headers.append((name, val))

        offered_protocols: List[str] = []
        proto_header = websocket.headers.get("sec-websocket-protocol")
        if proto_header:
            offered_protocols = [p.strip() for p in proto_header.split(",") if p.strip()]

        async with websockets.connect(
            upstream_ws_url,
            additional_headers=extra_headers,
            subprotocols=offered_protocols or None,
            ping_interval=20,
            ping_timeout=20,
        ) as upstream_ws:

            # Accept the client websocket and mirror the chosen subprotocol (if any)
            await websocket.accept(subprotocol=upstream_ws.subprotocol)

            async def _client_to_upstream() -> None:
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if msg.get("text") is not None:
                            await upstream_ws.send(msg["text"])
                        elif msg.get("bytes") is not None:
                            await upstream_ws.send(msg["bytes"])
                except WebSocketDisconnect:
                    with contextlib.suppress(Exception):
                        await upstream_ws.close()

            async def _upstream_to_client() -> None:
                try:
                    async for data in upstream_ws:
                        if isinstance(data, (bytes, bytearray)):
                            await websocket.send_bytes(bytes(data))
                        else:
                            await websocket.send_text(str(data))
                except Exception:
                    with contextlib.suppress(Exception):
                        await websocket.close(code=1000)

            await asyncio.gather(_client_to_upstream(), _upstream_to_client())

    except Exception as exc:
        logger.warning("websocket_proxy_failed session_id=%s err=%s", session_id, exc)
        with contextlib.suppress(Exception):
            await websocket.accept()
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)


@app.api_route(
    "/{base_path}/{session_id}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
@app.api_route(
    "/{base_path}/{session_id}/",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
@app.api_route(
    "/{base_path}/{session_id}/{rest_of_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy_webtop(
    request: Request,
    base_path: str,
    session_id: str,
    rest_of_path: str = "",
) -> Response:
    # base_path is captured by the route; we also enforce it matches settings.
    if "/" + base_path.strip("/") != settings.base_path.rstrip("/"):
        raise HTTPException(status_code=404, detail="unknown_base_path")

    upstream = _session_map.get(session_id)
    if not upstream:
        raise HTTPException(status_code=404, detail="unknown_session")

    upstream = upstream.rstrip("/")
    rest_of_path = rest_of_path.lstrip("/")
    target_url = f"{upstream}/{rest_of_path}" if rest_of_path else upstream + "/"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    headers = dict(request.headers)
    headers.pop("host", None)
    # Avoid upstream compression to prevent Content-Encoding/body mismatches when proxying.
    # We proxy bytes as-is and let the client handle encoding.
    for k in list(headers.keys()):
        if k.lower() == "accept-encoding":
            headers.pop(k, None)
    headers["accept-encoding"] = "identity"
    # Avoid attempting to proxy WebSocket upgrades via plain HTTP (upstream would return 101,
    # which h11/uvicorn cannot emit as a normal HTTP response).
    for h in (
        "connection",
        "upgrade",
        "sec-websocket-key",
        "sec-websocket-version",
        "sec-websocket-extensions",
        "sec-websocket-protocol",
    ):
        headers.pop(h, None)

    body = await request.body()

    async with httpx.AsyncClient(follow_redirects=False, timeout=60.0) as client:
        resp = await client.request(
            request.method,
            target_url,
            headers=headers,
            content=body if body else None,
        )

    # Filter hop-by-hop headers
    excluded = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        # Prevent browsers from attempting to decode payloads that are no longer compressed.
        "content-encoding",
        # Let FastAPI/uvicorn compute Content-Length from the bytes we return.
        "content-length",
    }
    out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded}

    # Defensive: ensure these never leak through even if casing/duplication changes.
    for k in list(out_headers.keys()):
        if k.lower() in {"content-encoding", "content-length"}:
            out_headers.pop(k, None)

    return Response(content=resp.content, status_code=resp.status_code, headers=out_headers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port, ws="websockets")
