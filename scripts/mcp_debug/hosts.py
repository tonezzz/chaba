"""MCP Debug host operations."""
import shlex
import socket
import subprocess
from .config import HOSTS, RAW_PREFIXES


def _is_local(host):
    if host not in HOSTS:
        return False
    h = HOSTS[host]
    if h.get("local"):
        return True
    current = socket.gethostname()
    return current in (host, h.get("hostname"), h.get("name"))


def run_on_host(host, command, compact, shell=False):
    if host not in HOSTS:
        return {"ok": False, "error": f"unknown host: {host}", "available_hosts": list(HOSTS.keys())}
    h = HOSTS[host]
    if compact and not h.get("compact", True):
        return {"ok": False, "error": f"compact mcp_debug not supported for host: {host}", "host": host, "rc": 1, "out": "", "err": ""}
    mcp_debug = h.get("mcp_debug_path", "/home/tony/.local/bin/mcp-debug")

    if not compact and not shell:
        base = shlex.split(command)[0]
        base_name = base.split("/")[-1]
        if base_name not in RAW_PREFIXES:
            return {"ok": False, "error": f"raw command base '{base_name}' not in allowed_prefixes", "allowed": RAW_PREFIXES}

    if _is_local(host):
        if compact:
            argv = [mcp_debug] + shlex.split(command)
        else:
            argv = ["bash", "-c", command]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    else:
        ssh = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=60", "-o", "ServerAliveCountMax=3", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes"]
        user = h.get("ssh_user", "tony")
        hostname = h.get("hostname", host)
        target = f"{user}@{hostname}"
        if compact:
            remote = " ".join([shlex.quote(mcp_debug)] + [shlex.quote(a) for a in shlex.split(command)])
        else:
            remote = command
        proc = subprocess.run(ssh + [target, remote], capture_output=True, text=True, timeout=300)

    return {
        "ok": proc.returncode == 0,
        "host": host,
        "rc": proc.returncode,
        "out": proc.stdout,
        "err": proc.stderr,
    }

