#!/usr/bin/env python3
"""Sync the Chaba repo's KB into a single NotebookLM notebook."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path.home() / "CascadeProjects" / "chaba"
NOTEBOOK_ID = os.environ.get("NOTEBOOKLM_KB_NOTEBOOK", "fdfd3483-6b7e-4cb0-85f3-7f060698769c")
CHUNK_FILES = 40


def run(cmd, **kwargs):
    return subprocess.run(cmd, text=True, capture_output=True, check=True, **kwargs)


def nlm_source_list():
    out = run(["nlm", "source", "list", NOTEBOOK_ID, "--json"], timeout=60).stdout
    return json.loads(out)


def nlm_source_delete(source_id):
    run(["nlm", "source", "delete", source_id, "--confirm"], timeout=60)


def nlm_add(local_path, title):
    run(["nlm-add", NOTEBOOK_ID, str(local_path), "-t", title], timeout=600)


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


def main():
    with tempfile.TemporaryDirectory(prefix="nlm-kb-sync-") as tmp:
        workdir = Path(tmp)

        # Collect files
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
        merged.extend(chunk_and_merge("kb", kb_md + kb_yml, workdir))
        merged.extend(chunk_and_merge("AGENTS", agents, workdir))
        merged.extend(chunk_and_merge("README", readme, workdir))

        print(f"Prepared {len(merged)} merged source files:")
        for title, p in merged:
            print(f"  {title}: {p.stat().st_size} bytes")

        # Clear old sources
        print("Listing existing sources...")
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

        # Add new sources
        print("Adding new sources...")
        for title, p in merged:
            try:
                nlm_add(p, title)
                print(f"  added {title}")
            except Exception as e:
                print(f"  failed to add {title}: {e}", file=sys.stderr)

        print(f"\nNotebook {NOTEBOOK_ID} KB sync complete.")


if __name__ == "__main__":
    main()
