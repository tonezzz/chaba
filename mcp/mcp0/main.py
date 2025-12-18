from __future__ import annotations

import asyncio
import html
from contextlib import asynccontextmanager
import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, RootModel
import docker
from docker.errors import DockerException, NotFound as DockerNotFound

from registry import ProviderRegistry
from schemas import AggregatedHealth, ProviderDescriptor, ProviderInfo, ProxyResponse
from settings import Settings, get_settings
from tool_loader import ToolSourceError, load_tools_from_source

logger = logging.getLogger(__name__)

settings = get_settings()

if settings.admin_token:
    logger.info("Admin API enabled")
else:
    logger.warning("Admin API disabled (missing MCP0_ADMIN_TOKEN)")

auth_headers: Dict[str, Dict[str, str]] = {}
github_bearer = settings.github_personal_token or settings.github_token
if github_bearer:
    auth_headers["github"] = {"Authorization": f"Bearer {github_bearer}"}

registry = ProviderRegistry.from_env(settings.provider_list, auth_headers=auth_headers or None)


def _apply_dynamic_github_tools() -> None:
    if not settings.enable_dynamic_github_tools:
        return
    if not settings.github_tool_source:
        logger.warning(
            "MCP0_ENABLE_DYNAMIC_GITHUB_TOOLS is true but GITHUB_MCP_TOOLS is unset; skipping dynamic load"
        )
        return

    descriptor = registry.get_descriptor("githubModel")
    if not descriptor:
        logger.warning("Dynamic GitHub tools enabled, but provider 'githubModel' not found")
        return

    try:
        result = load_tools_from_source(settings.github_tool_source)
    except ToolSourceError as exc:
        logger.warning("Failed to load dynamic GitHub tools: %s", exc)
        return

    descriptor.default_tools = result.tools
    logger.info("Loaded %d GitHub MCP tools from %s", len(result.tools), result.source)


_apply_dynamic_github_tools()


@asynccontextmanager
async def app_lifespan(_app: FastAPI):  # noqa: D401
    """FastAPI lifespan handler to warm caches before serving traffic."""

    await asyncio.gather(
        registry.collect_health(),
        registry.refresh_capabilities(),
    )
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=app_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


def get_registry() -> ProviderRegistry:
    return registry


def get_timeout() -> float:
    return settings.request_timeout


def require_admin(authorization: Optional[str] = Header(default=None)) -> None:
    if not settings.admin_token:
        logger.warning("require_admin: admin token unset; rejecting request")
        raise HTTPException(status_code=503, detail="Admin API disabled")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid admin token")
    provided = authorization.split(" ", 1)[1].strip()
    if provided != settings.admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")


class ProviderRegistration(BaseModel):
    descriptor: ProviderDescriptor
    headers: Optional[Dict[str, str]] = None


# --- MCP native endpoints ---

@app.get("/.well-known/mcp.json")
async def mcp_manifest() -> JSONResponse:
    manifest = {
        "name": settings.app_name,
        "version": "0.1.0",
        "endpoints": {
            "messages": "/mcp/messages",
        },
        "provider": "github-models",
    }
    return JSONResponse(content=manifest)


class MCPMessage(BaseModel):
    role: str
    content: str


class MCPMessagesRequest(BaseModel):
    model: str
    messages: List[MCPMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


def _github_models_headers() -> Dict[str, str]:
    token = settings.effective_github_token
    if not token:
        raise HTTPException(status_code=503, detail="GitHub token not configured")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


@app.post("/mcp/messages", response_model=None)
async def mcp_messages(
    body: MCPMessagesRequest,
    timeout: float = Depends(get_timeout),
):
    api_base = settings.github_models_api_base.rstrip("/")
    url = f"{api_base}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model": body.model or settings.github_model,
        "messages": [m.model_dump() for m in body.messages],
    }
    if body.temperature is not None:
        payload["temperature"] = body.temperature
    if body.max_tokens is not None:
        payload["max_tokens"] = body.max_tokens

    headers = _github_models_headers()

    # Streaming response
    if body.stream:
        payload["stream"] = True
        client = httpx.AsyncClient(timeout=timeout)
        try:
            resp = await client.stream("POST", url, json=payload, headers=headers)
        except httpx.RequestError as exc:  # noqa: BLE001
            await client.aclose()
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        async def event_iterator():
            try:
                async for line in resp.aiter_lines():
                    # pass-through SSE (already in data: ... format from provider)
                    if not line:
                        yield "\n"
                    else:
                        yield f"{line}\n"
            finally:
                await client.aclose()

        return StreamingResponse(event_iterator(), media_type="text/event-stream")

    # Non-streaming response
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    content_type = r.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = r.json()
        except ValueError:
            data = r.text
    else:
        data = r.text
    return JSONResponse(status_code=r.status_code, content=data)


# --- Docker tool endpoints (integrated in mcp0) ---

class DockerPortMap(RootModel[Dict[str, str]]):
    # host_port: container_port (both as strings like "8080" or "8080/tcp")
    pass


class DockerEnvMap(RootModel[Dict[str, str]]):
    pass


class CreateContainerRequest(BaseModel):
    image: str
    name: Optional[str] = None
    command: Optional[str] = None
    ports: Optional[DockerPortMap] = None
    environment: Optional[DockerEnvMap] = None
    detach: bool = True


def _docker_client():
    try:
        return docker.from_env()
    except DockerException as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


@app.get("/mcp/tools/docker/list-containers")
async def docker_list_containers(all: bool = False) -> List[Dict[str, Any]]:  # noqa: A002
    client = _docker_client()
    try:
        containers = client.containers.list(all=all)
    except DockerException as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result: List[Dict[str, Any]] = []
    for c in containers:
        result.append(
            {
                "id": c.id,
                "name": c.name,
                "status": c.status,
                "image": getattr(c.image, "tags", None) or str(c.image),
            }
        )
    return result


@app.get("/mcp/tools/docker/get-logs/{container}")
async def docker_get_logs(container: str, tail: Optional[int] = 200) -> Dict[str, Any]:
    client = _docker_client()
    try:
        obj = client.containers.get(container)
        logs = obj.logs(tail=tail).decode("utf-8", errors="replace")
    except DockerNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DockerException as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"container": container, "logs": logs}


@app.post("/mcp/tools/docker/create-container")
async def docker_create_container(req: CreateContainerRequest) -> Dict[str, Any]:
    client = _docker_client()
    ports = None
    if req.ports and req.ports.root:
        # Convert host->container mapping into docker-py format {container_port: host_port}
        ports = {}
        for host, container in req.ports.root.items():
            ports[str(container)] = str(host)
    environment = req.environment.root if req.environment and req.environment.root else None
    try:
        image = req.image
        # Ensure image is available
        try:
            client.images.get(image)
        except DockerNotFound:
            client.images.pull(image)
        container = client.containers.run(
            image,
            name=req.name,
            command=req.command,
            detach=req.detach,
            ports=ports,
            environment=environment,
        )
    except DockerException as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"id": container.id, "name": container.name, "status": container.status}

@app.get("/health", response_model=AggregatedHealth)
async def service_health(registry: ProviderRegistry = Depends(get_registry)) -> AggregatedHealth:
    return await registry.collect_health()


@app.get("/providers", response_model=List[ProviderInfo])
async def list_providers(refresh: bool = False, registry: ProviderRegistry = Depends(get_registry)) -> List[ProviderInfo]:
    if refresh:
        await registry.refresh_capabilities()
    return registry.list_providers()


@app.get("/www/providers", response_class=HTMLResponse)
async def providers_dashboard(
    refresh: bool = False,
    registry: ProviderRegistry = Depends(get_registry),
) -> str:
    if refresh:
        await registry.refresh_capabilities()
    providers = registry.list_providers()

    if providers:
        rows = []
        for info in sorted(providers, key=lambda item: item.name.lower()):
            default_tools = ", ".join(info.default_tools) if info.default_tools else "—"
            health_status = "unknown"
            health_title = ""
            latency = ""
            if info.health:
                health_status = info.health.status
                if info.health.detail is not None:
                    health_title = html.escape(str(info.health.detail), quote=True)
                if info.health.latency_ms is not None:
                    latency = f"{info.health.latency_ms} ms"
            capabilities_updated = (
                info.capabilities_updated_at.isoformat() if info.capabilities_updated_at else "—"
            )
            rows.append(
                (
                    "<tr>"
                    f"<td>{html.escape(info.name)}</td>"
                    f"<td><a href=\"{html.escape(info.base_url)}\" target=\"_blank\" rel=\"noopener\">"
                    f"{html.escape(info.base_url)}</a></td>"
                    f"<td title=\"{health_title}\">{html.escape(health_status)}"
                    f"{f' · {latency}' if latency else ''}</td>"
                    f"<td>{html.escape(info.capabilities_path or '—')}</td>"
                    f"<td>{html.escape(default_tools)}</td>"
                    f"<td>{html.escape(capabilities_updated)}</td>"
                    "</tr>"
                )
            )
        table_body = "\n".join(rows)
    else:
        table_body = (
            "<tr><td colspan=\"6\" style=\"text-align:center; padding:1rem;\">"
            "No providers registered</td></tr>"
        )

    return f"""
    <!DOCTYPE html>
    <html lang="en">
        <head>
            <meta charset="utf-8" />
            <title>MCP Providers</title>
            <style>
                body {{
                    font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
                    background: #0f1115;
                    color: #e5e7eb;
                    margin: 0;
                    padding: 2rem;
                }}
                h1 {{
                    margin-top: 0;
                    font-size: 1.8rem;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 1.5rem;
                    background: #151922;
                    border: 1px solid #262b36;
                }}
                th, td {{
                    padding: 0.65rem 0.75rem;
                    border-bottom: 1px solid #1f2430;
                    text-align: left;
                }}
                th {{
                    background: #1d2431;
                    font-size: 0.85rem;
                    text-transform: uppercase;
                    letter-spacing: 0.05em;
                    color: #9ca3af;
                }}
                tr:hover td {{
                    background: #1c2230;
                }}
                a {{
                    color: #7dd3fc;
                    text-decoration: none;
                }}
                a:hover {{
                    text-decoration: underline;
                }}
                .toolbar {{
                    display: flex;
                    gap: 0.5rem;
                }}
                .button {{
                    background: #2563eb;
                    color: white;
                    border: none;
                    border-radius: 999px;
                    padding: 0.4rem 1rem;
                    font-size: 0.9rem;
                    cursor: pointer;
                    text-decoration: none;
                }}
                .button.secondary {{
                    background: #374151;
                }}
            </style>
        </head>
        <body>
            <div class="toolbar">
                <h1 style="flex:1;">Registered MCP Providers ({len(providers)})</h1>
                <a class="button secondary" href="/providers">JSON</a>
                <a class="button" href="/www/providers?refresh=true">Refresh</a>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Base URL</th>
                        <th>Health</th>
                        <th>Capabilities Path</th>
                        <th>Default Tools</th>
                        <th>Capabilities Updated</th>
                    </tr>
                </thead>
                <tbody>
                    {table_body}
                </tbody>
            </table>
        </body>
    </html>
    """


async def _proxy_request(
    provider: str,
    relative_path: str,
    payload: Dict[str, Any],
    registry: ProviderRegistry,
    timeout: float,
) -> ProxyResponse:
    descriptor = registry.get_descriptor(provider)
    if not descriptor:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")

    target_url = registry.build_target_url(descriptor, relative_path)
    extra_headers: Dict[str, str] = {}
    if descriptor.name.lower() == "github" and settings.github_token:
        extra_headers["Authorization"] = f"Bearer {settings.github_token}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(target_url, json=payload, headers=extra_headers or None)
        except httpx.RequestError as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    parsed_response: Any
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            parsed_response = response.json()
        except ValueError:
            parsed_response = response.text
    else:
        parsed_response = response.text

    return ProxyResponse(
        provider=provider,
        target_url=target_url,
        status_code=response.status_code,
        response=parsed_response,
    )


@app.post("/proxy/{provider}", response_model=ProxyResponse)
async def proxy_root(
    provider: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    registry: ProviderRegistry = Depends(get_registry),
    timeout: float = Depends(get_timeout),
) -> ProxyResponse:
    return await _proxy_request(provider, "", payload, registry, timeout)


@app.post("/proxy/{provider}/{relative_path:path}", response_model=ProxyResponse)
async def proxy_path(
    provider: str,
    relative_path: str = Path(..., description="Path relative to the provider base URL"),
    payload: Dict[str, Any] = Body(default_factory=dict),
    registry: ProviderRegistry = Depends(get_registry),
    timeout: float = Depends(get_timeout),
) -> ProxyResponse:
    return await _proxy_request(provider, relative_path, payload, registry, timeout)


@app.post("/admin/providers", response_model=ProviderInfo)
async def register_provider(
    payload: ProviderRegistration,
    registry: ProviderRegistry = Depends(get_registry),
    _: None = Depends(require_admin),
) -> ProviderInfo:
    info = registry.upsert_provider(payload.descriptor, headers=payload.headers)
    await asyncio.gather(registry.collect_health(), registry.refresh_capabilities())
    return info


@app.delete("/admin/providers/{provider_name}")
async def remove_provider(
    provider_name: str,
    registry: ProviderRegistry = Depends(get_registry),
    _: None = Depends(require_admin),
) -> Dict[str, str]:
    removed = registry.remove_provider(provider_name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")
    return {"status": "removed", "provider": provider_name}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
