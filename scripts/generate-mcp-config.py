#!/usr/bin/env python3
"""Generate ~/.config/devin/mcp_config.json from ssot.mcp.yml.

This keeps the runtime Devin MCP configuration in sync with the SSOT
single source of truth and validates that referenced source files exist
before generating.
"""

import json
import os
import re
import shlex
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

SSOT_FILE = Path("/home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.mcp.yml")
OUTPUT_FILE = Path("/home/tony/.config/devin/mcp_config.json")
BACKUP_DIR = Path("/home/tony/.config/devin/mcp-backups")
MCP_SCRIPTS_DIR = Path("/home/tony/.config/devin/mcp-scripts")

RUNNER_MAP = {
    "python3": "/usr/bin/python3",
    "python": "/usr/bin/python3",
    "node": "/usr/bin/node",
    "bash": "/bin/bash",
    "npx": "npx",
}


def error(msg: str) -> None:
    print(f"ERROR: {msg}")


def resolve_value(value: Any, ssot: dict[str, Any], profile: str) -> Any:
    """Resolve profile.* references and expand ~ in strings."""
    if not isinstance(value, str):
        return value

    # Expand ~ to $HOME
    if value.startswith("~/") or value == "~":
        value = os.path.expanduser(value)

    # Resolve profile.service_urls.llama_url -> profiles[profile]['service_urls']['llama_url']
    m = re.match(r"^profile\.([^.]+)\.(.+)$", value)
    if m:
        section, key = m.group(1), m.group(2)
        profiles = ssot.get("profiles", {})
        profile_data = profiles.get(profile, {})
        resolved = profile_data
        for part in [section, key]:
            if isinstance(resolved, dict) and part in resolved:
                resolved = resolved[part]
            else:
                raise KeyError(f"profile.{section}.{key} not found in profile {profile!r}")
        return resolve_value(resolved, ssot, profile)

    # Resolve profile.base_urls.tony_omen style references too
    m2 = re.match(r"^profile\.([^.]+)$", value)
    if m2:
        section = m2.group(1)
        profiles = ssot.get("profiles", {})
        profile_data = profiles.get(profile, {})
        if section in profile_data:
            return resolve_value(profile_data[section], ssot, profile)

    return value


def parse_command_tokens(implementation: str, extra_args: list[str] | None = None) -> tuple[str, list[str]]:
    """Split an implementation string into command and args.

    If the first token is a known runner, use the mapped executable.
    If it is an absolute path, default to /bin/bash so scripts execute correctly.
    """
    tokens = shlex.split(implementation)
    if not tokens:
        raise ValueError(f"empty implementation: {implementation!r}")
    runner = tokens[0]
    rest = tokens[1:]
    if runner in RUNNER_MAP:
        return RUNNER_MAP[runner], rest + (extra_args or [])
    if runner.startswith("/"):
        return "/bin/bash", tokens + (extra_args or [])
    return runner, rest + (extra_args or [])


def derive_pattern(implementation: str) -> str:
    """Derive a pgrep-safe pattern from the implementation path."""
    tokens = shlex.split(implementation)
    path = tokens[-1] if tokens else implementation
    # e.g. /.../mcp-gpu/server.py -> mcp-gpu/server.py
    # e.g. /.../mcp-playlive/playlive-server.py -> mcp-playlive/playlive-server.py
    parts = Path(path).parts
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return Path(path).name


def wrapper_path(wrapper: str) -> str:
    if wrapper == "mcp-single-instance.sh":
        return str(MCP_SCRIPTS_DIR / "mcp-single-instance.sh")
    if (MCP_SCRIPTS_DIR / wrapper).exists():
        return str(MCP_SCRIPTS_DIR / wrapper)
    # Some wrapper fields are labels, not file names; fall back to raw value
    return wrapper


def build_server_config(name: str, cfg: dict[str, Any], ssot: dict[str, Any], profile: str) -> dict[str, Any]:
    """Convert one ssot.mcp.yml server entry into an mcp_config.json server entry."""
    if "url" in cfg:
        return {"url": resolve_value(cfg["url"], ssot, profile)}

    wrapper = cfg.get("wrapper", "none")
    implementation = cfg.get("implementation", "")
    pattern = cfg.get("pattern")
    single_instance = cfg.get("single_instance", False)

    if wrapper == "mcp-single-instance.sh":
        # Inner command is in implementation, e.g. "python3 /path/server.py"
        tokens = shlex.split(implementation)
        if len(tokens) < 2:
            raise ValueError(f"{name}: mcp-single-instance.sh wrapper needs runner + path in implementation")
        runner = tokens[0]
        inner_path = tokens[1]
        if len(tokens) > 2:
            inner_path = shlex.join(tokens[1:])  # keep the rest as one arg if needed
        resolved_path = resolve_value(inner_path, ssot, profile)
        command = wrapper_path(wrapper)
        pat = pattern or derive_pattern(implementation)
        args = [pat, runner, resolved_path]

    elif wrapper.endswith(".sh") and wrapper != "mcp-single-instance.sh":
        wpath = resolve_value(wrapper_path(wrapper), ssot, profile)
        if single_instance:
            command = str(MCP_SCRIPTS_DIR / "mcp-single-instance.sh")
            pat = pattern or wrapper.replace(".sh", "")
            args = [pat, wpath]
        else:
            command = "/bin/bash"
            args = [wpath]

    else:
        # wrapper is "none" or a label; implementation is the full command
        if not implementation:
            raise ValueError(f"{name}: no implementation and no url")
        command, args = parse_command_tokens(implementation, cfg.get("args", []))
        # Resolve any path-like tokens
        args = [resolve_value(a, ssot, profile) for a in args]

    server = {"command": command, "args": args}

    if cfg.get("env"):
        resolved_env = {}
        for k, v in cfg["env"].items():
            resolved_env[k] = resolve_value(v, ssot, profile)
        server["env"] = resolved_env

    return server


def should_include_for_devin(cfg: dict[str, Any]) -> bool:
    for item in cfg.get("config_files", []):
        if isinstance(item, dict) and item.get("devin"):
            return bool(item["devin"])
    return False


def main() -> int:
    if not SSOT_FILE.exists():
        error(f"SSOT file not found: {SSOT_FILE}")
        return 1

    with open(SSOT_FILE, "r", encoding="utf-8") as f:
        ssot = yaml.safe_load(f) or {}

    generation = ssot.get("generation", {})
    profile = os.environ.get("DEVIN_MCP_PROFILE", generation.get("default_profile", "home"))

    if profile not in ssot.get("profiles", {}):
        error(f"profile {profile!r} not defined in {SSOT_FILE}")
        return 1

    mcp_servers: dict[str, Any] = {}
    missing: list[str] = []
    skipped: list[str] = []

    for name, cfg in ssot.get("servers", {}).items():
        if cfg.get("status") != "operational":
            skipped.append(name)
            continue
        if not should_include_for_devin(cfg):
            skipped.append(name)
            continue

        try:
            server = build_server_config(name, cfg, ssot, profile)
        except (ValueError, KeyError) as e:
            error(f"{name}: {e}")
            return 1

        # Validate that any local implementation paths exist
        for arg in server.get("args", []):
            if isinstance(arg, str) and arg.startswith("/"):
                if (Path(arg).is_file() and not Path(arg).exists()) or ("server.py" in arg and not Path(arg).exists()):
                    missing.append(f"{name}: {arg}")

        mcp_servers[name] = server

    if missing:
        error("some operational MCP server source files are missing:")
        for item in missing:
            error(f"  - {item}")
        return 1

    config = {"mcpServers": mcp_servers}

    # Backup existing config
    if OUTPUT_FILE.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = BACKUP_DIR / f"mcp_config.json.{ts}"
        shutil.copy2(OUTPUT_FILE, backup)
        print(f"Backed up existing config to {backup}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"Generated {OUTPUT_FILE} with {len(mcp_servers)} Devin MCP servers")
    print(f"Profile: {profile}")
    print(f"Skipped: {', '.join(skipped) if skipped else 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
