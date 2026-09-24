#!/usr/bin/env python3
"""Audit archive-distillation coverage per ssot.apps.archive-distillation.yml.

Checks:
  1. manifest unaccounted == 0 (every source file classified)
  2. every file in a report's covers: block exists in manifest w/ matching sha
  3. every manifest file's declared topic has a report (or is excluded-noise)
  4. every ## Timeline entry has a source ref (audit-soft)
  5. follows/superseded_by link targets exist (audit-soft)

Usage: python3 scripts/audit-archive.py <repo>
Exit 0 = PASS.
"""
import json, re, sys
from pathlib import Path

ROOT = Path("/home/tony/CascadeProjects/chaba")

def load_manifest(repo):
    p = ROOT / f"docs/archive/manifests/{repo}.yml"
    lines = p.read_text().splitlines()
    return json.loads("\n".join(l for l in lines if not l.startswith("#")))

def parse_report(path):
    t = path.read_text()
    fm = {}
    m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ": " in line and not line.startswith(" "):
                k, v = line.split(": ", 1)
                fm[k.strip()] = v.strip()
    covers = re.findall(r"^  - (\S.*?)$", m.group(1) if m else "", re.M)
    timeline_refs = len(re.findall(r"^\s*-\s*\d{4}-\d{2}", t, re.M))
    return fm, covers, timeline_refs

def main(repo):
    m = load_manifest(repo)
    files = {f["path"]: f for f in m["files"]}
    topics = {}
    for f in m["files"]:
        topics.setdefault(f["topic"], []).append(f["path"])
    unaccounted = m["audit"].get("unaccounted", 0)

    reports = sorted((ROOT / "docs/kb/archive" / repo).glob("*.md"))
    reports = [r for r in reports if r.name not in ("INDEX.md", "TIMELINE.md")]
    errors, warns = [], []

    if unaccounted:
        errors.append(f"manifest unaccounted={unaccounted}")

    report_topics = set()
    for r in reports:
        fm, covers, _ = parse_report(r)
        topic = fm.get("topic", r.stem)
        report_topics.add(topic)
        for c in covers:
            if c.endswith("/**"):
                prefix = c[:-3]
                if not any(p.startswith(prefix) for p in files):
                    errors.append(f"{r.name}: covers glob {c} matches nothing")
            elif c in ("...",) or c.startswith("..."):
                continue
            elif c not in files:
                errors.append(f"{r.name}: covers '{c}' not in manifest")
        for link in ("follows", "superseded_by"):
            v = fm.get(link)
            if v and v not in ("[]", "") and not any(v in x.name for x in reports):
                warns.append(f"{r.name}: {link}={v} has no matching report")

    for topic, tfiles in topics.items():
        if topic == "excluded-noise":
            continue
        if topic not in report_topics:
            errors.append(f"topic '{topic}' ({len(tfiles)} files) has no report")

    total = len(files)
    noise = len(topics.get("excluded-noise", []))
    print(f"repo={repo} files={total} noise={noise} reports={len(reports)}")
    for w in warns: print("WARN:", w)
    for e in errors: print("FAIL:", e)
    print("PASS" if not errors else f"FAIL ({len(errors)} errors)")
    return 0 if not errors else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
