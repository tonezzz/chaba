#!/usr/bin/env python3
"""Sync the Chaba repo's KB into a single NotebookLM notebook, incrementally."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path.home() / "CascadeProjects" / "chaba"
SSOT_VALUES = REPO / "docs" / "ssot" / "infrastructure" / "ssot.values.yml"


def _load_ssot_values():
    if not SSOT_VALUES.exists():
        return {}
    with open(SSOT_VALUES, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_SYNC = _load_ssot_values().get("notebooklm", {}).get("sync", {})

NOTEBOOK_ID = os.environ.get("NOTEBOOKLM_KB_NOTEBOOK") or _SYNC.get(
    "notebook_id", "fdfd3483-6b7e-4cb0-85f3-7f060698769c"
)
CHUNK_FILES = _SYNC.get("chunk_files", 40)
MIN_KB_GROUP = _SYNC.get("min_kb_group", 5)
MANIFEST_PATH = REPO / _SYNC.get("manifest", "data/notebooklm-kb-sync-manifest.yml")


def run(cmd, **kwargs):
    return subprocess.run(cmd, text=True, capture_output=True, check=True, **kwargs)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def nlm_source_list():
    out = run(["nlm", "source", "list", NOTEBOOK_ID, "--json"], timeout=60).stdout
    return json.loads(out)


def nlm_source_delete(source_id):
    run(["nlm", "source", "delete", source_id, "--confirm"], timeout=60)


def nlm_add(local_path, title):
    out = run(["nlm-add", NOTEBOOK_ID, str(local_path), "-t", title], timeout=600).stdout
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
    with open(out_file, "w", encoding="utf-8") as out:
        for f in sorted(files):
            p = Path(f)
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                print(f"  skip {p}: {e}")
                continue
            out.write(f"\n\n===== {p.relative_to(REPO)} =====\n\n")
            out.write(text)


def chunk_and_merge(group_name, files, workdir):
    paths = []
    files = list(files)
    if not files:
        return paths
    for i in range(0, len(files), CHUNK_FILES):
        chunk = files[i:i + CHUNK_FILES]
        suffix = f"-{i // CHUNK_FILES + 1}" if len(files) > CHUNK_FILES else ""
        out_file = workdir / f"{group_name}{suffix}.txt"
        merge_group(group_name, chunk, out_file)
        paths.append((f"{group_name}{suffix}", out_file))
    return paths


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

    # merge small flat categories into misc
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
        for i in range(0, len(gfiles), CHUNK_FILES):
            chunk = gfiles[i:i + CHUNK_FILES]
            suffix = f"-{i // CHUNK_FILES + 1}" if len(gfiles) > CHUNK_FILES else ""
            out_file = workdir / f"kb-{cat}{suffix}.txt"
            merge_group(f"kb-{cat}", chunk, out_file)
            paths.append((f"kb-{cat}{suffix}", out_file))
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


def build_chunks(workdir):
    infrastructure = sorted((REPO / "docs" / "ssot" / "infrastructure").glob("*.yml"))
    apps = sorted((REPO / "docs" / "ssot" / "apps").glob("*.yml"))
    sstop = sorted((REPO / "docs" / "ssot").glob("ssot*.yml"))
    kb_md = sorted((REPO / "docs" / "kb").rglob("*.md"))
    kb_yml = sorted((REPO / "docs" / "kb").rglob("*.yml"))
    agents = [REPO / "AGENTS.md"] if (REPO / "AGENTS.md").exists() else []
    readme = [REPO / "README.md"] if (REPO / "README.md").exists() else []

    merged = []
    merged.extend(chunk_and_merge("infrastructure", infrastructure, workdir))
    merged.extend(chunk_and_merge("ssot-apps", apps, workdir))
    merged.extend(chunk_and_merge("ssot-top", sstop, workdir))
    merged.extend(chunk_kb_by_category(kb_md + kb_yml, workdir))
    merged.extend(chunk_and_merge("AGENTS", agents, workdir))
    merged.extend(chunk_and_merge("README", readme, workdir))
    return merged


def plan_sync(chunks, manifest):
    desired = []
    for title, p in chunks:
        desired.append({
            "title": title,
            "path": p,
            "sha256": sha256_file(p),
            "size": p.stat().st_size,
        })

    old_by_title = {s["title"]: s for s in manifest.get("sources", []) if s.get("title")}
    desired_by_title = {d["title"]: d for d in desired}

    unchanged = []
    to_add = []
    to_update = []
    to_delete = []

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

    return to_add, to_update, to_delete, unchanged


def main():
    parser = argparse.ArgumentParser(description="Sync the Chaba repo's KB into a single NotebookLM notebook.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without touching NotebookLM.")
    parser.add_argument("--force", action="store_true", help="Full refresh: delete and re-add all sources.")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="nlm-kb-sync-") as tmp:
        workdir = Path(tmp)
        chunks = build_chunks(workdir)

        print(f"Prepared {len(chunks)} merged source files:")
        for title, p in chunks:
            print(f"  {title}: {p.stat().st_size} bytes")

        manifest = load_manifest()
        to_add, to_update, to_delete, unchanged = plan_sync(chunks, manifest)

        print(f"\nPlan: {len(to_add)} add, {len(to_update)} update, {len(to_delete)} delete, {len(unchanged)} unchanged")

        if args.dry_run:
            print("\nDry run; no changes.")
            for d in to_add:
                print(f"  would add: {d['title']} ({d['size']} bytes)")
            for d in to_update:
                print(f"  would update: {d['title']} ({d['size']} bytes)")
            for s in to_delete:
                print(f"  would delete: {s['title']} ({s.get('source_id')})")
            for d in unchanged:
                print(f"  unchanged: {d['title']}")
            return

        full_refresh = args.force or not manifest.get("sources")
        if full_refresh:
            print("\nFull refresh: listing and deleting all existing sources...")
            try:
                existing = nlm_source_list()
                print(f"Found {len(existing)} existing sources. Deleting...")
                for src in existing:
                    sid = src["id"]
                    title = src.get("title", sid)
                    try:
                        nlm_source_delete(sid)
                        print(f"  deleted {title} ({sid})")
                    except Exception as e:
                        print(f"  failed to delete {title}: {e}", file=sys.stderr)
            except Exception as e:
                print(f"  failed to list/delete existing sources: {e}", file=sys.stderr)
            to_add = [d for _, d in chunks]
            to_add = [{"title": t, "path": p, "sha256": sha256_file(p), "size": p.stat().st_size} for t, p in chunks]
            to_update = []
            to_delete = []
            unchanged = []

        # Delete removed or updated sources first
        for s in to_delete + to_update:
            sid = s.get("old_source_id") or s.get("source_id")
            if not sid:
                continue
            try:
                nlm_source_delete(sid)
                print(f"  deleted {s['title']} ({sid})")
            except Exception as e:
                print(f"  failed to delete {s['title']}: {e}", file=sys.stderr)

        # Add new and updated sources
        new_sources = list(unchanged)
        for d in to_add + to_update:
            try:
                info = nlm_add(d["path"], d["title"])
                new_sources.append({
                    "title": d["title"],
                    "sha256": d["sha256"],
                    "source_id": info["source_id"],
                    "drive_id": info["drive_id"],
                    "drive_name": info["drive_name"],
                    "size": d["size"],
                })
                print(f"  added {d['title']} ({info['source_id']})")
            except Exception as e:
                print(f"  failed to add {d['title']}: {e}", file=sys.stderr)

        save_manifest(new_sources)
        print(f"\nNotebook {NOTEBOOK_ID} KB sync complete.")


if __name__ == "__main__":
    main()
