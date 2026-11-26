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

Expected sets are computed from `fleet_observation.scope_model` in
ssot.mcp.yml: a server's `scope` (fleet | agent-lanes | [named hosts]) decides
which hosts expect it; `per_host` only overrides declaration details for a
host and never removes a host from scope. Findings carry stable IDs and human-owned
triage state read from `fleet_observation.finding_triage` — this producer
never writes triage state or card workflow fields.

Never writes secrets: every string is redacted before it reaches an artifact.
Declared truth stays in ssot.mcp.yml; this script only observes and reports.
Cards: KNB-0019 (fleet-mcp-inventory-report-wiki-edu), OPS-0025
(mcp-inventory-scope-status-standard — scope/status/finding standard).
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


def observation_config(ssot: dict) -> dict:
    return ssot.get("fleet_observation") or {}


def in_scope(fleet: dict, name: str, spec: dict, host: str) -> bool:
    """Evaluate a server's declared scope for a host.

    `per_host` is an implementation override applied by declared_for_host,
    not an inclusion filter. Treating it as a filter made every server with
    a single-host override (mcp-gpu, mcp-llama, mcp-weaviate) vanish from
    other agent lanes and manufacture false 'undeclared configured' findings.
    Use `scope: [host, ...]` to restrict a server to named hosts.

    Unknown or absent scope is a declaration bug: fail loudly so a bad
    SSOT edit cannot silently widen the expected set into false deltas.
    """
    model = fleet.get("scope_model") or {}
    if "scope" not in spec:
        raise ValueError(
            f"ssot.mcp.yml: server {name!r} has no scope "
            "(fleet_observation.scope_model requires one)")
    scope = spec["scope"]
    if isinstance(scope, list):
        applies = host in scope
    elif scope == "fleet":
        applies = True
    elif scope == "agent-lanes":
        applies = host in set(model.get("agent_lane_hosts") or [])
    else:
        raise ValueError(
            f"ssot.mcp.yml: server {name!r} has unsupported scope {scope!r}")
    return applies


def declared_for_host(ssot: dict, host: str) -> dict:
    """Declared server rows in scope for a host, with per_host overrides."""
    fleet = observation_config(ssot)
    rows = {}
    for name, spec in (ssot.get("servers") or {}).items():
        if not isinstance(spec, dict):
            continue
        if not in_scope(fleet, name, spec, host):
            continue
        row = dict(spec)
        override = (row.get("per_host") or {}).get(host)
        if isinstance(override, dict):
            row.update(override)
        elif override is not None:
            row["implementation"] = override
        rows[name] = {
            "status": str(row.get("status") or "unknown"),
            "implementation": redact(str(row.get("implementation") or "")),
            "transport": "http" if row.get("url") else (
                "stdio" if row.get("implementation") else "unknown"),
        }
    return rows


def finding_id(host: str, kind: str) -> str:
    """Stable across daily runs: one finding per host+kind, not per name set."""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{host}-{kind}".lower()).strip("-")
    return f"mcp-{slug}"


def triage_for(fleet: dict, fid: str, today: str) -> dict:
    """Annotate a finding with human-owned triage; never write it back."""
    states = set(fleet.get("finding_states") or
                 ["open", "carded", "suppressed"])
    record = (fleet.get("finding_triage") or {}).get(fid) or {}
    state = str(record.get("state") or "open")
    if state not in states:
        raise ValueError(
            f"ssot.mcp.yml: finding {fid!r} has invalid triage state {state!r}")
    result = {"state": state, "reason": str(record.get("reason") or ""),
              "card": str(record.get("card") or ""),
              "by": str(record.get("by") or ""),
              "until": str(record.get("until") or "")}
    if state == "suppressed":
        if not result["reason"]:
            raise ValueError(
                f"ssot.mcp.yml: suppressed finding {fid!r} needs a reason")
        if result["until"] and result["until"] < today:
            result["state"] = "open"
            result["expired"] = True
    return result


def make_finding(fleet: dict, host: str, kind: str, severity: str,
                 detail: str, servers: list[str], today: str) -> dict:
    fid = finding_id(host, kind)
    return {"id": fid, "host": host, "kind": kind, "severity": severity,
            "detail": detail, "servers": sorted(servers),
            "triage": triage_for(fleet, fid, today)}


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
    fleet = observation_config(ssot)
    today = datetime.now().astimezone().date().isoformat()
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    configs, reachable = read_configs(host)
    procs = running_processes(host) if reachable else []
    declared = declared_for_host(ssot, host)
    configured = sorted({s for c in configs.values() for s in c["servers"]})

    missing = sorted(set(declared) - set(configured))
    extra = sorted(set(configured) - set(declared))
    # Only the statuses declared in SSOT are expected to be configured;
    # retired-*/blocked declarations are not findings.
    expected = set(fleet.get("expected_statuses") or ["operational"])
    active_declared = sorted(
        n for n, s in declared.items() if s["status"] in expected
    )
    missing_active = sorted(set(active_declared) - set(configured))

    findings = []
    if not reachable:
        status = "unreachable"
        summary = f"{host}: no config surfaces answered (SSH/probe failed)"
        # An unprobed host has no observed configuration — reporting its
        # servers as "missing" would be a false finding.
        missing_active = []
        findings.append(make_finding(
            fleet, host, "host-unreachable", "warn",
            "host did not answer its SSH/config probes; nothing observed",
            [], today))
    elif not configured:
        status = "no-config"
        summary = f"{host}: reachable, no MCP client configs present (0 configured)"
        # An infra host without agent configs is not a declaration drift:
        # global agent-lane entries are not expected there.
        missing_active = []
    elif missing_active:
        status = "delta"
        summary = (f"{host}: {len(configured)} configured, "
                   f"{len(missing_active)} in-scope active servers absent")
        findings.append(make_finding(
            fleet, host, "missing-active", "warn",
            "active servers declared in scope but absent from config surfaces",
            missing_active, today))
    elif not active_declared:
        status = "ok"
        summary = (f"{host}: {len(configured)} configured, no servers in scope "
                   "(informational — not an agent-lane host)")
    else:
        status = "ok"
        summary = (f"{host}: {len(configured)} configured, "
                   f"{len(active_declared)} in-scope active present")

    if reachable and extra:
        findings.append(make_finding(
            fleet, host, "undeclared-configured", "info",
            "configured on a client surface but not declared for this host",
            extra, today))

    scope = {
        "default": str((fleet.get("scope_model") or {}).get("default") or
                       "agent-lanes"),
        "agent_lane": host in set((fleet.get("scope_model") or {}).get(
            "agent_lane_hosts") or []),
        "declared_in_scope": len(declared),
        "active_in_scope": len(active_declared),
    }
    artifact = {
        "node": f"mcp-inventory/{host}",
        "host": host,
        "observed_at": now_iso(),
        "ssh_name": ssh_name(host),
        "scope": scope,
        "declared_count": len(declared),
        "active_declared": active_declared,
        "configured_count": len(configured),
        "configured": configured,
        "missing_declared": missing,
        "missing_active": missing_active,
        "undeclared_configured": extra,
        "findings": findings,
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
        purpose="Observed MCP inventory, scoped declaration drift and triaged findings",
        generated_by=f"scripts/mcp-inventory.py --host {host}",
        status=status,
        summary=summary,
        sources=[str(art_path.relative_to(REPO)),
                 "docs/ssot/infrastructure/ssot.mcp.yml"],
        extra={
            "configured": len(configured),
            "declared": len(declared),
            "scope": scope,
            "missing_active": missing_active,
            "undeclared_configured": extra,
            "findings": findings,
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
        extra = meta.get("extra") or {}
        rows.append({
            "host": host,
            "status": meta.get("status", "missing"),
            "summary": meta.get("summary", ""),
            "generated_at": meta.get("generated_at", ""),
            "configured": extra.get("configured", 0),
            "declared": extra.get("declared", 0),
            "scope": extra.get("scope") or {},
            "missing_active": extra.get("missing_active") or [],
            "findings": extra.get("findings") or [],
        })

    registry = load_yaml_safe(REPO / "docs" / "ssot" / "infrastructure"
                              / "ssot.reports.yml")
    node = next((n for n in (registry.get("nodes") or [])
                 if n.get("id") == "mcp-fleet"), {})
    inputs = inputs_snapshot(node, registry)

    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    findings = [f for r in rows for f in r["findings"]]
    triage_counts = {}
    for f in findings:
        state = str((f.get("triage") or {}).get("state") or "open")
        triage_counts[state] = triage_counts.get(state, 0) + 1
    drift = [r for r in rows if r["status"] in ("delta", "unreachable", "error")]
    # "no-config" is informational: the host answered but runs no agent lane.
    status = "delta" if drift else "ok"
    headline = (f"{len(rows)} hosts observed; "
                f"{len(drift)} with findings "
                f"({', '.join(f'{k}={v}' for k, v in sorted(counts.items()))}); "
                f"{len(findings)} findings "
                f"({', '.join(f'{k}={v}' for k, v in sorted(triage_counts.items()))})")

    fleet = observation_config(ssot)
    model = fleet.get("scope_model") or {}
    agent_lanes = ", ".join(model.get("agent_lane_hosts") or []) or "none"
    named = ", ".join(
        f"{name} -> {','.join(spec['scope'])}"
        for name, spec in (ssot.get("servers") or {}).items()
        if isinstance(spec, dict) and isinstance(spec.get("scope"), list)
    ) or "none"
    expected = ", ".join(fleet.get("expected_statuses") or []) or "none"

    generated_at = now_iso()
    md = ["# Fleet MCP Inventory Report", "",
          f"_Generated: {generated_at}_  ",
          "_Source: scripts/mcp-inventory.py --consolidate (SSOT: ssot.mcp.yml)_",
          "", "## Headline", "", headline, "",
          "## Scope model", "",
          f"- Default scope: `{model.get('default') or 'agent-lanes'}`; "
          f"agent-lane hosts: `{agent_lanes}`.",
          f"- Named-host exceptions: `{named}`.",
          f"- Expected declaration statuses: `{expected}`; other statuses "
          "(retired/blocked) are never counted as missing.",
          "",
          "## Per-host state", "",
          "| Host | Status | Configured | In scope | Summary |",
          "|---|---|---:|---:|---|"]
    wiki = ["= Fleet MCP Inventory Report =", "",
            f"_Generated: {generated_at}_", "",
            "Source: <code>scripts/mcp-inventory.py --consolidate</code> "
            "(SSOT: <code>ssot.mcp.yml</code>).", "",
            "== Headline ==", "", headline, "",
            "== Scope model ==", "",
            f"* Default scope: <code>{model.get('default') or 'agent-lanes'}</code>; "
            f"agent-lane hosts: <code>{agent_lanes}</code>.",
            f"* Named-host exceptions: <code>{named}</code>.",
            f"* Expected declaration statuses: <code>{expected}</code>; other "
            "statuses (retired/blocked) are never counted as missing.", "",
            "== Per-host state ==", "",
            '{| class="wikitable"',
            "! Host !! Status !! Configured !! In scope !! Summary"]
    for r in rows:
        in_scope_n = (r["scope"] or {}).get("active_in_scope", 0)
        md.append(f"| {r['host']} | {r['status']} | {r['configured']} | "
                  f"{in_scope_n} | {r['summary']} |")
        wiki.append("|-")
        wiki.append(f"| {r['host']} || {r['status']} || {r['configured']} "
                    f"|| {in_scope_n} || {r['summary']}")
    wiki.append("|}")
    md += ["", "## Findings", "",
           "Triage state is human-owned in ssot.mcp.yml "
           "(open | carded | suppressed); producers only annotate it.", ""]
    wiki += ["", "== Findings ==", "",
             "Triage state is human-owned in <code>ssot.mcp.yml</code> "
             "(open | carded | suppressed); producers only annotate it.", ""]
    if findings:
        for f in findings:
            t = f.get("triage") or {}
            state = str(t.get("state") or "open")
            sev = str(f.get("severity") or "info")
            servers = ", ".join(f.get("servers") or []) or "none"
            tail = ""
            if t.get("card"):
                tail += f"; card: {t['card']}"
            if t.get("reason"):
                tail += f"; reason: {t['reason']}"
            if t.get("until"):
                tail += f"; until: {t['until']}"
            if t.get("expired"):
                tail += "; suppression expired -> open"
            md.append(f"- `{f['id']}` — **{state}**/{sev} — {f['host']}: "
                      f"{f['detail']} — servers: `{servers}`{tail}")
            wiki.append(f"* <code>{f['id']}</code> — '''{state}'''/{sev} — "
                        f"{f['host']}: {f['detail']} — servers: "
                        f"<code>{servers}</code>{tail}")
    else:
        md.append("_No findings in this run._")
        wiki.append("_No findings in this run._")

    L2_DIR.mkdir(parents=True, exist_ok=True)
    art = L2_DIR / "MCP-FLEET-REPORT.md"
    art.write_text("\n".join(md) + "\n")
    wiki_art = L2_DIR / "MCP-FLEET-REPORT.wiki"
    wiki_art.write_text("\n".join(wiki) + "\n")
    write_meta(
        L2_DIR / "meta.yml",
        node="mcp-fleet",
        layer="L2-domain",
        purpose="Cross-host MCP inventory drift, scoped declarations and triaged findings",
        generated_by="scripts/mcp-inventory.py --consolidate",
        status=status,
        summary=headline,
        sources=[str(a.relative_to(REPO)) for a in
                 sorted(L1_DIR.glob("*.yml")) if a.name.startswith("meta.")],
        children=[f"mcp-inventory/{h}" for h in hosts],
        inputs_at=inputs,
        extra={"hosts": len(rows), "counts": counts,
               "triage_counts": triage_counts,
               "finding_ids": [f["id"] for f in findings],
               "chars": len("\n".join(md))},
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
# the coordination card as an audit trail. Infrastructure: host pages go
# through POST /wiki/page — that prefix is allowlisted there since card
# wiki-page-door-infrastructure-namespace.
BOARD_API = os.environ.get(
    "BOARD_API_URL", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
WIKI_TITLE = os.environ.get(
    "MCP_FLEET_WIKI_TITLE", "Reports:Fleet-MCP-Inventory")
CARD_ID = os.environ.get(
    "MCP_FLEET_CARD_ID", "fleet-mcp-inventory-report-wiki-edu")


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
