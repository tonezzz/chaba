#!/usr/bin/env python3
"""Sync the Chaba repo's KB into a single NotebookLM notebook, incrementally."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import yaml

REPO = Path.home() / "CascadeProjects" / "chaba"
SSOT_VALUES = REPO / "docs" / "ssot" / "infrastructure" / "ssot.values.yml"


def _load_ssot_values():
    if not SSOT_VALUES.exists():
        return {}
    with open(SSOT_VALUES, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_NOTEBOOKLM = _load_ssot_values().get("notebooklm", {})
_SYNC = _NOTEBOOKLM.get("sync", {})
_COLLECTION = _NOTEBOOKLM.get("collections", {}).get("chaba", {})
_COLLECTION_PATH = _COLLECTION.get("path", "gdrive:notebooklm/chaba")

NOTEBOOK_ID = os.environ.get("NOTEBOOKLM_KB_NOTEBOOK") or _SYNC.get(
    "notebook_id", "fdfd3483-6b7e-4cb0-85f3-7f060698769c"
)
CHUNK_FILES = _SYNC.get("chunk_files", 40)
MIN_KB_GROUP = _SYNC.get("min_kb_group", 5)
MAX_CHUNK_BYTES = _SYNC.get("max_chunk_bytes", 0)
MAX_WORKERS = _SYNC.get("max_workers", 1)
RETRY_ATTEMPTS = _SYNC.get("retry_attempts", 3)
BACKOFF_BASE = _SYNC.get("backoff_base_seconds", 2)
MANIFEST_PATH = REPO / _SYNC.get("manifest", "data/notebooklm-kb-sync-manifest.yml")
SYNC_LOG = REPO / _SYNC.get("log", "data/notebooklm-kb-sync.ndjson")
DRIVE_ROOT = _COLLECTION_PATH.rstrip("/") + "/notebooks"
RCLONE_REMOTE = _NOTEBOOKLM.get("rclone_remote", "gdrive")
_NLM_ADD_LOCK = threading.Lock()


def _log_sync(record):
    SYNC_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SYNC_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _run_with_retry(cmd, env=None, timeout=60):
    last_err = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                check=True,
                env=env,
                timeout=timeout,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            last_err = e
            if attempt < RETRY_ATTEMPTS - 1:
                wait = BACKOFF_BASE * (2 ** attempt)
                print(
                    f"  retrying {' '.join(str(c) for c in cmd[:3])} in {wait}s "
                    f"(attempt {attempt + 2}/{RETRY_ATTEMPTS})...",
                    file=sys.stderr,
                )
                time.sleep(wait)
            else:
                raise last_err


def run(cmd, **kwargs):
    return _run_with_retry(cmd, **kwargs)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def nlm_source_list():
    out = run(["nlm", "source", "list", NOTEBOOK_ID, "--json"], timeout=120).stdout
    return json.loads(out)


def nlm_source_delete(source_id):
    run(["nlm", "source", "delete", source_id, "--confirm"], timeout=120)


def nlm_add(local_path, title):
    env = os.environ.copy()
    env["NOTEBOOKLM_DRIVE_ROOT"] = DRIVE_ROOT
    env["NOTEBOOKLM_RCLONE_REMOTE"] = RCLONE_REMOTE
    with _NLM_ADD_LOCK:
        out = run(
            ["nlm-add", NOTEBOOK_ID, str(local_path), "-t", title],
            env=env,
            timeout=600,
        ).stdout
    m_drive = re.search(r"Drive file:\s+(\S+)\s+\(([^)]+)\)", out)
    m_source = re.search(r"NLM source:\s+(\S+)", out)
    if not m_source:
        raise RuntimeError(f"Could not parse nlm-add output:\n{out}")
    return {
        "source_id": m_source.group(1),
        "drive_id": m_drive.group(2) if m_drive else None,
        "drive_name": m_drive.group(1) if m_drive else None,
    }


def merge_group(name, files, out_file):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as out:
        for f in sorted(files):
            p = Path(f)
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                print(f"  skip {p}: {e}")
                continue
            try:
                header = p.relative_to(REPO).as_posix()
            except ValueError:
                header = p.as_posix()
            out.write(f"\n\n===== {header} =====\n\n")
            out.write(text)


def chunk_items(group_name, files, workdir):
    files = list(files)
    if not files:
        return []

    if MAX_CHUNK_BYTES and MAX_CHUNK_BYTES > 0:
        chunks = []
        current = []
        current_bytes = 0
        for f in files:
            size = Path(f).stat().st_size
            if current and (current_bytes + size) > MAX_CHUNK_BYTES:
                chunks.append(current)
                current = [f]
                current_bytes = size
            else:
                current.append(f)
                current_bytes += size
        if current:
            chunks.append(current)
    else:
        chunks = [files[i:i + CHUNK_FILES] for i in range(0, len(files), CHUNK_FILES)]

    out = []
    for idx, chunk in enumerate(chunks, 1):
        suffix = f"-{idx}" if len(chunks) > 1 else ""
        out_file = workdir / f"{group_name}{suffix}.txt"
        merge_group(group_name, chunk, out_file)
        out.append((f"{group_name}{suffix}", out_file, [str(f) for f in chunk]))
    return out


def kb_category(p):
    rel = p.relative_to(REPO / "docs" / "kb")
    if len(rel.parts) > 1:
        return rel.parts[0].lstrip(".").replace("-", "_")
    stem = p.stem
    if stem.lower() == "readme":
        return "readme"
    if stem.lower().startswith(".template"):
        return "template"
    cat = stem.split("-")[0].lower()
    if not cat:
        return "misc"
    return cat


def chunk_kb_by_category(files, workdir):
    """Group KB files by topic prefix, merge small groups into misc."""
    from collections import defaultdict
    groups = defaultdict(list)
    for f in sorted(files):
        groups[kb_category(f)].append(f)

    misc = []
    final = {}
    for cat, gfiles in groups.items():
        if cat in ("experiments", "home_assistant", "archive") or len(gfiles) >= MIN_KB_GROUP:
            final[cat] = gfiles
        else:
            misc.extend(gfiles)
    if misc:
        final["misc"] = misc

    paths = []
    for cat in sorted(final):
        gfiles = sorted(final[cat])
        paths.extend(chunk_items(f"kb/{cat}", gfiles, workdir))
    return paths


def load_manifest():
    if not MANIFEST_PATH.exists():
        return {"version": 1, "notebook_id": NOTEBOOK_ID, "sources": []}
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or not isinstance(data, dict):
        return {"version": 1, "notebook_id": NOTEBOOK_ID, "sources": []}
    data.setdefault("version", 1)
    data.setdefault("notebook_id", NOTEBOOK_ID)
    data.setdefault("sources", [])
    return data


def save_manifest(sources):
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump({"version": 1, "notebook_id": NOTEBOOK_ID, "sources": sources},
                       f, sort_keys=False, allow_unicode=True)


def _flatten_values(data, prefix=""):
    rows = []
    if isinstance(data, dict):
        for k, v in data.items():
            new_prefix = f"{prefix}.{k}" if prefix else str(k)
            rows.extend(_flatten_values(v, new_prefix))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            rows.extend(_flatten_values(v, f"{prefix}[{i}]"))
    else:
        rows.append(f"{prefix}: {data}")
    return rows


def build_glossary(workdir):
    values = _load_ssot_values()
    out_file = workdir / "meta" / "glossary.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    rows = _flatten_values(values)
    with open(out_file, "w", encoding="utf-8") as out:
        out.write("===== SSOT Values Glossary =====\n\n")
        for line in sorted(rows):
            out.write(line + "\n")
    return [("meta/glossary", out_file, [str(SSOT_VALUES)])]


def build_source_map(sources, workdir):
    out_file = workdir / "meta" / "source-map.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as out:
        out.write("===== NotebookLM Source Map =====\n\n")
        out.write(f"Notebook ID: {NOTEBOOK_ID}\n")
        out.write(f"Sources: {len(sources)}\n\n")
        for s in sorted(sources, key=lambda x: x["title"]):
            out.write(f"title: {s['title']}\n")
            out.write(f"  source_id: {s['source_id']}\n")
            out.write(f"  drive_id: {s.get('drive_id', 'unknown')}\n")
            out.write(f"  drive_name: {s.get('drive_name', 'unknown')}\n")
            out.write(f"  size: {s.get('size', 0)}\n")
            out.write(f"  sha256: {s['sha256']}\n")
            if s.get("files"):
                out.write(f"  files: {len(s['files'])}\n")
                for f in s["files"]:
                    out.write(f"    - {f}\n")
            out.write("\n")
    return out_file


def build_chunks(workdir):
    infrastructure = sorted((REPO / "docs" / "ssot" / "infrastructure").glob("*.yml"))
    apps = sorted((REPO / "docs" / "ssot" / "apps").glob("*.yml"))
    sstop = sorted((REPO / "docs" / "ssot").glob("ssot*.yml"))
    kb_md = sorted((REPO / "docs" / "kb").rglob("*.md"))
    kb_yml = sorted((REPO / "docs" / "kb").rglob("*.yml"))
    agents = [REPO / "AGENTS.md"] if (REPO / "AGENTS.md").exists() else []
    readme = [REPO / "README.md"] if (REPO / "README.md").exists() else []

    merged = []
    merged.extend(build_glossary(workdir))
    merged.extend(chunk_items("ssot/infrastructure", infrastructure, workdir))
    merged.extend(chunk_items("ssot/apps", apps, workdir))
    merged.extend(chunk_items("ssot/top", sstop, workdir))
    merged.extend(chunk_kb_by_category(kb_md + kb_yml, workdir))
    merged.extend(chunk_items("meta/AGENTS", agents, workdir))
    merged.extend(chunk_items("meta/README", readme, workdir))

    # Also sync the separate ada-pi repo's docs so the chaba KB covers its
    # architecture and integrations (e.g. the RK600 weather station).
    ada_pi = Path.home() / "CascadeProjects" / "ada-pi"
    ada_pi_readme = [ada_pi / "README.md"] if (ada_pi / "README.md").exists() else []
    ada_pi_docs = sorted((ada_pi / "docs").rglob("*.md")) if (ada_pi / "docs").exists() else []
    merged.extend(chunk_items("ada-pi", ada_pi_readme + ada_pi_docs, workdir))

    # Other high-signal READMEs that live outside docs/.
    more_docs = []
    for d in [
        REPO / "apps" / "dev" / "v0" / "README.md",
        REPO / "experiments" / "gold-thb-usd-causality" / "app" / "README.md",
        REPO / "experiments" / "meshtastic-th-collector" / "README.md",
        REPO / "mcp-servers" / "mcp-health" / "README.md",
        REPO / "stacks" / "ha-live" / "README.md",
        REPO / "workflows" / "README.md",
    ]:
        if d.exists():
            more_docs.append(d)
    merged.extend(chunk_items("meta/extra", more_docs, workdir))

    return merged


def plan_sync(chunks, manifest, reconcile=False):
    desired = []
    for title, p, files in chunks:
        desired.append({
            "title": title,
            "path": str(p),
            "sha256": sha256_file(p),
            "size": p.stat().st_size,
            "files": files,
        })

    old_by_title = {s["title"]: s for s in manifest.get("sources", []) if s.get("title")}
    desired_by_title = {d["title"]: d for d in desired}

    unchanged = []
    to_add = []
    to_update = []
    to_delete = []
    orphans = []

    for d in desired:
        old = old_by_title.get(d["title"])
        if old and old.get("sha256") == d["sha256"]:
            unchanged.append({**old, "path": d["path"]})
        elif old:
            d["old_source_id"] = old.get("source_id")
            to_update.append(d)
        else:
            to_add.append(d)

    for title, old in old_by_title.items():
        if title not in desired_by_title:
            to_delete.append(old)

    if reconcile:
        try:
            live_sources = nlm_source_list()
            live_ids = {s["id"] for s in live_sources}
            known_ids = {s.get("source_id") for s in manifest.get("sources", []) if s.get("source_id")}
            for d in unchanged[:]:
                if d.get("source_id") not in live_ids:
                    d["old_source_id"] = d.pop("source_id")
                    to_update.append(d)
                    unchanged.remove(d)
            for s in live_sources:
                sid = s["id"]
                if sid not in known_ids:
                    orphans.append({"title": s.get("title", sid), "source_id": sid})
        except Exception as e:
            print(f"  failed to reconcile: {e}", file=sys.stderr)

    return to_add, to_update, to_delete, unchanged, orphans


def _delete_sources(sources):
    deleted = 0
    for s in sources:
        sid = s.get("old_source_id") or s.get("source_id")
        if not sid:
            continue
        try:
            nlm_source_delete(sid)
            print(f"  deleted {s['title']} ({sid})")
            deleted += 1
        except Exception as e:
            print(f"  failed to delete {s['title']}: {e}", file=sys.stderr)
    return deleted


def _add_sources(sources):
    new = []
    errors = 0
    if MAX_WORKERS and MAX_WORKERS > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(nlm_add, d["path"], d["title"]): d for d in sources}
            for fut in concurrent.futures.as_completed(futures):
                d = futures[fut]
                try:
                    info = fut.result()
                    new.append({
                        "title": d["title"],
                        "sha256": d["sha256"],
                        "source_id": info["source_id"],
                        "drive_id": info["drive_id"],
                        "drive_name": info["drive_name"],
                        "size": d["size"],
                        "files": d.get("files", []),
                    })
                    print(f"  added {d['title']} ({info['source_id']})")
                except Exception as e:
                    print(f"  failed to add {d['title']}: {e}", file=sys.stderr)
                    errors += 1
    else:
        for d in sources:
            try:
                info = nlm_add(d["path"], d["title"])
                new.append({
                    "title": d["title"],
                    "sha256": d["sha256"],
                    "source_id": info["source_id"],
                    "drive_id": info["drive_id"],
                    "drive_name": info["drive_name"],
                    "size": d["size"],
                    "files": d.get("files", []),
                })
                print(f"  added {d['title']} ({info['source_id']})")
            except Exception as e:
                print(f"  failed to add {d['title']}: {e}", file=sys.stderr)
                errors += 1
    return new, errors


def main():
    parser = argparse.ArgumentParser(description="Sync the Chaba repo's KB into a single NotebookLM notebook.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without touching NotebookLM.")
    parser.add_argument("--force", action="store_true", help="Full refresh: delete and re-add all sources.")
    parser.add_argument("--reconcile", action="store_true", help="Check live NotebookLM sources and remove orphaned ones.")
    args = parser.parse_args()

    start = time.time()
    with tempfile.TemporaryDirectory(prefix="nlm-kb-sync-") as tmp:
        workdir = Path(tmp)
        chunks = build_chunks(workdir)

        print(f"Prepared {len(chunks)} merged source files:")
        for title, p, files in chunks:
            print(f"  {title}: {p.stat().st_size} bytes ({len(files)} files)")

        manifest = load_manifest()
        to_add, to_update, to_delete, unchanged, orphans = plan_sync(chunks, manifest, reconcile=args.reconcile)

        print(
            f"\nPlan: {len(to_add)} add, {len(to_update)} update, "
            f"{len(to_delete)} delete, {len(unchanged)} unchanged, {len(orphans)} orphan(s)"
        )

        if args.dry_run:
            print("\nDry run; no changes.")
            for d in to_add:
                print(f"  would add: {d['title']} ({d['size']} bytes)")
            for d in to_update:
                print(f"  would update: {d['title']} ({d['size']} bytes)")
            for s in to_delete:
                print(f"  would delete: {s['title']} ({s.get('source_id')})")
            for s in orphans:
                print(f"  would delete orphan: {s['title']} ({s.get('source_id')})")
            for d in unchanged:
                print(f"  unchanged: {d['title']}")
            return

        full_refresh = args.force or not manifest.get("sources")
        if full_refresh:
            print("\nFull refresh: listing and deleting all existing sources...")
            try:
                existing = nlm_source_list()
                print(f"Found {len(existing)} existing sources. Deleting...")
                _delete_sources([{"title": s.get("title", s["id"]), "source_id": s["id"]} for s in existing])
            except Exception as e:
                print(f"  failed to list/delete existing sources: {e}", file=sys.stderr)
            to_add = [{"title": t, "path": str(p), "sha256": sha256_file(p), "size": p.stat().st_size, "files": files} for t, p, files in chunks]
            to_update = []
            to_delete = []
            unchanged = []
            orphans = []

        # Delete removed, updated, and orphaned sources first
        _delete_sources(to_delete + orphans + to_update)

        # Add new and updated sources
        added, add_errors = _add_sources(to_add + to_update)
        new_sources = list(unchanged) + added

        # Build and add a source-map source describing all other sources
        try:
            source_map_file = build_source_map(new_sources, workdir)
            info = nlm_add(source_map_file, "meta/source-map")
            new_sources.append({
                "title": "meta/source-map",
                "sha256": sha256_file(source_map_file),
                "source_id": info["source_id"],
                "drive_id": info["drive_id"],
                "drive_name": info["drive_name"],
                "size": source_map_file.stat().st_size,
            })
            print(f"  added meta/source-map ({info['source_id']})")
        except Exception as e:
            print(f"  failed to add meta/source-map: {e}", file=sys.stderr)
            add_errors += 1

    duration = time.time() - start
    _log_sync({
        "ts": start,
        "duration": round(duration, 3),
        "notebook_id": NOTEBOOK_ID,
        "added": len(to_add),
        "updated": len(to_update),
        "deleted": len(to_delete) + len(orphans),
        "unchanged": len(unchanged),
        "errors": add_errors,
        "force": full_refresh,
        "reconcile": args.reconcile,
    })
    save_manifest(new_sources)
    print(f"\nNotebook {NOTEBOOK_ID} KB sync complete in {duration:.1f}s.")


if __name__ == "__main__":
    main()
