#!/usr/bin/env python3
"""Generate MCP configuration from ssot.mcp.yml.

Keeps the runtime Devin/Windsurf MCP configuration in sync with the SSOT
single source of truth and validates that referenced source files exist
before generating.
"""

import argparse
import json
import os
import re
import shlex
import shutil
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SSOT_FILE = REPO_ROOT / "docs" / "ssot" / "infrastructure" / "ssot.mcp.yml"
OUTPUT_FILE = Path("/home/tony/.config/devin/mcp_config.json")
BACKUP_DIR = Path("/home/tony/.config/devin/mcp-backups")
MCP_SCRIPTS_DIR = Path("/home/tony/.config/devin/mcp-scripts")
MCP_SCRIPTS_SRC = REPO_ROOT / "scripts" / "mcp-scripts"


class UniqueLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate mapping keys."""


def _require_unique_keys(loader: yaml.Loader, node: yaml.MappingNode) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in mapping:
            raise yaml.YAMLError(f"duplicate key {key!r} in {node.start_mark}")
        mapping[key] = loader.construct_object(value_node)
    return mapping


UniqueLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _require_unique_keys,
)

RUNNER_MAP = {
    "python3": "/usr/bin/python3",
    "python": "/usr/bin/python3",
    "node": "/usr/bin/node",
    "bash": "/bin/bash",
    "npx": "npx",
}


def error(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"WARN: {msg}", file=sys.stderr)


def normalize_host(host: str) -> str:
    return re.sub(r"[-.]+", "_", host).strip("_").lower()


def current_host() -> str:
    return normalize_host(socket.gethostname())


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


def merge_host_overrides(cfg: dict[str, Any], host: str) -> dict[str, Any]:
    """Return a server config merged with the per_host block for `host`."""
    merged = dict(cfg)
    per_host = merged.pop("per_host", None)
    if not isinstance(per_host, dict):
        return merged

    for key in (host, host.replace("_", "-")):
        overrides = per_host.get(key)
        if not isinstance(overrides, dict):
            continue
        for k, v in overrides.items():
            if k == "env" and isinstance(v, dict) and "env" in merged:
                env = dict(merged["env"])
                env.update(v)
                merged["env"] = env
            else:
                merged[k] = v
        break

    return merged


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
        inner_path = shlex.join(tokens[1:])
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


def should_include_for_target(cfg: dict[str, Any], target: str) -> bool:
    for item in cfg.get("config_files", []):
        if isinstance(item, dict) and item.get(target):
            return bool(item[target])
    return False


def looks_like_executable_path(arg: str) -> bool:
    return (
        arg.endswith((".py", ".js", ".mjs", ".sh"))
        or "/node_modules/" in arg
        or "server.py" in arg
    )


def install_wrappers() -> int:
    """Sync wrapper scripts from the repo to the runtime mcp-scripts directory."""
    if not MCP_SCRIPTS_SRC.exists():
        error(f"wrapper source not found: {MCP_SCRIPTS_SRC}")
        return 1
    MCP_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    for src in MCP_SCRIPTS_SRC.iterdir():
        if not src.is_file() or src.name.startswith("."):
            continue
        dst = MCP_SCRIPTS_DIR / src.name
        if not dst.exists() or src.read_bytes() != dst.read_bytes():
            shutil.copy2(src, dst)
            print(f"installed {dst}")
    return 0


def validate_per_host_keys(ssot: dict[str, Any]) -> bool:
    """Check that every per_host key is a known host id."""
    valid: set[str] = set()
    for profile_data in ssot.get("profiles", {}).values():
        if isinstance(profile_data, dict) and isinstance(profile_data.get("base_urls"), dict):
            valid.update(profile_data["base_urls"].keys())
    valid.update(ssot.get("hosts", {}).keys())

    ok = True
    for name, cfg in ssot.get("servers", {}).items():
        per_host = cfg.get("per_host", {})
        if not isinstance(per_host, dict):
            continue
        for key in per_host.keys():
            if key not in valid:
                error(f"server {name}: unknown per_host host {key!r}; expected one of {sorted(valid)}")
                ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate MCP config from ssot.mcp.yml")
    parser.add_argument("--host", default=None, help="Target host (default: this hostname)")
    parser.add_argument("--profile", default=None, help="Network profile (default: SSOT default)")
    parser.add_argument("--target", choices=["devin", "windsurf"], default="devin",
                        help="MCP client to generate for")
    parser.add_argument("--output", type=Path, default=None, help="Output file path")
    parser.add_argument("--ssot", type=Path, default=SSOT_FILE, help="SSOT YAML file")
    parser.add_argument("--install-wrappers", action="store_true",
                        help="Sync wrapper scripts from the repo to ~/.config/devin/mcp-scripts")
    args = parser.parse_args()

    if not args.ssot.exists():
        error(f"SSOT file not found: {args.ssot}")
        return 1

    with open(args.ssot, "r", encoding="utf-8") as f:
        ssot = yaml.load(f, Loader=UniqueLoader) or {}

    generation = ssot.get("generation", {})
    profile = args.profile or os.environ.get("DEVIN_MCP_PROFILE") or generation.get("default_profile", "home")
    host = normalize_host(args.host or os.environ.get("DEVIN_MCP_HOST") or socket.gethostname())
    this_host = current_host()

    if profile not in ssot.get("profiles", {}):
        error(f"profile {profile!r} not defined in {args.ssot}")
        return 1

    if not validate_per_host_keys(ssot):
        return 1

    if args.install_wrappers:
        rc = install_wrappers()
        if rc != 0:
            return rc

    output_file = args.output or OUTPUT_FILE
    mcp_servers: dict[str, Any] = {}
    missing: list[str] = []
    skipped: list[str] = []

    for name, raw_cfg in ssot.get("servers", {}).items():
        cfg = merge_host_overrides(raw_cfg, host)

        if cfg.get("status") != "operational":
            skipped.append(name)
            continue
        if not should_include_for_target(cfg, args.target):
            skipped.append(name)
            continue

        try:
            server = build_server_config(name, cfg, ssot, profile)
        except (ValueError, KeyError) as e:
            error(f"{name}: {e}")
            return 1

        # Validate that any local implementation paths exist
        for arg in server.get("args", []):
            if isinstance(arg, str) and arg.startswith("/") and looks_like_executable_path(arg):
                if not Path(arg).exists():
                    msg = f"{name}: {arg}"
                    if host == this_host:
                        missing.append(msg)
                    else:
                        warn(f"expected remote file not present here: {msg}")

        mcp_servers[name] = server

    if missing:
        error("some operational MCP server source files are missing:")
        for item in missing:
            error(f"  - {item}")
        return 1

    config = {"mcpServers": mcp_servers}

    # Backup existing config
    if output_file.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = BACKUP_DIR / f"mcp_config.json.{ts}"
        shutil.copy2(output_file, backup)
        print(f"Backed up existing config to {backup}")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"Generated {output_file} with {len(mcp_servers)} {args.target} MCP servers")
    print(f"Profile: {profile}")
    print(f"Host: {host}")
    print(f"Skipped: {', '.join(skipped) if skipped else 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
