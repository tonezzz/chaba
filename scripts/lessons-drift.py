#!/usr/bin/env python3
"""lessons-drift — source-doc freshness check for the Education store.

A lesson's job is to be current. This read-only audit lists every WP
`lesson` post via board-api /lesson (op=list + op=get — no WP creds
held), extracts repo-path source references from the content, and
compares each source's last git commit date against the lesson's own
freshness stamp (meta.updated, falling back to learned_at / WP
modified).

Flags per lesson:
  drift         a referenced source doc was committed AFTER the lesson
                was last (re)filed — the lesson may be stale
  source-gone   a referenced path no longer exists in the repo
  no-repo-source  content carries no repo-path reference at all
                (informational — chat/voice lessons legitimately have
                none; they are excluded from drift counting but listed)

Usage:
  lessons-drift.py [--repo PATH] [--out FILE.json] [--slugs a,b]
                   [--strict]   # nonzero exit when drift found

Env: BOARD_API (default: dispatch_repos.board_api_base() -> idc03 door).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "board"))
try:
    import dispatch_repos as dr
    API = dr.board_api_base().rstrip("/") + "/lesson"
except Exception:
    API = "https://idc03.taila0626a.ts.net:10000/lesson"

# repo-relative paths a lesson can point at. Deliberately conservative —
# bare filenames (foo.py) are too ambiguous to call a source reference.
SRC_RE = re.compile(
    r"\b((?:docs|scripts|reports|evals|tests|stacks|systemd|apps|web|"
    r"mcp|mcp-servers|integrations|edge|fixtures|workflows)/"
    r"[\w.\-/]+?\.(?:md|yml|yaml|py|sh|json|ts|js|mjs|html|conf|service|"
    r"timer|toml|txt))"
    r"|\b(AGENTS\.md|Justfile|Makefile|README\.md)\b")


def api(body: dict) -> dict:
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read().decode())


def last_commit(repo: Path, rel: str) -> str:
    """YYYY-MM-DD of the newest commit touching rel ('' = never)."""
    r = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%cs", "--", rel],
        capture_output=True, text=True, timeout=30)
    return r.stdout.strip() if r.returncode == 0 else ""


def source_refs(content: str) -> list:
    out = []
    for m in SRC_RE.finditer(content or ""):
        p = (m.group(1) or m.group(2) or "").rstrip(".,;:)\"'")
        if p and p not in out:
            out.append(p)
    return out


def lesson_date(lesson: dict) -> str:
    """The lesson's own freshness stamp — last (re)file date."""
    meta = lesson.get("meta") or {}
    for k in ("updated", "learned_at"):
        if str(meta.get(k) or "").strip():
            return str(meta[k]).strip()[:10]
    return str(lesson.get("modified") or "")[:10]


def audit_lesson(repo: Path, slug: str, lesson: dict, ldate: str) -> dict:
    content = ""
    try:
        g = api({"op": "get", "slug": slug})
        content = g.get("content") or ""
    except Exception as e:
        return {"slug": slug, "topic": lesson.get("topic", ""),
                "lesson_date": ldate, "flags": [f"get-failed:{e}"],
                "sources": []}
    refs = source_refs(content)
    srcs, flags = [], []
    for rel in refs:
        exists = (repo / rel).exists()
        lc = last_commit(repo, rel) if exists else ""
        srcs.append({"path": rel, "exists": exists,
                     "last_commit": lc or None})
        if not exists:
            flags.append(f"source-gone:{rel}")
        elif ldate and lc > ldate:
            flags.append(f"drift:{rel}({lc}>{ldate})")
    if not refs:
        flags.append("no-repo-source")
    return {"slug": slug, "topic": lesson.get("topic", ""),
            "level": lesson.get("level", ""), "lesson_date": ldate,
            "flags": flags, "sources": srcs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="",
                    help="repo root for source-doc lookups "
                         "(default: git toplevel of cwd)")
    ap.add_argument("--out", default="", help="write JSON report here")
    ap.add_argument("--slugs", default="", help="comma list — audit only")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any drift flag is present")
    a = ap.parse_args()

    repo = Path(a.repo).expanduser() if a.repo else None
    if repo is None:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True)
        repo = Path(r.stdout.strip()) if r.returncode == 0 else Path.cwd()

    try:
        listing = api({"op": "list"})
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"lessons-drift: board-api /lesson unreachable: {e}",
              file=sys.stderr)
        return 2
    lessons = listing.get("lessons") or []
    want = {s.strip() for s in a.slugs.split(",") if s.strip()}
    rows = []
    for l in lessons:
        slug = l.get("slug") or ""
        if want and slug not in want:
            continue
        ldate = str(l.get("modified") or "")[:10] or \
            str((l.get("meta") or {}).get("updated") or "")[:10]
        rows.append(audit_lesson(repo, slug, l, ldate))

    drifted = [r for r in rows
               if any(f.startswith("drift:") for f in r["flags"])]
    gone = [r for r in rows
            if any(f.startswith("source-gone:") for f in r["flags"])]
    nosrc = [r for r in rows if "no-repo-source" in r["flags"]]
    report = {"generated": date.today().isoformat(), "repo": str(repo),
              "total": len(rows), "drifted": len(drifted),
              "source_gone": len(gone), "no_repo_source": len(nosrc),
              "rows": rows}
    print(f"lessons-drift: {len(rows)} lessons — "
          f"{len(drifted)} drifted, {len(gone)} source-gone, "
          f"{len(nosrc)} no-repo-source")
    for r in drifted + gone:
        print(f"  {r['slug']} ({r['topic'] or 'untitled'}) "
              f"filed {r['lesson_date']}")
        for f in r["flags"]:
            if f != "no-repo-source" and not f.startswith("get-failed"):
                print(f"    - {f}")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(report, indent=1,
                                          ensure_ascii=False))
        print("wrote", a.out)
    return 1 if (a.strict and drifted) else 0


if __name__ == "__main__":
    sys.exit(main())
