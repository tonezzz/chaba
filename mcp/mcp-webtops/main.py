from __future__ import annotations

import json
import logging
import os
import contextlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx
from fastapi import Body, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

import docker
from docker.errors import DockerException

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    app_name: str = Field("mcp-webtops", alias="WEBTOPS_APP_NAME")
    host: str = Field("0.0.0.0", alias="WEBTOPS_HOST")
    port: int = Field(8091, alias="PORT")

    admin_token: Optional[str] = Field(None, alias="WEBTOPS_ADMIN_TOKEN")

    public_base_url: str = Field("http://localhost:3001/webtop/", alias="WEBTOPS_PUBLIC_BASE_URL")
    base_path: str = Field("/webtop/", alias="WEBTOPS_BASE_PATH")

    router_base_url: str = Field("http://webtops-router:3001", alias="WEBTOPS_ROUTER_BASE_URL")
    router_admin_token: Optional[str] = Field(None, alias="WEBTOPS_ROUTER_ADMIN_TOKEN")

    backend: str = Field("docker", alias="WEBTOPS_BACKEND")
    docker_network: str = Field("webtops-net", alias="WEBTOPS_DOCKER_NETWORK")
    session_internal_port: int = Field(3000, alias="WEBTOPS_SESSION_INTERNAL_PORT")

    session_image: str = Field("lscr.io/linuxserver/webtop:latest", alias="WEBTOPS_SESSION_IMAGE")
    session_image_pull: bool = Field(True, alias="WEBTOPS_SESSION_IMAGE_PULL")

    session_image_windsurf: str = Field("", alias="WEBTOPS_SESSION_IMAGE_WINDSURF")
    windsurf_version: str = Field("", alias="WEBTOPS_WINDSURF_VERSION")
    windsurf_download_url_template: str = Field("", alias="WEBTOPS_WINDSURF_DOWNLOAD_URL_TEMPLATE")
    windsurf_install_mode: str = Field("deb_extract", alias="WEBTOPS_WINDSURF_INSTALL_MODE")
    windsurf_deb_url_template: str = Field("", alias="WEBTOPS_WINDSURF_DEB_URL_TEMPLATE")
    windsurf_cache_volume: str = Field("webtops_windsurf_cache", alias="WEBTOPS_WINDSURF_CACHE_VOLUME")
    windsurf_cache_mount_path: str = Field("/windsurf-cache", alias="WEBTOPS_WINDSURF_CACHE_MOUNT_PATH")

    workspaces_volume: str = Field("webtops_workspaces", alias="WEBTOPS_WORKSPACES_VOLUME")
    workspaces_mount_path: str = Field("/workspaces", alias="WEBTOPS_WORKSPACES_MOUNT_PATH")
    workspaces_repo_url: str = Field("", alias="WEBTOPS_WORKSPACES_REPO_URL")
    workspaces_repo_branch: str = Field("", alias="WEBTOPS_WORKSPACES_REPO_BRANCH")
    workspaces_repo_dir: str = Field("/workspaces/chaba", alias="WEBTOPS_WORKSPACES_REPO_DIR")
    session_upstream_scheme: str = Field("http", alias="WEBTOPS_SESSION_UPSTREAM_SCHEME")
    session_container_name_prefix: str = Field("webtops-sess", alias="WEBTOPS_SESSION_NAME_PREFIX")
    session_volume_name_prefix: str = Field("webtops_sess", alias="WEBTOPS_SESSION_VOLUME_PREFIX")
    session_mount_path: str = Field("/config", alias="WEBTOPS_SESSION_MOUNT_PATH")
    session_tz: str = Field("Asia/Bangkok", alias="WEBTOPS_SESSION_TZ")
    session_puid: str = Field("1000", alias="WEBTOPS_SESSION_PUID")
    session_pgid: str = Field("1000", alias="WEBTOPS_SESSION_PGID")
    session_password: Optional[str] = Field(None, alias="WEBTOPS_SESSION_PASSWORD")

    snapshot_dir: str = Field("/snapshots", alias="WEBTOPS_SNAPSHOT_DIR")
    state_dir: str = Field("/state", alias="WEBTOPS_STATE_DIR")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()  # type: ignore[call-arg]

if settings.admin_token:
    logger.info("Admin API enabled")
else:
    logger.warning("Admin API disabled (missing WEBTOPS_ADMIN_TOKEN)")

app = FastAPI(title=settings.app_name, version="0.1.0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _state_file() -> Path:
    return Path(settings.state_dir) / "webtops-state.json"


def _ensure_state_dir() -> None:
    Path(settings.state_dir).mkdir(parents=True, exist_ok=True)


def _load_state() -> Dict[str, Any]:
    _ensure_state_dir()
    path = _state_file()
    if not path.exists():
        return {"users": {}, "sessions": {}, "snapshots": {}, "user_tags": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"users": {}, "sessions": {}, "snapshots": {}, "user_tags": {}}
        data.setdefault("users", {})
        data.setdefault("sessions", {})
        data.setdefault("snapshots", {})
        data.setdefault("user_tags", {})
        return data
    except Exception:
        return {"users": {}, "sessions": {}, "snapshots": {}, "user_tags": {}}


def _save_state(state: Dict[str, Any]) -> None:
    _ensure_state_dir()
    path = _state_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


STATE: Dict[str, Any] = {}


@app.on_event("startup")
async def _startup() -> None:
    global STATE
    STATE = _load_state()


def _require_router_token() -> str:
    if not settings.router_admin_token:
        raise HTTPException(status_code=503, detail="Router admin token missing (WEBTOPS_ROUTER_ADMIN_TOKEN)")
    return settings.router_admin_token


async def _router_put(session_id: str, upstream: str) -> None:
    token = _require_router_token()
    url = settings.router_base_url.rstrip("/") + f"/admin/sessions/{session_id}"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(url, json={"upstream": upstream}, headers=headers)
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"router_put_failed: HTTP {resp.status_code}")


async def _router_delete(session_id: str) -> None:
    token = _require_router_token()
    url = settings.router_base_url.rstrip("/") + f"/admin/sessions/{session_id}"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(url, headers=headers)
        if resp.status_code >= 400 and resp.status_code != 404:
            raise HTTPException(status_code=502, detail=f"router_delete_failed: HTTP {resp.status_code}")


async def _router_list() -> Dict[str, Any]:
    token = _require_router_token()
    url = settings.router_base_url.rstrip("/") + "/admin/sessions"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"router_list_failed: HTTP {resp.status_code}")
        return resp.json()


def _docker_client() -> docker.DockerClient:
    try:
        return docker.from_env()
    except DockerException as exc:
        raise HTTPException(status_code=503, detail=f"docker_unavailable: {exc}")


def _resolve_network_name(client: docker.DockerClient, network_name: str) -> str:
    """Resolve a configured network name to an actual Docker network name.

    Compose often creates prefixed network names like '<project>_<network>'.
    Users frequently (and reasonably) configure the short name.
    """
    try:
        client.networks.get(network_name)
        return network_name
    except docker.errors.NotFound:
        pass
    except DockerException as exc:
        raise HTTPException(status_code=503, detail=f"docker_network_error: {exc}")

    try:
        candidates = client.networks.list()
    except DockerException as exc:
        raise HTTPException(status_code=503, detail=f"docker_network_list_failed: {exc}")

    suffix = f"_{network_name}".lower()
    for n in candidates:
        try:
            n_name = (getattr(n, "name", None) or "").strip()
        except Exception:
            continue
        if n_name.lower().endswith(suffix):
            return n_name

    raise HTTPException(
        status_code=400,
        detail=(
            f"docker_network_not_found: '{network_name}'. "
            "Set WEBTOPS_DOCKER_NETWORK to the actual Docker network name created by compose."
        ),
    )


def _build_linuxserver_env() -> Dict[str, str]:
    env: Dict[str, str] = {
        "TZ": settings.session_tz,
        "PUID": settings.session_puid,
        "PGID": settings.session_pgid,
        "HOME": settings.session_mount_path,
    }
    if settings.session_password:
        env["PASSWORD"] = settings.session_password
    return env


def _maybe_add_workspaces(
    client: docker.DockerClient,
    env: Dict[str, str],
    volumes: Dict[str, Dict[str, str]],
) -> None:
    if not settings.workspaces_volume or not settings.workspaces_mount_path:
        return
    try:
        workspaces_volume = client.volumes.get(settings.workspaces_volume)
    except docker.errors.NotFound:
        try:
            workspaces_volume = client.volumes.create(name=settings.workspaces_volume)
        except DockerException as exc:
            raise HTTPException(status_code=502, detail=f"docker_volume_create_failed: {exc}")
    except DockerException as exc:
        raise HTTPException(status_code=502, detail=f"docker_volume_get_failed: {exc}")

    volumes[workspaces_volume.name] = {"bind": settings.workspaces_mount_path, "mode": "rw"}
    env["WORKSPACES_ROOT"] = settings.workspaces_mount_path
    env["WORKSPACES_REPO_DIR"] = settings.workspaces_repo_dir or f"{settings.workspaces_mount_path.rstrip('/')}/chaba"
    if settings.workspaces_repo_url:
        env["WORKSPACES_REPO_URL"] = settings.workspaces_repo_url
    if settings.workspaces_repo_branch:
        env["WORKSPACES_REPO_BRANCH"] = settings.workspaces_repo_branch


def _normalize_profile(profile: Any) -> str:
    if profile is None or profile == "":
        return "default"
    if not isinstance(profile, str):
        raise HTTPException(status_code=400, detail="options.profile must be a string")
    p = profile.strip().lower()
    if p in {"default", "windsurf"}:
        return p
    raise HTTPException(status_code=400, detail="unsupported_profile")


def _make_upstream(container_name: str) -> str:
    scheme = (settings.session_upstream_scheme or "http").strip().lower()
    if scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="invalid WEBTOPS_SESSION_UPSTREAM_SCHEME (must be http or https)")
    return f"{scheme}://{container_name}:{settings.session_internal_port}"


def _ensure_image(client: docker.DockerClient, image: str) -> None:
    try:
        client.images.get(image)
        return
    except docker.errors.ImageNotFound:
        if not settings.session_image_pull:
            raise HTTPException(status_code=400, detail=f"docker_image_not_found: {image}")
        try:
            client.images.pull(image)
        except DockerException as exc:
            raise HTTPException(status_code=502, detail=f"docker_image_pull_failed: {exc}")
    except DockerException as exc:
        raise HTTPException(status_code=503, detail=f"docker_image_check_failed: {exc}")


def _copy_docker_volume(
    client: docker.DockerClient,
    src_volume: str,
    dst_volume: str,
    *,
    remove_dst_contents: bool,
) -> None:
    """Copy all data from src volume to dst volume using a short-lived helper container."""
    helper_image = "alpine:3.20"
    try:
        client.images.get(helper_image)
    except docker.errors.ImageNotFound:
        try:
            client.images.pull(helper_image)
        except DockerException as exc:
            raise HTTPException(status_code=502, detail=f"docker_image_pull_failed: {exc}")
    except DockerException as exc:
        raise HTTPException(status_code=503, detail=f"docker_image_check_failed: {exc}")

    # Ensure both volumes exist.
    try:
        client.volumes.get(src_volume)
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"docker_volume_not_found: {src_volume}")
    except DockerException as exc:
        raise HTTPException(status_code=502, detail=f"docker_volume_get_failed: {exc}")

    try:
        client.volumes.get(dst_volume)
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"docker_volume_not_found: {dst_volume}")
    except DockerException as exc:
        raise HTTPException(status_code=502, detail=f"docker_volume_get_failed: {exc}")

    rm_dst = ""
    if remove_dst_contents:
        rm_dst = "rm -rf /dst/* /dst/.[!.]* /dst/..?* 2>/dev/null || true; "

    cmd = f"sh -lc '{rm_dst}mkdir -p /dst; cp -a /src/. /dst/ 2>/dev/null || cp -a /src/* /dst/; sync'"

    try:
        client.containers.run(
            image=helper_image,
            command=cmd,
            remove=True,
            detach=False,
            volumes={
                src_volume: {"bind": "/src", "mode": "ro"},
                dst_volume: {"bind": "/dst", "mode": "rw"},
            },
        )
    except DockerException as exc:
        raise HTTPException(status_code=502, detail=f"docker_volume_copy_failed: {exc}")


def require_admin(authorization: Optional[str]) -> None:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="Admin API disabled")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid admin token")
    provided = authorization.split(" ", 1)[1].strip()
    if provided != settings.admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")


class InvokePayload(BaseModel):
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


def _session_access_url(session_id: str) -> str:
    base = settings.public_base_url
    if not base.endswith("/"):
        base += "/"
    return f"{base}{session_id}/"


def _normalize_user_id(user_id: str) -> str:
    user_id = (user_id or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    return user_id


def _normalize_session_id(session_id: str) -> str:
    session_id = (session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    return session_id


def tool_definitions() -> List[Dict[str, Any]]:
    # Spec-first: schemas are intentionally permissive in v0.1.
    return [
        {"name": "health", "description": "Service health check", "input_schema": {"type": "object", "properties": {}}},
        {"name": "capabilities", "description": "Return server capability flags", "input_schema": {"type": "object", "properties": {}}},
        {"name": "list_users", "description": "List known webtop users", "input_schema": {"type": "object", "properties": {}}},
        {"name": "get_user", "description": "Get user defaults", "input_schema": {"type": "object", "properties": {"user_id": {"type": "string"}}, "required": ["user_id"]}},
        {"name": "upsert_user", "description": "Create/update user defaults (admin)", "input_schema": {"type": "object", "properties": {"user_id": {"type": "string"}, "config": {"type": "object"}}, "required": ["user_id", "config"]}},
        {"name": "list_sessions", "description": "List sessions", "input_schema": {"type": "object", "properties": {"filter": {"type": "object"}}}},
        {"name": "start_session", "description": "Start a new session", "input_schema": {"type": "object", "properties": {"user_id": {"type": "string"}, "options": {"type": "object"}}, "required": ["user_id"]}},
        {"name": "get_session", "description": "Get session details", "input_schema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}},
        {"name": "rename_session", "description": "Rename a session (admin)", "input_schema": {"type": "object", "properties": {"session_id": {"type": "string"}, "name": {"type": "string"}}, "required": ["session_id", "name"]}},
        {"name": "stop_session", "description": "Stop a session", "input_schema": {"type": "object", "properties": {"session_id": {"type": "string"}, "options": {"type": "object"}}, "required": ["session_id"]}},
        {"name": "delete_session", "description": "Delete a session (admin)", "input_schema": {"type": "object", "properties": {"session_id": {"type": "string"}, "options": {"type": "object"}}, "required": ["session_id"]}},
        {"name": "reap_expired_sessions", "description": "Stop/delete expired sessions (admin)", "input_schema": {"type": "object", "properties": {"dry_run": {"type": "boolean"}}}},
        {"name": "list_snapshots", "description": "List snapshots for user", "input_schema": {"type": "object", "properties": {"user_id": {"type": "string"}}, "required": ["user_id"]}},
        {"name": "create_snapshot", "description": "Create snapshot from session", "input_schema": {"type": "object", "properties": {"session_id": {"type": "string"}, "options": {"type": "object"}}, "required": ["session_id"]}},
        {"name": "get_snapshot", "description": "Get snapshot metadata", "input_schema": {"type": "object", "properties": {"snapshot_id": {"type": "string"}}, "required": ["snapshot_id"]}},
        {"name": "restore_snapshot", "description": "Restore snapshot into a new session", "input_schema": {"type": "object", "properties": {"user_id": {"type": "string"}, "snapshot_id": {"type": "string"}, "options": {"type": "object"}}, "required": ["user_id", "snapshot_id"]}},
        {"name": "promote_snapshot", "description": "Promote snapshot to a tag", "input_schema": {"type": "object", "properties": {"user_id": {"type": "string"}, "snapshot_id": {"type": "string"}, "tag": {"type": "string"}}, "required": ["user_id", "snapshot_id"]}},
        {"name": "delete_snapshot", "description": "Delete snapshot (admin)", "input_schema": {"type": "object", "properties": {"snapshot_id": {"type": "string"}}, "required": ["snapshot_id"]}},
        {"name": "export_snapshot", "description": "Export snapshot artifact (admin)", "input_schema": {"type": "object", "properties": {"snapshot_id": {"type": "string"}, "destination": {"type": "object"}}, "required": ["snapshot_id", "destination"]}},
        {"name": "import_snapshot", "description": "Import snapshot artifact (admin)", "input_schema": {"type": "object", "properties": {"user_id": {"type": "string"}, "source": {"type": "object"}}, "required": ["user_id", "source"]}},
        {"name": "get_logs", "description": "Get session logs (admin)", "input_schema": {"type": "object", "properties": {"session_id": {"type": "string"}, "options": {"type": "object"}}, "required": ["session_id"]}},
        {"name": "exec", "description": "Execute command in session (admin)", "input_schema": {"type": "object", "properties": {"session_id": {"type": "string"}, "command": {"type": "string"}, "options": {"type": "object"}}, "required": ["session_id", "command"]}},
        {"name": "get_routes", "description": "List router mappings", "input_schema": {"type": "object", "properties": {}}},
    ]


ADMIN_ONLY_TOOLS = {
    "upsert_user",
    "rename_session",
    "delete_session",
    "reap_expired_sessions",
    "delete_snapshot",
    "export_snapshot",
    "import_snapshot",
    "get_logs",
    "exec",
}


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "name": settings.app_name,
        "backend": settings.backend,
        "router_base_url": settings.router_base_url,
        "state_file": str(_state_file()),
    }


@app.get("/tools")
async def tools() -> Dict[str, Any]:
    return {"tools": tool_definitions()}


@app.get("/.well-known/mcp.json")
async def well_known_manifest() -> Dict[str, Any]:
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "description": "Webtops session/snapshot manager (spec-first skeleton)",
        "capabilities": {
            "tools": tool_definitions(),
        },
    }


@app.post("/invoke")
async def invoke(payload: InvokePayload = Body(...), authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    tool = payload.tool
    args = payload.arguments or {}

    if tool in ADMIN_ONLY_TOOLS:
        require_admin(authorization)

    if tool == "health":
        result = await health()
        return {"tool": tool, "result": result}

    if tool == "capabilities":
        return {
            "tool": tool,
            "result": {
                "url_mode": "path_routed",
                "supports_snapshots": True,
                "supports_backup_transfer": True,
                "supports_exec": True,
                "security": {"admin_token": bool(settings.admin_token)},
            },
        }

    if tool == "list_users":
        users = STATE.get("users") or {}
        return {"tool": tool, "result": {"users": sorted(users.keys())}}

    if tool == "get_user":
        user_id = _normalize_user_id(args.get("user_id"))
        users = STATE.get("users") or {}
        return {"tool": tool, "result": {"user_id": user_id, "config": users.get(user_id) or {}}}

    if tool == "upsert_user":
        user_id = _normalize_user_id(args.get("user_id"))
        config = args.get("config") or {}
        if not isinstance(config, dict):
            raise HTTPException(status_code=400, detail="config must be an object")
        users = STATE.setdefault("users", {})
        users[user_id] = config
        _save_state(STATE)
        return {"tool": tool, "result": {"ok": True, "user_id": user_id, "config": config}}

    if tool == "list_sessions":
        sessions = STATE.get("sessions") or {}
        flt = args.get("filter") or {}
        if flt and not isinstance(flt, dict):
            raise HTTPException(status_code=400, detail="filter must be an object")
        user_filter = (flt.get("user_id") if isinstance(flt, dict) else None) or None
        status_filter = (flt.get("status") if isinstance(flt, dict) else None) or None
        active_only = bool(flt.get("active_only")) if isinstance(flt, dict) else False

        out: List[Dict[str, Any]] = []
        changed = False
        for s in sessions.values():
            if not isinstance(s, dict):
                continue
            if not s.get("name"):
                sid = (s.get("session_id") or "").strip()
                if sid:
                    s["name"] = sid
                    changed = True
            if user_filter and s.get("user_id") != user_filter:
                continue
            if status_filter and s.get("status") != status_filter:
                continue
            if active_only and s.get("status") not in ("running", "starting"):
                continue
            out.append(s)
        out.sort(key=lambda x: x.get("created_at", ""))
        if changed:
            _save_state(STATE)
        return {"tool": tool, "result": {"sessions": out}}

    if tool == "get_session":
        session_id = _normalize_session_id(args.get("session_id"))
        sessions = STATE.get("sessions") or {}
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="session_not_found")
        return {"tool": tool, "result": session}

    if tool == "rename_session":
        session_id = _normalize_session_id(args.get("session_id"))
        name = args.get("name")
        if not isinstance(name, str):
            raise HTTPException(status_code=400, detail="name must be a string")
        name = name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        if len(name) > 200:
            raise HTTPException(status_code=400, detail="name too long")

        sessions = STATE.get("sessions") or {}
        session = sessions.get(session_id)
        if not isinstance(session, dict):
            raise HTTPException(status_code=404, detail="session_not_found")

        session["name"] = name
        _save_state(STATE)
        return {"tool": tool, "result": session}

    if tool == "create_snapshot":
        session_id = _normalize_session_id(args.get("session_id"))
        options = args.get("options") or {}
        if options and not isinstance(options, dict):
            raise HTTPException(status_code=400, detail="options must be an object")

        sessions = STATE.get("sessions") or {}
        session = sessions.get(session_id)
        if not isinstance(session, dict):
            raise HTTPException(status_code=404, detail="session_not_found")

        backend = session.get("backend") if isinstance(session, dict) else None
        if not isinstance(backend, dict) or not backend.get("volume_id"):
            raise HTTPException(status_code=400, detail="session_missing_volume")

        src_volume_id = str(backend.get("volume_id"))
        user_id = str(session.get("user_id") or "")
        if not user_id:
            raise HTTPException(status_code=400, detail="session_missing_user_id")

        snapshot_id = "snap_" + uuid4().hex[:12]
        snapshot_volume = f"webtops_snap_{snapshot_id}"
        created_at = _now()

        client = _docker_client()
        try:
            client.volumes.create(
                name=snapshot_volume,
                labels={
                    "webtops.snapshot_id": snapshot_id,
                    "webtops.user_id": user_id,
                    "webtops.source_session_id": session_id,
                    "webtops.managed_by": "mcp-webtops",
                },
            )
        except DockerException as exc:
            raise HTTPException(status_code=502, detail=f"docker_volume_create_failed: {exc}")

        try:
            _copy_docker_volume(client, src_volume_id, snapshot_volume, remove_dst_contents=True)
        except Exception:
            with contextlib.suppress(Exception):
                client.volumes.get(snapshot_volume).remove(force=True)
            raise

        snap = {
            "snapshot_id": snapshot_id,
            "user_id": user_id,
            "created_at": _iso(created_at),
            "source_session_id": session_id,
            "profile": session.get("profile") or "default",
            "backend": {"type": "docker", "volume_id": snapshot_volume},
        }
        STATE.setdefault("snapshots", {})[snapshot_id] = snap
        _save_state(STATE)
        return {"tool": tool, "result": snap}

    if tool == "restore_snapshot":
        user_id = _normalize_user_id(args.get("user_id"))
        snapshot_id = (args.get("snapshot_id") or "").strip()
        if not snapshot_id:
            raise HTTPException(status_code=400, detail="snapshot_id is required")
        options = args.get("options") or {}
        if options and not isinstance(options, dict):
            raise HTTPException(status_code=400, detail="options must be an object")

        snapshots = STATE.get("snapshots") or {}
        snap = snapshots.get(snapshot_id)
        if not isinstance(snap, dict):
            raise HTTPException(status_code=404, detail="snapshot_not_found")

        if snap.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="snapshot_user_mismatch")

        snap_backend = snap.get("backend")
        if not isinstance(snap_backend, dict) or not snap_backend.get("volume_id"):
            raise HTTPException(status_code=400, detail="snapshot_missing_volume")
        snapshot_volume = str(snap_backend.get("volume_id"))

        profile = _normalize_profile(options.get("profile") or snap.get("profile") or "default")

        # Create a fresh session volume first, seed it from snapshot, then start container.
        if settings.backend != "docker":
            raise HTTPException(status_code=501, detail=f"backend_not_supported: {settings.backend}")

        client = _docker_client()
        resolved_network = _resolve_network_name(client, settings.docker_network)

        session_id = "sess_" + uuid4().hex[:12]
        created_at = _now()

        ttl_minutes = options.get("ttl_minutes")
        expires_at = None
        if ttl_minutes is not None:
            try:
                ttl = float(ttl_minutes)
            except Exception:
                raise HTTPException(status_code=400, detail="ttl_minutes must be a number")
            expires_at = created_at + timedelta(minutes=ttl)

        session_image = settings.session_image
        extra_env: Dict[str, str] = {}
        shared_windsurf_cache_volume = None
        if profile == "windsurf":
            if not settings.session_image_windsurf:
                raise HTTPException(status_code=503, detail="windsurf_profile_missing_image (WEBTOPS_SESSION_IMAGE_WINDSURF)")
            if not settings.windsurf_version:
                raise HTTPException(status_code=503, detail="windsurf_profile_missing_version (WEBTOPS_WINDSURF_VERSION)")
            session_image = settings.session_image_windsurf
            extra_env["WINDSURF_VERSION"] = settings.windsurf_version
            extra_env["WINDSURF_INSTALL_MODE"] = (settings.windsurf_install_mode or "deb_extract").strip().lower()
            if extra_env["WINDSURF_INSTALL_MODE"] == "deb_extract":
                if not settings.windsurf_deb_url_template:
                    raise HTTPException(status_code=503, detail="windsurf_profile_missing_deb_url_template (WEBTOPS_WINDSURF_DEB_URL_TEMPLATE)")
                extra_env["WINDSURF_DEB_URL_TEMPLATE"] = settings.windsurf_deb_url_template
            else:
                if not settings.windsurf_download_url_template:
                    raise HTTPException(status_code=503, detail="windsurf_profile_missing_download_url_template (WEBTOPS_WINDSURF_DOWNLOAD_URL_TEMPLATE)")
                extra_env["WINDSURF_DOWNLOAD_URL_TEMPLATE"] = settings.windsurf_download_url_template

            if settings.windsurf_cache_volume and settings.windsurf_cache_mount_path:
                extra_env["WINDSURF_CACHE_ROOT"] = settings.windsurf_cache_mount_path
                try:
                    shared_windsurf_cache_volume = client.volumes.get(settings.windsurf_cache_volume)
                except docker.errors.NotFound:
                    try:
                        shared_windsurf_cache_volume = client.volumes.create(name=settings.windsurf_cache_volume)
                    except DockerException as exc:
                        raise HTTPException(status_code=502, detail=f"docker_volume_create_failed: {exc}")
                except DockerException as exc:
                    raise HTTPException(status_code=502, detail=f"docker_volume_get_failed: {exc}")

        _ensure_image(client, session_image)

        container_name = f"{settings.session_container_name_prefix}-{session_id}"
        volume_name = f"{settings.session_volume_name_prefix}_{session_id}"

        try:
            client.volumes.create(name=volume_name, labels={"webtops.session_id": session_id, "webtops.user_id": user_id})
        except DockerException as exc:
            raise HTTPException(status_code=502, detail=f"docker_volume_create_failed: {exc}")

        # Seed the new volume from the snapshot.
        _copy_docker_volume(client, snapshot_volume, volume_name, remove_dst_contents=True)

        env = _build_linuxserver_env()
        env.update(extra_env)
        container_volumes: Dict[str, Dict[str, str]] = {
            volume_name: {"bind": settings.session_mount_path, "mode": "rw"},
        }
        if shared_windsurf_cache_volume is not None:
            container_volumes[shared_windsurf_cache_volume.name] = {"bind": settings.windsurf_cache_mount_path, "mode": "rw"}
        _maybe_add_workspaces(client, env, container_volumes)

        try:
            container = client.containers.run(
                image=session_image,
                name=container_name,
                detach=True,
                network=resolved_network,
                environment=env,
                labels={
                    "webtops.session_id": session_id,
                    "webtops.user_id": user_id,
                    "webtops.managed_by": "mcp-webtops",
                    "webtops.restored_from_snapshot": snapshot_id,
                },
                volumes=container_volumes,
            )
        except DockerException as exc:
            with contextlib.suppress(Exception):
                client.volumes.get(volume_name).remove(force=True)
            raise HTTPException(status_code=502, detail=f"docker_container_create_failed: {exc}")

        container_id = container.id
        upstream = _make_upstream(container_name)
        await _router_put(session_id, upstream)

        session = {
            "session_id": session_id,
            "user_id": user_id,
            "profile": profile,
            "status": "running",
            "name": session_id,
            "created_at": _iso(created_at),
            "expires_at": _iso(expires_at) if expires_at else None,
            "access_url": _session_access_url(session_id),
            "backend": {
                "type": settings.backend,
                "container_id": container_id,
                "volume_id": volume_name,
                "ports": None,
            },
            "route": {
                "base_path": settings.base_path.rstrip("/") + f"/{session_id}/",
                "router_type": "router_service",
                "upstream": upstream,
            },
            "last_error": None,
            "restored_from_snapshot": snapshot_id,
        }

        STATE.setdefault("sessions", {})[session_id] = session
        _save_state(STATE)
        return {"tool": tool, "result": session}

    if tool == "delete_snapshot":
        snapshot_id = (args.get("snapshot_id") or "").strip()
        if not snapshot_id:
            raise HTTPException(status_code=400, detail="snapshot_id is required")
        snapshots = STATE.get("snapshots") or {}
        snap = snapshots.get(snapshot_id)
        if not isinstance(snap, dict):
            return {"tool": tool, "result": {"ok": True, "snapshot_id": snapshot_id}}

        backend = snap.get("backend")
        volume_id = backend.get("volume_id") if isinstance(backend, dict) else None

        removed: Dict[str, Any] = {"volume": False}
        if volume_id:
            client = _docker_client()
            try:
                client.volumes.get(str(volume_id)).remove(force=True)
                removed["volume"] = True
            except docker.errors.NotFound:
                removed["volume"] = True
            except DockerException as exc:
                removed["volume_error"] = str(exc)

        snapshots.pop(snapshot_id, None)
        _save_state(STATE)
        return {"tool": tool, "result": {"ok": True, "snapshot_id": snapshot_id, "removed": removed}}

    if tool == "start_session":
        user_id = _normalize_user_id(args.get("user_id"))
        options = args.get("options") or {}
        if options and not isinstance(options, dict):
            raise HTTPException(status_code=400, detail="options must be an object")

        profile = _normalize_profile(options.get("profile"))

        session_id = "sess_" + uuid4().hex[:12]
        created_at = _now()
        ttl_minutes = options.get("ttl_minutes")
        expires_at = None
        if ttl_minutes is not None:
            try:
                ttl = float(ttl_minutes)
            except Exception:
                raise HTTPException(status_code=400, detail="ttl_minutes must be a number")
            expires_at = created_at + timedelta(minutes=ttl)

        # If caller provides an upstream, treat this as a "virtual" session.
        upstream = options.get("upstream")
        container_id = None
        volume_name = None

        if upstream is not None:
            if not isinstance(upstream, str):
                raise HTTPException(status_code=400, detail="options.upstream must be a string")
        else:
            # Real webtop session: create container + per-session volume.
            if settings.backend != "docker":
                raise HTTPException(status_code=501, detail=f"backend_not_supported: {settings.backend}")

            client = _docker_client()
            resolved_network = _resolve_network_name(client, settings.docker_network)

            session_image = settings.session_image
            extra_env: Dict[str, str] = {}
            shared_windsurf_cache_volume = None
            if profile == "windsurf":
                if not settings.session_image_windsurf:
                    raise HTTPException(status_code=503, detail="windsurf_profile_missing_image (WEBTOPS_SESSION_IMAGE_WINDSURF)")
                if not settings.windsurf_version:
                    raise HTTPException(status_code=503, detail="windsurf_profile_missing_version (WEBTOPS_WINDSURF_VERSION)")
                session_image = settings.session_image_windsurf
                extra_env["WINDSURF_VERSION"] = settings.windsurf_version

                # Runtime installer can use either apt (preferred) or AppImage.
                extra_env["WINDSURF_INSTALL_MODE"] = (settings.windsurf_install_mode or "deb_extract").strip().lower()
                if extra_env["WINDSURF_INSTALL_MODE"] == "deb_extract":
                    if not settings.windsurf_deb_url_template:
                        raise HTTPException(status_code=503, detail="windsurf_profile_missing_deb_url_template (WEBTOPS_WINDSURF_DEB_URL_TEMPLATE)")
                    extra_env["WINDSURF_DEB_URL_TEMPLATE"] = settings.windsurf_deb_url_template
                else:
                    if not settings.windsurf_download_url_template:
                        raise HTTPException(status_code=503, detail="windsurf_profile_missing_download_url_template (WEBTOPS_WINDSURF_DOWNLOAD_URL_TEMPLATE)")
                    extra_env["WINDSURF_DOWNLOAD_URL_TEMPLATE"] = settings.windsurf_download_url_template

                if settings.windsurf_cache_volume and settings.windsurf_cache_mount_path:
                    extra_env["WINDSURF_CACHE_ROOT"] = settings.windsurf_cache_mount_path
                    try:
                        shared_windsurf_cache_volume = client.volumes.get(settings.windsurf_cache_volume)
                    except docker.errors.NotFound:
                        try:
                            shared_windsurf_cache_volume = client.volumes.create(name=settings.windsurf_cache_volume)
                        except DockerException as exc:
                            raise HTTPException(status_code=502, detail=f"docker_volume_create_failed: {exc}")
                    except DockerException as exc:
                        raise HTTPException(status_code=502, detail=f"docker_volume_get_failed: {exc}")

            _ensure_image(client, session_image)

            container_name = f"{settings.session_container_name_prefix}-{session_id}"
            volume_name = f"{settings.session_volume_name_prefix}_{session_id}"

            try:
                volume = client.volumes.create(name=volume_name, labels={"webtops.session_id": session_id, "webtops.user_id": user_id})
            except DockerException as exc:
                raise HTTPException(status_code=502, detail=f"docker_volume_create_failed: {exc}")

            env = _build_linuxserver_env()
            env.update(extra_env)
            container_volumes: Dict[str, Dict[str, str]] = {
                volume.name: {"bind": settings.session_mount_path, "mode": "rw"},
            }
            if shared_windsurf_cache_volume is not None:
                container_volumes[shared_windsurf_cache_volume.name] = {"bind": settings.windsurf_cache_mount_path, "mode": "rw"}
            _maybe_add_workspaces(client, env, container_volumes)
            # Allow options.env as a safe extension point later.

            try:
                container = client.containers.run(
                    image=session_image,
                    name=container_name,
                    detach=True,
                    network=resolved_network,
                    environment=env,
                    labels={
                        "webtops.session_id": session_id,
                        "webtops.user_id": user_id,
                        "webtops.managed_by": "mcp-webtops",
                    },
                    volumes=container_volumes,
                )
            except DockerException as exc:
                with contextlib.suppress(Exception):
                    volume.remove(force=True)
                raise HTTPException(status_code=502, detail=f"docker_container_create_failed: {exc}")

            container_id = container.id
            upstream = _make_upstream(container_name)

        await _router_put(session_id, upstream)

        session = {
            "session_id": session_id,
            "user_id": user_id,
            "profile": profile,
            "status": "running",
            "created_at": _iso(created_at),
            "expires_at": _iso(expires_at) if expires_at else None,
            "access_url": _session_access_url(session_id),
            "backend": {
                "type": settings.backend,
                "container_id": container_id,
                "volume_id": volume_name,
                "ports": None,
            },
            "route": {
                "base_path": settings.base_path.rstrip("/") + f"/{session_id}/",
                "router_type": "router_service",
                "upstream": upstream,
            },
            "last_error": None,
        }

        STATE.setdefault("sessions", {})[session_id] = session
        _save_state(STATE)

        return {"tool": tool, "result": session}

    if tool == "stop_session":
        session_id = _normalize_session_id(args.get("session_id"))
        sessions = STATE.get("sessions") or {}
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="session_not_found")
        session["status"] = "stopped"
        await _router_delete(session_id)
        _save_state(STATE)
        return {"tool": tool, "result": {"ok": True, "session_id": session_id}}

    if tool == "extend_session_ttl":
        session_id = _normalize_session_id(args.get("session_id"))
        ttl_minutes = args.get("ttl_minutes")
        try:
            ttl = float(ttl_minutes)
        except Exception:
            raise HTTPException(status_code=400, detail="ttl_minutes must be a number")
        sessions = STATE.get("sessions") or {}
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="session_not_found")
        expires_at = _now() + timedelta(minutes=ttl)
        session["expires_at"] = _iso(expires_at)
        _save_state(STATE)
        return {"tool": tool, "result": {"ok": True, "session_id": session_id, "expires_at": session["expires_at"]}}

    if tool == "delete_session":
        session_id = _normalize_session_id(args.get("session_id"))
        sessions = STATE.get("sessions") or {}
        session = sessions.get(session_id)
        if not session:
            return {"tool": tool, "result": {"ok": True, "session_id": session_id}}

        # Best-effort router deregistration first so the path stops working immediately.
        with contextlib.suppress(Exception):
            await _router_delete(session_id)

        backend = session.get("backend") if isinstance(session, dict) else None
        container_id = None
        volume_id = None
        if isinstance(backend, dict):
            container_id = backend.get("container_id")
            volume_id = backend.get("volume_id")

        removed: Dict[str, Any] = {"router": True, "container": False, "volume": False}

        if container_id or volume_id:
            client = _docker_client()

            if container_id:
                try:
                    client.containers.get(container_id).remove(force=True)
                    removed["container"] = True
                except docker.errors.NotFound:
                    removed["container"] = True
                except DockerException as exc:
                    # Keep going; we still want to remove the mapping + state.
                    removed["container_error"] = str(exc)

            if volume_id:
                try:
                    client.volumes.get(volume_id).remove(force=True)
                    removed["volume"] = True
                except docker.errors.NotFound:
                    removed["volume"] = True
                except DockerException as exc:
                    removed["volume_error"] = str(exc)

        sessions.pop(session_id, None)
        _save_state(STATE)
        return {"tool": tool, "result": {"ok": True, "session_id": session_id, "removed": removed}}

    if tool == "get_routes":
        routes = await _router_list()
        return {"tool": tool, "result": routes}

    if tool == "list_snapshots":
        user_id = _normalize_user_id(args.get("user_id"))
        snapshots = STATE.get("snapshots") or {}
        out = [s for s in snapshots.values() if isinstance(s, dict) and s.get("user_id") == user_id]
        out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return {"tool": tool, "result": {"snapshots": out}}

    if tool == "get_snapshot":
        snapshot_id = (args.get("snapshot_id") or "").strip()
        if not snapshot_id:
            raise HTTPException(status_code=400, detail="snapshot_id is required")
        snapshots = STATE.get("snapshots") or {}
        snap = snapshots.get(snapshot_id)
        if not snap:
            raise HTTPException(status_code=404, detail="snapshot_not_found")
        return {"tool": tool, "result": snap}

    # Spec-first skeleton: return a structured placeholder for every other tool.
    return {
        "tool": tool,
        "result": {
            "status": "not_implemented",
            "echo": args,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
