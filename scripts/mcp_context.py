"""Context retrieval for active focus.

Phase 3 prototype: loads active focus from mcp_focus, expands a query, and returns
relevant KB and SSOT files by keyword. MDDB semantic search integration is next.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_debug.focus import mcp_focus

REPO = Path(__file__).resolve().parent.parent
KB_DIR = REPO / "docs" / "kb"
SSOT_DIR = REPO / "docs" / "ssot"


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _score(path, tokens):
    try:
        text = read_text(path)
    except OSError:
        return 0
    content = path.stem + " " + text.lower()
    hits = sum(1 for t in tokens if t in content)
    # Reduce noise from very short files
    length = len(text.split())
    if length < 10:
        return 0
    return hits


def read_text(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def _relevant_files(tokens, root, limit=10):
    if not root.exists():
        return []
    results = []
    for path in root.rglob("*.md"):
        if path.is_dir() or path.name.startswith("_"):
            continue
        score = _score(path, tokens)
        if score > 0:
            results.append((score, str(path.relative_to(REPO))))
    for path in root.rglob("*.yml"):
        if path.is_dir() or path.name.startswith("_"):
            continue
        score = _score(path, tokens)
        if score > 0:
            results.append((score, str(path.relative_to(REPO))))
    results.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in results[:limit]]


def mcp_context(query=None, top_k=10):
    status = mcp_focus(mode="status")
    active = status.get("active", {})
    branch = active.get("branch", {})
    shared = active.get("shared", {})

    # Build context from active focus labels and quick wins
    context_parts = []
    if branch:
        context_parts.append(branch.get("label", ""))
        context_parts.append(branch.get("text", ""))
    if shared:
        context_parts.append(shared.get("label", ""))
        context_parts.append(shared.get("text", ""))
    for qw in status.get("quick_wins", []):
        context_parts.append(qw.get("label", ""))
    if query:
        context_parts.append(query)

    text = " ".join(context_parts)
    tokens = _tokens(text)

    kb_files = _relevant_files(tokens, KB_DIR, limit=top_k)
    ssot_files = _relevant_files(tokens, SSOT_DIR, limit=top_k)

    return {
        "ok": True,
        "query": query or text[:200],
        "active_focus": branch.get("label") or shared.get("label"),
        "tokens": sorted(list(tokens))[:50],
        "kb": kb_files,
        "ssot": ssot_files,
        "note": "Local keyword fallback; MDDB semantic search integration is next.",
    }


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(mcp_context(query=q), indent=2, default=str))
