#!/usr/bin/env python3
"""mcp-homelab — read-only MCP server for the chaba2 stack.

Runs over stdio by default for local IDE integration (e.g. Windsurf/Cascade).
"""
import json
import os
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-homelab")

REPO_PATH = os.environ.get("REPO_PATH", "/home/tony/CascadeProjects/chaba2")
STATUS_URLS = [
    "http://status-api:8000/api/status",
    "http://localhost:8080/api/status",
]

HOSTS = [
    {
        "name": "tony-omen",
        "ip": "192.168.1.48",
        "group": "docker-hosts",
        "role": "Docker host",
    },
    {
        "name": "tony-dell",
        "ip": "192.168.1.42",
        "group": "workstations",
        "role": "Secondary workstation",
    },
    {
        "name": "vstarcam",
        "ip": "192.168.1.41",
        "group": "cameras",
        "role": "IP camera",
        "port": "10554",
    },
]

SERVICES = [
    {"name": "caddy", "host": "tony-omen", "port": 8080},
    {"name": "status-api", "host": "tony-omen", "port": 8000, "internal": True},
    {"name": "camera-control", "host": "tony-omen", "port": 8090, "internal": True},
    {"name": "frigate", "host": "tony-omen", "port": 5000},
    {"name": "nerfstudio", "host": "tony-omen", "port": 7007},
    {"name": "jupyter", "host": "tony-omen", "port": 8888},
]


def _fetch_status() -> dict[str, Any]:
    last_error = None
    for url in STATUS_URLS:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"status-api unreachable: {last_error}")


def _temperatures_for_host(host: str, status: dict[str, Any]) -> list[dict[str, Any]]:
    if host != "tony-omen":
        return []
    temps = status.get("host", {}).get("temperatures", {})
    return temps.get("coretemp", [])


@mcp.tool()
def get_overview(group: str | None = None) -> str:
    """Return a grouped overview of hosts and services.

    Args:
        group: Optional filter — docker-hosts, workstations, cameras,
               external-streams, or services.
    """
    status = _fetch_status()
    host_records = []
    for h in HOSTS:
        if group and h["group"] != group:
            continue
        temps = _temperatures_for_host(h["name"], status)
        pkg = next((t for t in temps if t.get("label") == "Package id 0"), None)
        host_records.append(
            {
                "name": h["name"],
                "ip": h["ip"],
                "group": h["group"],
                "role": h["role"],
                "temperature_c": pkg.get("current") if pkg else None,
                "services_up": ["caddy"],
                "services_down": [],
            }
        )

    service_records = []
    for s in SERVICES:
        if group and group != "services":
            continue
        service_records.append(
            {
                "name": s["name"],
                "host": s["host"],
                "port": s["port"],
                "internal": s.get("internal", False),
            }
        )

    result = {"hosts": host_records, "services": service_records}
    return json.dumps(result, indent=2)


@mcp.tool()
def get_hosts() -> str:
    """Return all configured hosts."""
    return json.dumps(HOSTS, indent=2)


@mcp.tool()
def get_host(name: str) -> str:
    """Return a single host by name."""
    for h in HOSTS:
        if h["name"] == name:
            return json.dumps(h, indent=2)
    return json.dumps({"error": "host not found"})


@mcp.tool()
def get_services() -> str:
    """Return all configured services."""
    return json.dumps(SERVICES, indent=2)


@mcp.tool()
def get_service(name: str) -> str:
    """Return a single service by name."""
    for s in SERVICES:
        if s["name"] == name:
            return json.dumps(s, indent=2)
    return json.dumps({"error": "service not found"})


@mcp.tool()
def get_system_status() -> str:
    """Return the raw /api/status payload."""
    return json.dumps(_fetch_status(), indent=2)


@mcp.tool()
def get_host_temperatures(host: str) -> str:
    """Return temperature sensors for a host (currently only tony-omen)."""
    status = _fetch_status()
    temps = _temperatures_for_host(host, status)
    return json.dumps(temps, indent=2)


@mcp.tool()
def get_docker_containers() -> str:
    """Return the list of Docker containers from /api/status."""
    status = _fetch_status()
    return json.dumps(status.get("containers", []), indent=2)


@mcp.tool()
def get_container_logs(name: str, tail: int = 50) -> str:
    """Placeholder: return container info; log streaming requires Docker socket access."""
    status = _fetch_status()
    containers = status.get("containers", [])
    for c in containers:
        if c.get("name") == name:
            return json.dumps({"name": name, "status": c.get("status"), "image": c.get("image")}, indent=2)
    return json.dumps({"error": "container not found"})


if __name__ == "__main__":
    mcp.run(transport="stdio")
