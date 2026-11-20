#!/usr/bin/env python3
"""mcp-inventory.py — observed MCP inventory producer + fleet rollup.

Part of the layered reporting standard (docs/ssot/infrastructure/ssot.reports.yml):

* ``--host <name>``   L1 producer ``mcp-inventory/<name>``. Reads the MCP
  configs present on one host (Devin / Windsurf / Codeium / OpenCode), compares
  them with the declared servers in ssot.mcp.yml, probes running processes,
  then writes an L0 artifact + meta.yml via scripts/lib/report.py::write_meta.
* ``--all``           run the L1 producer for every host declared in
  ssot.mcp.yml (local read for this host, SSH probe for the rest).
* ``--consolidate``   L2 domain ``mcp-fleet``. Renders
  reports/mcp-fleet/MCP-FLEET-REPORT.md + meta.yml from the L1 metas/artifacts.

Never writes secrets: every string is redacted before it reaches an artifact.
Declared truth stays in ssot.mcp.yml; this script only observes and reports.
Card: KNB-0019 (fleet-mcp-inventory-report-wiki-edu).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from lib.report import (  # noqa: E402
    append_timeline,
    inputs_snapshot,
    now_iso,
    write_meta,
)

SSOT_MCP = REPO / "docs" / "ssot" / "infrastructure" / "ssot.mcp.yml"
L1_DIR = REPO / "reports" / "mcp-inventory"
L2_DIR = REPO / "reports" / "mcp-fleet"

# Agent config surfaces declared in ssot.tools.yml (agent_lanes).
CONFIG_PATHS = {
    "devin": "~/.config/devin/mcp_config.json",
    "windsurf": "~/.config/windsurf/mcp_config.json",
    "codeium": "~/.config/codeium/mcp_config.json",
    "opencode": "~/.config/opencode/opencode.json",
}

# Token-bearing URL query params and long opaque path tokens (HA/API keys).
_SECRET_QUERY = re.compile(r"(?i)([?&](?:apikey|api_key|token|key|secret)=)[^&\s\"']+")
_LONG_TOKEN = re.compile(r"(?<![\w/])([A-Za-z0-9_\-]{28,})(?![\w/])")


def redact(value):
    """Best-effort scrub so an artifact never carries a credential."""
    if isinstance(value, dict):
        return {str(k): redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    s = _SECRET_QUERY.sub(r"\1<redacted>", value)
    s = _LONG_TOKEN.sub("<redacted>", s)
    return s


def load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def ssh_name(host: str) -> str:
    """ssot.mcp.yml uses underscores; tailnet names use hyphens."""
    return host.replace("_", "-")


def is_local(host: str) -> bool:
    return ssh_name(host) == os.uname().nodename.split(".")[0]


def run_remote(host: str, command: str, timeout: int = 8) -> tuple[int, str]:
    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=accept-new", ssh_name(host), command,
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except (subprocess.TimeoutExpired, OSError):
        return 124, ""


# --- config discovery -------------------------------------------------------

def server_names_from_config(path: str, text: str) -> list[str]:
    """Extract MCP server names from a JSON config; tolerate shape drift."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    candidates = []
    if isinstance(data, dict):
        for key in ("mcpServers", "servers", "mcp"):
            node = data.get(key)
            if isinstance(node, dict):
                candidates.extend(node.keys())
    return sorted({str(n) for n in candidates})


def read_configs(host: str) -> tuple[dict, bool]:
    """Return {surface: {path, present, servers}} and a host-reachable flag.

    A missing config file is not proof of an unreachable host: `cat` exits 1
    for a file that is not there, while SSH failure exits 255 (or 124 on
    timeout). Only the latter means the host could not be observed.
    """
    out = {}
    codes = []
    for surface, rel in CONFIG_PATHS.items():
        expanded = os.path.expanduser(rel)
        if is_local(host):
            p = Path(expanded)
            present = p.exists()
            text = p.read_text(errors="replace") if present else ""
            rc = 0 if present else 1
        else:
            rc, text = run_remote(host, "cat %s 2>/dev/null" % rel)
            present = rc == 0 and bool(text.strip())
        codes.append(rc)
        out[surface] = {
            "path": rel,
            "present": present,
            "read_ok": rc == 0,
            "servers": redact(server_names_from_config(rel, text)) if present else [],
        }
    reachable = is_local(host) or any(rc in (0, 1) for rc in codes)
    return out, reachable


def running_processes(host: str) -> list[str]:
    """Command lines mentioning an MCP server, for the running-state hint."""
    if is_local(host):
        try:
            p = subprocess.run(["ps", "-eo", "args"], capture_output=True,
                               text=True, timeout=8)
            text = p.stdout
        except (subprocess.TimeoutExpired, OSError):
            text = ""
    else:
        _, text = run_remote(host, "ps -eo args 2>/dev/null")
    lines = []
    for line in text.splitlines():
        if re.search(r"(?i)mcp|mddbd|playlive|notebooklm", line):
            lines.append(redact(line.strip())[:300])
    return lines[:200]


def declared_for_host(ssot: dict, host: str) -> dict:
    """Declared server rows applicable to a host, with per_host overrides."""
    servers = ssot.get("servers") or {}
    rows = {}
    for name, spec in servers.items():
        if not isinstance(spec, dict):
            continue
        row = dict(spec)
        override = (spec.get("per_host") or {}).get(host)
        if isinstance(override, dict):
            row.update(override)
        elif override is not None:
            row["implementation"] = override
        # A server is in scope everywhere unless it pins per_host keys.
        per = spec.get("per_host")
        if isinstance(per, dict) and per and host not in per:
            continue
        rows[name] = {
            "status": str(row.get("status") or "unknown"),
            "implementation": redact(str(row.get("implementation") or "")),
            "transport": "http" if row.get("url") else (
                "stdio" if row.get("implementation") else "unknown"),
        }
    return rows


# --- L1 producer ------------------------------------------------------------

def produce_host(ssot: dict, host: str, force_local: bool = False) -> dict:
    global is_local
    if force_local:
        real_is_local = is_local
        is_local = lambda h: True  # noqa: E731 - scoped override for this call
    try:
        return _produce_host(ssot, host)
    finally:
        if force_local:
            is_local = real_is_local


def _produce_host(ssot: dict, host: str) -> dict:
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    configs, reachable = read_configs(host)
    procs = running_processes(host) if reachable else []
    declared = declared_for_host(ssot, host)
    configured = sorted({s for c in configs.values() for s in c["servers"]})

    missing = sorted(set(declared) - set(configured))
    extra = sorted(set(configured) - set(declared))
    # retired/blocked declarations are not expected to be configured.
    active_declared = sorted(
        n for n, s in declared.items()
        if not str(s["status"]).startswith(("retired", "blocked"))
    )
    missing_active = sorted(set(active_declared) - set(configured))

    if not reachable:
        status = "unreachable"
        summary = f"{host}: no config surfaces answered (SSH/probe failed)"
        # An unprobed host has no observed configuration — reporting its
        # servers as "missing" would be a false finding.
        missing_active = []
    elif not configured:
        status = "no-config"
        summary = f"{host}: reachable, no MCP client configs present (0 configured)"
        # An infra host without agent configs is not a declaration drift:
        # global server entries apply to agent lanes, not to every host.
        missing_active = []
    elif missing_active:
        status = "delta"
        summary = (f"{host}: {len(configured)} configured, "
                   f"{len(missing_active)} active declared servers absent")
    else:
        status = "ok"
        summary = (f"{host}: {len(configured)} configured, "
                   f"{len(active_declared)} active declared present")

    artifact = {
        "node": f"mcp-inventory/{host}",
        "host": host,
        "observed_at": now_iso(),
        "ssh_name": ssh_name(host),
        "declared_count": len(declared),
        "active_declared": active_declared,
        "configured_count": len(configured),
        "configured": configured,
        "missing_declared": missing,
        "missing_active": missing_active,
        "undeclared_configured": extra,
        "declared": declared,
        "configs": configs,
        "running_process_hints": procs,
        "status": status,
    }
    L1_DIR.mkdir(parents=True, exist_ok=True)
    art_path = L1_DIR / f"{host}-{stamp}.yml"
    art_path.write_text(yaml.safe_dump(redact(artifact), sort_keys=False,
                                       allow_unicode=True))

    meta_path = L1_DIR / f"meta.{host}.yml"
    write_meta(
        meta_path,
        node=f"mcp-inventory/{host}",
        layer="L1-producer",
        purpose="Observed MCP server inventory and declared-vs-configured drift",
        generated_by=f"scripts/mcp-inventory.py --host {host}",
        status=status,
        summary=summary,
        sources=[str(art_path.relative_to(REPO)),
                 "docs/ssot/infrastructure/ssot.mcp.yml"],
        extra={
            "configured": len(configured),
            "declared": len(declared),
            "missing_active": missing_active,
            "undeclared_configured": extra,
        },
    )
    append_timeline(f"mcp-inventory/{host}", "L1", status, summary,
                    ref=str(art_path.relative_to(REPO)))
    return artifact


# --- L2 rollup --------------------------------------------------------------

def consolidate(ssot: dict) -> dict:
    hosts = list((ssot.get("hosts") or {}).keys())
    rows = []
    for host in hosts:
        meta = load_yaml_safe(L1_DIR / f"meta.{host}.yml")
        if not meta:
            continue
        rows.append({
            "host": host,
            "status": meta.get("status", "missing"),
            "summary": meta.get("summary", ""),
            "generated_at": meta.get("generated_at", ""),
            "configured": (meta.get("extra") or {}).get("configured", 0),
            "declared": (meta.get("extra") or {}).get("declared", 0),
            "missing_active": (meta.get("extra") or {}).get("missing_active") or [],
        })

    registry = load_yaml_safe(REPO / "docs" / "ssot" / "infrastructure"
                              / "ssot.reports.yml")
    node = next((n for n in (registry.get("nodes") or [])
                 if n.get("id") == "mcp-fleet"), {})
    inputs = inputs_snapshot(node, registry)

    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    drift = [r for r in rows if r["status"] in ("delta", "unreachable", "error")]
    # "no-config" is informational: the host answered but runs no agent lane.
    status = "delta" if drift else "ok"
    headline = (f"{len(rows)} hosts observed; "
                f"{len(drift)} with findings "
                f"({', '.join(f'{k}={v}' for k, v in sorted(counts.items()))})")

    generated_at = now_iso()
    md = ["# Fleet MCP Inventory Report", "",
          f"_Generated: {generated_at}_  ",
          "_Source: scripts/mcp-inventory.py --consolidate (SSOT: ssot.mcp.yml)_",
          "", "## Headline", "", headline, "",
          "## Per-host state", "",
          "| Host | Status | Configured | Declared | Summary |",
          "|---|---|---:|---:|---|"]
    wiki = ["= Fleet MCP Inventory Report =", "",
            f"_Generated: {generated_at}_", "",
            "Source: <code>scripts/mcp-inventory.py --consolidate</code> "
            "(SSOT: <code>ssot.mcp.yml</code>).", "",
            "== Headline ==", "", headline, "",
            "== Per-host state ==", "",
            '{| class="wikitable"',
            "! Host !! Status !! Configured !! Declared !! Summary"]
    for r in rows:
        md.append(f"| {r['host']} | {r['status']} | {r['configured']} | "
                  f"{r['declared']} | {r['summary']} |")
        wiki.append("|-")
        wiki.append(f"| {r['host']} || {r['status']} || {r['configured']} "
                    f"|| {r['declared']} || {r['summary']}")
    wiki.append("|}")
    md += ["", "## Findings", ""]
    wiki += ["", "== Findings ==", ""]
    if drift:
        for r in drift:
            md.append(f"- **{r['host']}** ({r['status']}): {r['summary']}")
            wiki.append(f"* '''{r['host']}''' ({r['status']}): {r['summary']}")
            if r["status"] not in ("unreachable", "no-config") and r["missing_active"]:
                missing = ", ".join(r["missing_active"])
                md.append(f"  - active declared but not configured: {missing}")
                wiki.append(f"** Active declared but not configured: {missing}")
    else:
        md.append("_No drift — every observed host matched its declaration._")
        wiki.append("_No drift — every observed host matched its declaration._")

    L2_DIR.mkdir(parents=True, exist_ok=True)
    art = L2_DIR / "MCP-FLEET-REPORT.md"
    art.write_text("\n".join(md) + "\n")
    wiki_art = L2_DIR / "MCP-FLEET-REPORT.wiki"
    wiki_art.write_text("\n".join(wiki) + "\n")
    write_meta(
        L2_DIR / "meta.yml",
        node="mcp-fleet",
        layer="L2-domain",
        purpose="Cross-host MCP inventory drift and declared-vs-observed rollup",
        generated_by="scripts/mcp-inventory.py --consolidate",
        status=status,
        summary=headline,
        sources=[str(a.relative_to(REPO)) for a in
                 sorted(L1_DIR.glob("*.yml")) if a.name.startswith("meta.")],
        children=[f"mcp-inventory/{h}" for h in hosts],
        inputs_at=inputs,
        extra={"hosts": len(rows), "counts": counts, "chars": len("\n".join(md))},
    )
    append_timeline("mcp-fleet", "L2", status, headline,
                    ref=str(art.relative_to(REPO)))
    return {"status": status, "summary": headline, "hosts": len(rows)}


def load_yaml_safe(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


# --- Reports: publication ---------------------------------------------------
# board-api is the only mutation door; no wiki credentials are read here.
# A stable wiki_title means the daily job UPDATES one Reports: page instead
# of spawning a new page each run. The board sink also records the event on
# the coordination card as an audit trail. No Infrastructure: writes until
# the wiki-page-door-infrastructure-namespace card lands.
BOARD_API = os.environ.get(
    "BOARD_API_URL", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
WIKI_TITLE = os.environ.get(
    "MCP_FLEET_WIKI_TITLE", "Reports:Fleet-MCP-Inventory")
CARD_ID = "fleet-mcp-inventory-report-wiki-edu"


def publish_report() -> dict:
    """Upsert the L2 report into Reports: via POST /publish."""
    wiki_path = L2_DIR / "MCP-FLEET-REPORT.wiki"
    if not wiki_path.exists():
        raise RuntimeError("run --consolidate before --publish")
    meta = load_yaml_safe(L2_DIR / "meta.yml") or {}
    payload = {
        "kind": "report",
        "title": "Fleet MCP inventory",
        "source": "mcp-inventory",
        "from": "mcp-inventory",
        "body": wiki_path.read_text(encoding="utf-8"),
        "card": CARD_ID,
        "visibility": "private",
        "confidence": "observed",
        "sinks": ["wiki-reports", "board"],
        "meta": {
            "wiki_title": WIKI_TITLE,
            "report_type": "MCP Fleet Inventory",
            "period": "current",
            "format": "wikitext",
            "status": "current",
            "updated": str(meta.get("generated_at") or "")[:10],
            "source_key": "mcp-fleet",
        },
    }
    req = urllib.request.Request(
        f"{BOARD_API}/publish",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"board-api /publish -> {e.code}: "
                           f"{e.read()[:300].decode('utf-8', 'replace')}")
    receipts = result.get("receipts") or {}
    failures = {n: r for n, r in receipts.items()
                if isinstance(r, dict) and r.get("status") in
                ("queued", "skipped", "suppressed")}
    return {"event_id": result.get("event_id"), "deduped": result.get("deduped"),
            "receipts": receipts, "failures": failures,
            "message": result.get("message", "")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", help="observe one host (matches ssot.mcp.yml key)")
    ap.add_argument("--all", action="store_true", help="observe every declared host")
    ap.add_argument("--consolidate", action="store_true", help="render L2 fleet report")
    ap.add_argument("--publish", action="store_true",
                    help="upsert the rendered report into Reports: via board-api")
    ap.add_argument("--local", action="store_true",
                    help="read local config paths even for another host name")
    args = ap.parse_args()
    if not (args.host or args.all or args.consolidate or args.publish):
        ap.error("give --host, --all, --consolidate and/or --publish")

    ssot = load_yaml_safe(SSOT_MCP)
    hosts = list((ssot.get("hosts") or {}).keys())
    if args.host and args.host not in hosts:
        ap.error(f"unknown host {args.host!r}; declared: {', '.join(hosts)}")

    if args.host or args.all:
        targets = hosts if args.all else [args.host]
        for h in targets:
            art = produce_host(ssot, h, force_local=args.local)
            print(f"{h}: {art['status']} — {len(art['configured'])} configured "
                  f"({len(art['missing_active'])} active declared missing)")
    if args.consolidate:
        result = consolidate(ssot)
        print(f"mcp-fleet: {result['status']} — {result['summary']}")
    if args.publish:
        res = publish_report()
        print(f"Reports: upsert {res['event_id']} "
              f"(deduped={res['deduped']}): {res['message']}")
        for name, receipt in res["receipts"].items():
            print(f"  {name}: {receipt.get('status')} "
                  f"{receipt.get('ref') or receipt.get('reason') or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
