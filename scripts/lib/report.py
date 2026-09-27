#!/usr/bin/env python3
"""Shared helpers for the layered reporting standard.

Implements the producer side of docs/ssot/infrastructure/ssot.reports.yml:
meta.yml writers, the append-only timeline, and registry resolution used
by scripts/report-system.py to compute observed node state.

Timeline lives outside the repo (it grows forever): ~/var/chaba/reports/
unless CHABA_REPORTS_DIR is set.
"""
from __future__ import annotations

import datetime
import fnmatch
import json
import os
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO / "docs" / "ssot" / "infrastructure" / "ssot.reports.yml"
REPORTS_ROOT = Path(
    os.environ.get("CHABA_REPORTS_DIR", "~/var/chaba/reports")
).expanduser()
TIMELINE_PATH = REPORTS_ROOT / "timeline.jsonl"

STATUSES = (
    "ok", "delta", "stale", "error",
    "missing", "untracked", "remote", "planned",
)

_CADENCE_UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
_CADENCE_WORDS = {
    "hourly": 3600, "daily": 86400, "weekly": 604800,
}


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def parse_cadence(value) -> float | None:
    """'24h' / '7d' / '10m' / 'daily' -> seconds. None if unparseable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    if s in _CADENCE_WORDS:
        return float(_CADENCE_WORDS[s])
    try:
        return float(s)
    except ValueError:
        pass
    num, unit = s[:-1], s[-1]
    if unit in _CADENCE_UNITS:
        try:
            return float(num) * _CADENCE_UNITS[unit]
        except ValueError:
            return None
    return None


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text()) or {}


def registry_nodes(path: Path = REGISTRY_PATH) -> list[dict]:
    return load_registry(path).get("nodes") or []


def _resolve_repo_path(value: str | None) -> Path | None:
    if not value:
        return None
    p = Path(value).expanduser()
    return p if p.is_absolute() else REPO / p


def write_meta(meta_path, *, node: str, layer: str, generated_by: str,
               status: str, purpose: str | None = None, summary: str = "",
               sources=None, children=None, extra=None) -> Path:
    """Write a node's meta.yml (canonical writer per ssot.reports.yml)."""
    meta_path = Path(meta_path).expanduser()
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "node": node,
        "layer": layer,
        "purpose": purpose,
        "generated_by": generated_by,
        "generated_at": now_iso(),
        "status": status,
        "summary": summary,
        "sources": list(sources or []),
        "children": list(children or []),
        "extra": dict(extra or {}),
    }
    meta_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return meta_path


def append_timeline(node: str, layer: str, status: str, summary: str = "",
                    ref=None, timeline: Path = TIMELINE_PATH) -> Path:
    """Append one event to the shared reports timeline (JSONL)."""
    timeline = Path(timeline).expanduser()
    timeline.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": now_iso(),
        "node": node,
        "layer": layer.replace("-producer", "").replace("-domain", "")
                  .replace("-overview", "").replace("-raw", ""),
        "status": status,
        "summary": summary,
    }
    if ref:
        event["ref"] = str(ref)
    with open(timeline, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return timeline


def latest_artifact(output_dir, pattern: str | None = None) -> Path | None:
    """Newest file matching pattern in output_dir (mtime order)."""
    d = _resolve_repo_path(str(output_dir)) if output_dir else None
    if not d or not d.is_dir():
        return None
    files = [p for p in d.iterdir() if p.is_file()]
    if pattern:
        files = [p for p in files if fnmatch.fnmatch(p.name, pattern)]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _is_stale(last_run_iso: str | None, cadence) -> bool:
    seconds = parse_cadence(cadence)
    if not seconds or not last_run_iso:
        return False
    try:
        last = datetime.datetime.fromisoformat(str(last_run_iso))
    except ValueError:
        return False
    if last.tzinfo is None:
        last = last.astimezone()
    age = (datetime.datetime.now().astimezone() - last).total_seconds()
    return age > seconds


def resolve_node(node: dict) -> dict:
    """Observed state for a registry node.

    Precedence: registry `state: planned` -> planned; meta.yml present ->
    its status (stale overrides ok/delta when past cadence); observe=remote
    -> remote; artifacts present without meta -> untracked (or stale);
    otherwise missing.
    """
    out = {
        "id": node.get("id"),
        "layer": node.get("layer"),
        "purpose": node.get("purpose"),
        "status": "missing",
        "last_run": None,
        "summary": "",
        "meta_path": None,
        "artifact": None,
    }
    if node.get("state") == "planned":
        out["status"] = "planned"
        return out
    if node.get("observe") == "remote":
        out["status"] = "remote"
        return out

    meta_path = _resolve_repo_path(node.get("meta"))
    artifact = latest_artifact(node.get("output"), node.get("artifact_pattern"))
    cadence = node.get("cadence")

    if meta_path and meta_path.is_file():
        out["meta_path"] = str(meta_path)
        try:
            meta = yaml.safe_load(meta_path.read_text()) or {}
        except Exception as e:
            out["status"] = "error"
            out["summary"] = f"meta unreadable: {e}"
            return out
        out["last_run"] = meta.get("generated_at")
        out["summary"] = meta.get("summary") or ""
        status = meta.get("status") or "ok"
        if status in ("ok", "delta") and _is_stale(out["last_run"], cadence):
            status = "stale"
        out["status"] = status if status in STATUSES else "error"
        out["artifact"] = str(artifact) if artifact else None
        return out

    if artifact:
        out["artifact"] = str(artifact)
        mtime = datetime.datetime.fromtimestamp(
            artifact.stat().st_mtime).astimezone()
        out["last_run"] = mtime.isoformat(timespec="seconds")
        out["status"] = "stale" if _is_stale(out["last_run"], cadence) else "untracked"
        return out

    return out


def resolve_all(nodes: list[dict]) -> list[dict]:
    return [resolve_node(n) for n in nodes]


def _emit_cli(argv: list[str] | None = None) -> int:
    """CLI entry point so shell producers can emit meta+timeline without
    importing this module::

        python3 scripts/lib/report.py emit \
            --node health-monitor --layer L1-producer \
            --meta ~/var/chaba/health/meta.yml \
            --status ok --summary "9/9 healthy" \
            --generated-by "scripts/tony-dell-monitor.sh" \
            [--purpose "..."] [--source f.json]... [--child id]... \
            [--extra-json '{"k": v}'] [--ref artifact]
    """
    import argparse

    p = argparse.ArgumentParser(prog="report.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("emit", help="Write a node meta.yml + append a timeline event")
    e.add_argument("--node", required=True)
    e.add_argument("--layer", required=True)
    e.add_argument("--meta", required=True, help="meta.yml output path")
    e.add_argument("--status", required=True, choices=STATUSES)
    e.add_argument("--summary", default="")
    e.add_argument("--purpose", default=None)
    e.add_argument("--generated-by", required=True)
    e.add_argument("--source", dest="sources", action="append", default=[])
    e.add_argument("--child", dest="children", action="append", default=[])
    e.add_argument("--extra-json", default=None,
                   help="JSON object merged into meta.extra")
    e.add_argument("--ref", default=None, help="primary artifact path")
    args = p.parse_args(argv)

    extra = {}
    if args.extra_json:
        try:
            extra = json.loads(args.extra_json)
        except json.JSONDecodeError as ex:
            print(f"emit: bad --extra-json: {ex}", file=sys.stderr)
            return 2

    write_meta(args.meta, node=args.node, layer=args.layer,
               generated_by=args.generated_by, status=args.status,
               purpose=args.purpose, summary=args.summary,
               sources=args.sources, children=args.children, extra=extra)
    append_timeline(args.node, args.layer, args.status, args.summary,
                    ref=args.ref)
    print(f"meta -> {args.meta}")
    return 0


if __name__ == "__main__":
    sys.exit(_emit_cli())
