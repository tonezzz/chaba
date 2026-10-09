#!/usr/bin/env python3
"""lesson_primer — harvest relevant past-failure lines for a dispatch.

Card dispatch-lesson-primer: dispatches start from zero every run; this
closes the loop by injecting the top-K lesson lines matching the card's
(host, repo, task keywords) into the prompt as a KNOWN_PITFALLS block.

Sources, in rank order:

  1. dispatch-outcome-*.md ``lessons:`` lists — self-seeded: TASK_RAILS
     tells every session to write short gotcha lines there.
  2. docs/ssot/jobs/**/*.yml — fields named method_notes / side_findings /
     gotchas / lessons / pitfalls (any depth), split into signal lines.
  3. kanban card comms matching gotcha|failed|lesson|do NOT|never|...
  4. docs/kb/**/*.md runbooks — title+abstract keyword match contributes
     a pointer line ("runbook <path>: <title>").

A line is kept only when it carries a lesson signal word and shares >=2
distinct keywords with the card. Output: top MAX_LINES lines within
MAX_CHARS (~1.5k tokens, ssot.tokens.policy baseline-discipline).
KANBAN_PRIMER=0 disables (kanban-dispatch checks the env).
"""
import re
from pathlib import Path

import yaml

MAX_LINES = 8
MAX_CHARS = 5500          # ~1.5k tokens at ~3.7 chars/token
LINE_CAP = 240
MIN_SCORE = 2             # distinct keyword hits required

# Words that mark a line as an actual lesson rather than prose.
SIGNAL_RE = re.compile(
    r"gotcha|fail(?:ed|ure|s)?\b|lesson|pitfall|never\b|do not\b|"
    r"don't\b|must not|beware|careful|broken|stall|race\b|workaround|"
    r"watch out|avoid\b|tripped|bit us", re.I)

# Job-doc fields harvested at any depth (plus any key matching KEY_RE).
LESSON_KEYS = {"method_notes", "side_findings", "gotchas", "lessons",
               "pitfalls", "lesson", "gotcha"}
KEY_RE = re.compile(r"gotcha|lesson|pitfall|fail", re.I)

COMMS_RE = re.compile(r"gotcha|failed|lesson|do not|never", re.I)

STOPWORDS = {
    "this", "that", "with", "from", "into", "when", "then", "than",
    "have", "been", "will", "would", "should", "could", "about", "after",
    "before", "the", "and", "for", "are", "was", "were", "not", "all",
    "any", "each", "card", "task", "work", "spec", "your", "them",
    "they", "their", "there", "here", "what", "which", "while",
}


def _tokens(s: str) -> list:
    return re.findall(r"[a-z0-9][a-z0-9_.-]{2,}", (s or "").lower())


def keywords(card: dict, host: str, repo: str) -> set:
    """Task keyword set: card text + tags + host + repo tokens."""
    parts = [str(card.get(k) or "")
             for k in ("id", "title", "brief", "spec", "note")]
    parts += [str(t) for t in (card.get("tags") or [])]
    kws = {t for t in _tokens(" ".join(parts))
           if len(t) >= 4 and t not in STOPWORDS}
    kws.update(t for t in _tokens(host or "") if len(t) >= 3)
    kws.update(t for t in _tokens(repo or "") if len(t) >= 3)
    return kws


def _score(text: str, kws: set) -> int:
    tl = text.lower()
    return sum(1 for k in kws if k in tl)


def _clip(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip(" -•\t")
    return (line[:LINE_CAP - 1] + "…") if len(line) > LINE_CAP else line


def _lesson_lines(text: str) -> list:
    """Split a harvested field into signal-bearing lesson lines."""
    out = []
    for raw in str(text).splitlines():
        raw = raw.strip()
        if not raw:
            continue
        # Long folded paragraphs: split on sentence/GOTCHA boundaries so a
        # signal sentence isn't dragged down by surrounding prose.
        pieces = [raw] if len(raw) <= LINE_CAP else re.split(
            r"(?<=[.!?])\s+|(?=GOTCHA:|NOTE:|WARNING:)", raw)
        for p in pieces:
            if SIGNAL_RE.search(p):
                out.append(_clip(p))
    return [l for l in out if l]


def _walk_fields(node):
    """Yield text under lesson-named keys, at any depth."""
    if isinstance(node, dict):
        for k, v in node.items():
            kl = str(k).lower()
            if kl in LESSON_KEYS or KEY_RE.search(kl):
                yield from _texts(v)
            else:
                yield from _walk_fields(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_fields(v)


def _texts(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, list):
        for item in v:
            yield from _texts(item)
    elif isinstance(v, dict):
        yield from _walk_fields(v)


def _job_candidates(root: Path) -> list:
    out = []
    for p in sorted(root.glob("docs/ssot/jobs/**/*.yml")):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        for text in _walk_fields(doc):
            for line in _lesson_lines(text):
                out.append((line, 1, p.name))
    return out


def _comms_candidates(root: Path) -> list:
    out = []
    for p in sorted(root.glob("docs/ssot/kanban/cards/*.yml")):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        for c in (doc.get("comms") or []):
            text = str((c or {}).get("text") or "")
            if COMMS_RE.search(text):
                out.append((_clip(f"[{p.stem}] {text}"), 2, p.name))
    return out


def _outcome_candidates(root: Path) -> list:
    """`lessons:` lists in dispatch-outcome-*.md (self-seeded)."""
    out = []
    for p in sorted(root.glob("dispatch-outcome-*.md")):
        try:
            lines = p.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for i, ln in enumerate(lines):
            if not re.match(r"^\s*lessons:\s*$", ln):
                continue
            for item in lines[i + 1:]:
                m = re.match(r"^\s*-\s+(.+)$", item)
                if not m:
                    break
                out.append((_clip(m.group(1)), 0, p.name))
    return out


def _kb_candidates(root: Path, kws: set) -> list:
    """Runbook pointer lines when title+abstract shares >=2 keywords."""
    out = []
    for p in sorted(root.glob("docs/kb/**/*.md")):
        try:
            head = p.read_text(errors="replace")[:2048]
        except Exception:
            continue
        title = ""
        abstract = []
        for ln in head.splitlines():
            s = ln.strip()
            if not title and s.startswith("#"):
                title = s.lstrip("#").strip()
                continue
            if title and s and not s.startswith("#"):
                abstract.append(s)
                if len(" ".join(abstract)) > 200:
                    break
        title = title or p.stem
        ab = " ".join(abstract)
        if _score(f"{title} {ab}", kws) >= MIN_SCORE:
            rel = p.relative_to(root) if p.is_relative_to(root) else p
            out.append((_clip(f"runbook {rel}: {title}"
                              + (f" — {ab[:120]}" if ab else "")),
                        3, p.name))
    return out


def build(card: dict, host: str, repo: str = "",
          root: Path | None = None) -> list:
    """Top MAX_LINES lesson lines for this card, char-capped."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    kws = keywords(card, host, repo)
    cands = (_outcome_candidates(root) + _job_candidates(root)
             + _comms_candidates(root) + _kb_candidates(root, kws))
    seen, scored = set(), []
    for text, rank, src in cands:
        key = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        s = _score(text, kws)
        if s >= MIN_SCORE:
            scored.append((-s, rank, text))
    scored.sort()
    lines, total = [], 0
    for _, _, text in scored:
        if len(lines) >= MAX_LINES or total + len(text) > MAX_CHARS:
            break
        lines.append(text)
        total += len(text)
    return lines


def format_block(lines: list, host: str, repo: str) -> str:
    body = "\n".join(f"- {l}" for l in lines)
    return (
        "---\n"
        "KNOWN_PITFALLS — lessons harvested from past dispatches/jobs "
        f"matching this card (host={host}, repo={repo}); "
        "check before acting:\n" + body)
