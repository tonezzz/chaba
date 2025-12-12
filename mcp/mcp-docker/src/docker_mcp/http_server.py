from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from python_on_whales import DockerException

from .handlers import DockerHandlers, docker_client

APP_NAME = "docker-mcp-http"
APP_VERSION = "0.1.0"
DEFAULT_PORT = int(os.environ.get("PORT", os.environ.get("MCP_DOCKER_PORT", "8340")))


def _tool_definitions() -> List[Dict[str, Any]]:
    """Describe the available tools for both /.well-known/mcp.json and /tools."""
    return [
        {
            "name": "create-container",
            "description": "Create a new standalone Docker container",
            "input_schema": {
                "type": "object",
                "properties": {
                    "image": {"type": "string"},
                    "name": {"type": "string"},
                    "ports": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Mapping of host_port (or host_port/protocol) to container_port",
                    },
                    "environment": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Environment variables for the container",
                    },
                },
                "required": ["image"],
            },
        },
        {
            "name": "deploy-compose",
            "description": "Deploy a Docker Compose stack",
            "input_schema": {
                "type": "object",
                "properties": {
                    "compose_yaml": {"type": "string"},
                    "project_name": {"type": "string"},
                },
                "required": ["compose_yaml", "project_name"],
            },
        },
        {
            "name": "get-logs",
            "description": "Retrieve logs for a specific Docker container",
            "input_schema": {
                "type": "object",
                "properties": {
                    "container_name": {"type": "string"},
                },
                "required": ["container_name"],
            },
        },
        {
            "name": "list-containers",
            "description": "List all Docker containers on the host",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "compose-control",
            "description": "Run arbitrary docker compose commands against an existing stack file",
            "input_schema": {
                "type": "object",
                "properties": {
                    "compose_path": {"type": "string"},
                    "project_name": {"type": "string"},
                    "command": {"type": "string"},
                    "flags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "services": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["compose_path", "project_name", "command"],
            },
        },
    ]


TOOL_DISPATCH = {
    "create-container": DockerHandlers.handle_create_container,
    "deploy-compose": DockerHandlers.handle_deploy_compose,
    "get-logs": DockerHandlers.handle_get_logs,
    "list-containers": DockerHandlers.handle_list_containers,
    "compose-control": DockerHandlers.handle_compose_control,
}


class InvokeRequest(BaseModel):
    tool: str
    arguments: Dict[str, Any] | None = None


class InvokeResponse(BaseModel):
    tool: str
    outputs: List[Dict[str, str]]


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _serialize_outputs(outputs: List[Any]) -> List[Dict[str, str]]:
    serialized: List[Dict[str, str]] = []
    for item in outputs:
        if hasattr(item, "type") and hasattr(item, "text"):
            serialized.append({"type": getattr(item, "type"), "text": getattr(item, "text")})
        else:
            serialized.append({"type": "text", "text": str(item)})
    return serialized


@app.get("/health")
async def health() -> Dict[str, Any]:
    try:
        # python-on-whales' DockerClient doesn't expose ping(); info() is lightweight and
        # still verifies daemon + socket connectivity.
        await asyncio.to_thread(docker_client.info)
        status = "ok"
        detail = "docker_socket_accessible"
    except DockerException as exc:
        status = "error"
        detail = str(exc)
    except Exception as exc:  # noqa: BLE001
        status = "error"
        detail = str(exc)

    return {"status": status, "detail": detail, "app": APP_NAME, "version": APP_VERSION}


@app.get("/tools")
async def list_tools() -> Dict[str, Any]:
    return {"tools": _tool_definitions()}


@app.get("/.well-known/mcp.json")
async def well_known_manifest() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "HTTP wrapper exposing docker-mcp tools over REST.",
        "capabilities": {
            "tools": _tool_definitions(),
        },
    }


@app.post("/invoke", response_model=InvokeResponse)
async def invoke(request: InvokeRequest) -> InvokeResponse:
    tool_name = request.tool.strip()
    handler = TOOL_DISPATCH.get(tool_name)
    if not handler:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{tool_name}'")

    arguments = request.arguments or {}
    if tool_name != "list-containers" and not arguments:
        raise HTTPException(status_code=400, detail="arguments are required for this tool")

    try:
        outputs = await handler(arguments)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return InvokeResponse(tool=tool_name, outputs=_serialize_outputs(outputs))


def create_app() -> FastAPI:
    """Allow uvicorn to load the FastAPI instance via string reference."""
    return app
