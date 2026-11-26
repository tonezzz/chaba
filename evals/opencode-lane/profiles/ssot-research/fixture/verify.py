#!/usr/bin/env python3
"""Held-out verifier for ssot-research: required fields present and
every claimed citation resolves to a real file in the checkout — the
citation contract is checked, not trusted.

KNB-1029/OPS-1017 class gap: path-existence alone lets a fabricated
answer pass when it cites real files that do not support the claim
(qwen3:8b cited AGENTS.md + ssot.mcp.yml for a kk-mac answer whose
truth lived in ssot.audit.hosts.yml + litellm config). Fix: every
citation's `note` must carry a quoted string ("...", “...”, `...`,
or '...') that appears VERBATIM in the cited file — whitespace-
normalized. A citation with no verifiable quote fails closed."""
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]

QUOTE_RE = re.compile(
    r'"([^"\n]{8,})"|“([^”\n]{8,})”|`([^`\n]{8,})`'
    r"|'([^'\n]{10,})'")
MAX_FILE_BYTES = 4_000_000


def _norm(s):
    return " ".join(str(s).split())


def _quotes(note):
    """Verbatim-quote candidates from a citation note (>=8 chars)."""
    out = []
    for m in QUOTE_RE.finditer(str(note or "")):
        q = next(g for g in m.groups() if g is not None)
        q = _norm(q)
        if len(q) >= 8:
            out.append(q)
    return out


def _file_norm(path):
    try:
        raw = path.read_bytes()[:MAX_FILE_BYTES]
        return _norm(raw.decode("utf-8", "replace"))
    except Exception:
        return ""


def verify(run_dir):
    rd = Path(run_dir)
    checks = {}
    try:
        a = json.loads((rd / "artifact.out").read_text())
        man = json.loads((rd / "manifest.json").read_text())
    except Exception as e:
        return {"verdict": "fail",
                "checks": {"artifact readable": False, "error": str(e)}}

    req = ("question", "answer", "citations", "sources_consulted",
           "read_only")
    checks["required fields"] = all(k in a for k in req)
    checks["read_only true"] = a.get("read_only") is True
    checks["answer non-empty"] = bool(str(a.get("answer") or "").strip())

    cits = a.get("citations") or []
    checks["citations >= 2"] = len(cits) >= 2
    # contract is {path, note} objects — anything else is malformed and
    # fails cleanly (never crash on agent-shaped input)
    checks["citations are {path,note} objects"] = all(
        isinstance(c, dict) and c.get("path") for c in cits)
    resolved = 0
    bad = []
    unverified = []
    for c in cits:
        p = str((c or {}).get("path") if isinstance(c, dict) else c) \
            .strip().lstrip("/")
        fp = REPO / p if p else None
        if p and fp.is_file():
            resolved += 1
            # quote-verification: the note must quote text that really
            # appears in the cited file — existence != support (KNB-1029)
            qs = _quotes((c or {}).get("note") if isinstance(c, dict)
                         else "")
            content = _file_norm(fp)
            if qs and any(q in content for q in qs):
                continue
            unverified.append({"path": p,
                               "reason": "no quote" if not qs
                               else "quote not in file"})
        else:
            bad.append(p or "?")
    checks["every cited path exists"] = resolved == len(cits) and not bad
    checks["every citation quote verified"] = not unverified
    if unverified:
        checks["unverified citations"] = unverified
    checks["no bare/outside citations"] = all(
        ".." not in str((c or {}).get("path") if isinstance(c, dict)
                        else c)
        for c in cits)
    if bad:
        checks["bad citations"] = False

    srcs = a.get("sources_consulted") or []
    checks["sources under docs/"] = any(
        str(s).lstrip("/").startswith("docs/") for s in srcs)
    checks["consulted paths exist"] = all(
        (REPO / str(s).lstrip("/")).exists() for s in srcs) \
        if srcs else False

    # the question in the artifact echoes the envelope's task text
    task = str((man.get("envelope") or {}).get("task") or "").strip()
    if task:
        q = str(a.get("question") or "")
        echoed = q.strip()[:80] == task[:80] or \
            task[:40].lower() in q.lower()
        if not echoed and (man.get("envelope") or {}).get("dispatch_card"):
            # card dispatches carry long multi-sentence specs; a faithful
            # restatement is acceptable — require >=50% content-word
            # overlap with the task instead of verbatim echo.
            words = lambda s: set(re.findall(r"[a-z0-9]{3,}", s.lower()))
            tw = words(task)
            qw = words(q)
            ov = len(tw & qw)
            echoed = bool(tw) and bool(qw) and (
                ov / len(tw) >= 0.4 or ov / len(qw) >= 0.6)
        checks["question echoed"] = echoed

    verdict = "pass" if all(v is True for v in checks.values()) \
        else "fail"
    return {"verdict": verdict, "checks": checks}


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1] if len(sys.argv) > 1
                            else os.getcwd()), indent=1))
