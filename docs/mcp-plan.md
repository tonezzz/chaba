# MCP plan for chaba2 — `mcp-homelab`

## Goal
Expose a controlled, read-mostly interface between the AI assistant and the chaba2 stack so the assistant can inspect state and trigger safe, idempotent actions without needing broad shell access.

The server is named **`mcp-homelab`**: one instance that can talk to many host *types* through adapters, but only one MCP server runs on the primary host.

## Best-practice guidelines

1. **One MCP server (`mcp-homelab`) per logical stack, not per host.**
   - A single MCP server runs alongside the primary host (`tony-omen`, 192.168.1.48).
   - Remote hosts (`tony-dell`, VSTARCAM, Frigate if external, etc.) are reached through existing APIs, SSH, or small agent endpoints — not by running a second MCP server.
   - Multiple MCP servers create duplicated permission logic and conflicting tool names.

2. **Prefer read-only tools; writes require explicit, auditable actions.**
   - Read: status, camera list, container list, recordings, disk usage, temperatures.
   - Write: regenerate Frigate config, restart a service, toggle a camera.
   - Any destructive action should return a confirmation summary and log to stdout/file.

3. **Reuse existing APIs instead of re-implementing them.**
   - `/api/status` already gives system, Docker, Frigate, and camera summary.
   - `stacks/nvr/generate_config.py` already performs config regeneration.
   - The MCP server should call these, not replace them.

4. **Run the MCP server in a container on the web stack.**
   - Adds it behind Caddy if needed, keeps it on the same lifecycle as `status-api`.
   - Mount the repo read-only where possible and the Docker socket read-only if container introspection is required.

5. **Security boundaries**
   - The MCP server should not run as root.
   - It should not have write access to `stacks/nvr/config.yml` unless it is performing a regeneration.
   - Tool permissions should be coarse-grained at startup (e.g. `--allow-write` flag).

## Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| R1 | Expose `get_system_status` returning `/api/status` data. | Must |
| R2 | Expose `list_cameras` returning `stacks/nvr/cameras.json` summary. | Must |
| R3 | Expose `check_camera_stream` calling `generate_config.py --check` for one camera. | Should |
| R4 | Expose `regenerate_frigate_config` running `generate_config.py`. | Should |
| R5 | Expose `enable_camera` / `disable_camera` by name, regenerating config. | Could |
| R6 | Expose `list_docker_containers` and `container_logs`. | Should |
| R7 | Expose `get_temperatures` for the host running the server (`tony-omen`). | Could |
| R8 | Reach `tony-dell` only through its existing `:8090` camera-control endpoint or SSH; do not install a second MCP server there. | Must |

## Jobs / tools to expose

1. **Inspection tools**
   - `get_overview(group=None)` — at-a-glance summary. Returns grouped hosts/services if no group is specified, or only one group (`docker-hosts`, `workstations`, `cameras`, `external-streams`, `services`).
   - `get_hosts()` — all hosts.
   - `get_host(name)` — one host by name.
   - `get_services()` — all services.
   - `get_service(name)` — one service by name.
   - `get_cameras()` — all cameras.
   - `get_camera(name)` — one camera by name.
   - `get_system_status()`
   - `get_host_temperatures(host)`
   - `get_docker_containers()`
   - `get_container_logs(name, tail=50)`

2. **Action tools**
   - `regenerate_frigate_config()`
   - `enable_camera(name)`
   - `disable_camera(name)`
   - `restart_web_stack()`
   - `restart_frigate_stack()`

3. **Utility tools**
   - `read_file(path)` — scoped under the repo path only.
   - `run_command(command)` — optional, behind an `--unsafe` flag; otherwise disabled.

### Naming convention

- **Plural** = collection: `get_hosts()`, `get_services()`, `get_cameras()`.
- **Singular** = single item lookup: `get_host(name)`, `get_service(name)`, `get_camera(name)`.
- Avoid `get_all`; use `get_overview()` or a specific plural endpoint so callers know exactly what they are receiving.

### Display-friendly output example

`get_overview()` should return something like:

```json
[
  {
    "name": "tony-omen",
    "ip": "192.168.1.48",
    "role": "docker-host",
    "reachable": true,
    "temperature_c": 85.0,
    "services_up": ["caddy", "status-api", "camera-control"],
    "services_down": [],
    "last_seen": "2026-07-21T05:25:00Z"
  },
  {
    "name": "tony-dell",
    "ip": "192.168.1.42",
    "role": "workstation",
    "reachable": false,
    "temperature_c": null,
    "services_up": [],
    "services_down": ["camera-control"],
    "last_seen": null
  }
]
```

## Host groups

Group hosts before building the overview so the data is easy to scan and the MCP tool can filter.

| Group | Members | How to check |
|-------|---------|--------------|
| `docker-hosts` | `tony-omen` | Local Docker socket, `/api/status`, `psutil` |
| `workstations` | `tony-dell` | HTTP poll to `:8090` camera-control, or SSH agent |
| `cameras` | `vstarcam`, XMEye DVR (blocked) | RTSP probe via ffmpeg or Frigate stream health |
| `external-streams` | DOH Wowza `.207/.208`, GISTDA, iTIC | HTTP/TLS probe or known HLS URL check |
| `services` | `caddy`, `status-api`, `camera-control`, `frigate`, `nerfstudio`, `jupyter` | Docker container state + port health |

## Host strategy

| Host | Group | MCP server? | Reason |
|------|-------|-------------|--------|
| `tony-omen` (192.168.1.48) | `docker-hosts` | **Yes** — primary server. | This is the Docker host, web stack, and source of truth for `cameras.json`. |
| `tony-dell` (192.168.1.42) | `workstations` | **No** | It already exposes a camera-control web UI. The MCP server on `tony-omen` can poll it over HTTP or SSH. |
| VSTARCAM (192.168.1.41) | `cameras` | **No** | RTSP-only camera; no place to run an MCP server. |
| Frigate | `services` | **No** | It already has an HTTP API at `:5000`. The MCP server can proxy to it. |

## Tool output

`get_overview(group=None)` returns all hosts and services by default. If `group` is given, only that group is returned. Each record includes the `group` field so callers can render grouped tables or foldable sections.

## Implementation status

- `mcp/server.py` — initial stdio server using `mcp.server.fastmcp`.
- `mcp/requirements.txt` — dependency on the official Python MCP SDK.
- Supports read-only tools: `get_overview`, `get_hosts`, `get_host`, `get_services`, `get_service`, `get_system_status`, `get_host_temperatures`, `get_docker_containers`, `get_container_logs`.

## Run locally (stdio)

```bash
python3 -m venv mcp/.venv
source mcp/.venv/bin/activate
pip install -r mcp/requirements.txt
python3 mcp/server.py
```

## Connect in Windsurf / Cascade

Add to your MCP config:

```json
{
  "mcpServers": {
    "mcp-homelab": {
      "command": "bash",
      "args": [
        "-c",
        "source /home/tony/CascadeProjects/chaba2/mcp/.venv/bin/activate && python3 /home/tony/CascadeProjects/chaba2/mcp/server.py"
      ]
    }
  }
}
```

Once connected, ask the assistant: `get_hosts`, `get_services`, or `get_overview`.

Future transport: SSE over HTTP can be added later if remote access is needed.

## Risks

- If the MCP server can write `stacks/nvr/config.yml` or restart services, a bad prompt could take down surveillance.
- Running it on every host multiplies update and credential management effort.
- Exposing `run_command` makes the MCP server as powerful as shell access; keep it disabled by default.

## Next step

- Install the Python MCP SDK in `mcp/.venv` and test the server with a stdio client.
- Wire the stdio command into Windsurf/Cascade MCP settings.
- Add action tools (`regenerate_frigate_config`, `enable_camera`, `disable_camera`) behind an explicit `--unsafe` or confirmation flag.
