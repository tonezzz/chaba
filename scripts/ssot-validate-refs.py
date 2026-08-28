#!/usr/bin/env python3
"""Validate SSOT ref, *_ref, and source_ref pointers across docs/ssot/."""

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML is required: pip install pyyaml")

REPO = Path(__file__).resolve().parent.parent
SSOT_DIRS = [REPO / "docs" / "ssot"]

# Key suffixes treated as references
REF_SUFFIXES = ("_ref", "ref", "source_ref")


def is_ref_key(key):
    if not isinstance(key, str):
        return False
    return key == "ref" or key.endswith("_ref")


def all_ssot_files():
    files = {}
    for d in SSOT_DIRS:
        for path in d.rglob("*.yml"):
            rel = path.relative_to(REPO).as_posix()
            try:
                files[rel] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                print(f"YAML_ERROR {rel}: {e}")
                files[rel] = None
    return files


def get_path(obj, parts):
    for p in parts:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(p)
        if obj is None:
            return None
    return obj


def is_placeholder(ref):
    return not ref or "<" in ref or ">" in ref or "..." in ref or "*" in ref


def normalize_target(target, source_rel):
    if not target:
        return source_rel
    if target.startswith("/") or target.startswith(".."):
        return None  # external, not validated
    if target.startswith("./"):
        target = target[2:]
    # If the ref starts with docs/ssot/, use that; otherwise assume relative to REPO root
    if target.startswith("docs/ssot/"):
        return target
    return f"docs/ssot/{target}"


def is_pointer(ref):
    return ".yml" in ref or "#" in ref or ref.startswith("docs/ssot/") or ("/" in ref and Path(ref).suffix)


def resolve_ref(ref, source_rel, all_files):
    if not isinstance(ref, str):
        return None
    if is_placeholder(ref):
        return None
    if ".yml" in ref:
        if "#" in ref:
            target, _, path = ref.partition("#")
        else:
            target = ref
            path = ""
    elif "#" in ref:
        target, _, path = ref.partition("#")
    elif "/" in ref and (ref.startswith("docs/") or ref.startswith("reports/") or ref.startswith("scripts/")):
        # repo-relative file path to a non-SSOT file (e.g., kb_ref, plan_ref)
        target = ref
        path = ""
        if not (REPO / target).exists():
            return f"missing file: {target}"
        return None
    elif "/" in ref or ref.startswith("."):
        # file path without #, treat as file-only reference
        target = ref
        path = ""
    else:
        # bare dotted key path in the same file or an ID reference
        if "." in ref:
            target = ""
            path = ref
        else:
            # likely an ID like overnight-assessment-2026-08-04; skip
            return None

    target = normalize_target(target, source_rel)
    if target is None:
        return None  # external
    if target not in all_files:
        return f"missing file: {target}"
    doc = all_files[target]
    if doc is None:
        return f"unparseable file: {target}"
    if path:
        parts = path.split(".")
        value = get_path(doc, parts)
        if value is None:
            return f"missing key '{path}' in {target}"
    return None


def scan_refs(obj, source_rel, all_files, found=None):
    if found is None:
        found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if is_ref_key(key):
                refs = value if isinstance(value, list) else [value]
                for r in refs:
                    found.append((source_rel, key, r))
            else:
                scan_refs(value, source_rel, all_files, found)
    elif isinstance(obj, list):
        for item in obj:
            scan_refs(item, source_rel, all_files, found)
    return found


def main():
    all_files = all_ssot_files()
    errors = []
    for rel, doc in all_files.items():
        if doc is None:
            continue
        for src, key, ref in scan_refs(doc, rel, all_files):
            error = resolve_ref(ref, src, all_files)
            if error:
                errors.append(f"{src}: {key}={ref!r} -> {error}")

    if errors:
        print("=== SSOT ref validation errors ===")
        for e in errors:
            print(e)
        print(f"\n{len(errors)} error(s)")
        return 1
    print(f"OK: {len(all_files)} SSOT file(s) parsed; no broken refs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
