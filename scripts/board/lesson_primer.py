#!/usr/bin/env python3
"""lesson_primer — harvest relevant past-failure lines for a dispatch.

Card dispatch-lesson-primer: dispatches start from zero every run; this
closes the loop by injecting the top-K lesson lines matching the card's
(host, repo, task keywords) into the prompt as a KNOWN_PITFALLS block.

Sources, in rank order:

  1. dispatch-outcome-*.md ``lessons:`` lists — self-seeded: TASK_RAILS
     tells every session to write short gotcha lines there. Kept as the
     fallback corpus for chaba-local docs that predate bank writes.
  1b. the mddb devin-handoff bank — kind=lesson docs that
     dispatch_repos.bank_outcome_lessons POSTs at every dispatch
     close-out, keyed lesson/<task_id>/<n>. This is the repo-agnostic
     corpus (cross-repo-lesson-harvest): outcome docs written inside
     ada-voice / sunsynk-card / mddb-fork checkouts never reach the
     chaba-root glob but DO reach the bank. Fetched over /v1/search
     (base MDDB_BASE_URL, default http://100.102.134.91:11023/v1 — the
     kanban-dispatch convention), ~60s in-process cache, fail-open
     with a stderr warn when unreachable. LESSON_BANK=0 disables.
  2. docs/ssot/jobs/**/*.yml — fields named method_notes / side_findings /
     gotchas / lessons / pitfalls (any depth), split into signal lines.
  3. kanban card comms matching gotcha|failed|lesson|do NOT|never|...
  4. docs/kb/**/*.md runbooks — title+abstract keyword match contributes
     a pointer line ("runbook <path>: <title>").

A line is kept only when it carries a lesson signal word, shares >=2
distinct keywords with the card (matched on word boundaries), AND hits
>=1 card-derived task keyword — host/repo tokens rank but cannot
qualify a line on their own (host-specific lessons are the least
generalizable). Lines from files older than STALE_DAYS score -1
(staleness demotion); lines naming retired infra (RETIRED_RE) are
dropped unless they still hit >=2 task keywords.
Output: top MAX_LINES lines within
MAX_CHARS (~1.5k tokens, ssot.tokens.policy baseline-discipline).
KANBAN_PRIMER=0 disables (kanban-dispatch checks the env).

Positive channel (card positive-signal-primer): build_good() mirrors the
pitfalls path but harvests what WORKED — one distilled line per card that
verified clean on its first attempt (action.verified + attempts <= 1),
plus job-doc fields named wins / worked / success_patterns. Rendered as
a KNOWN_GOOD block via format_good_block(); KANBAN_PRIMER_GOOD=0
disables. Both channels share _select() so eligibility/scoring stays in
one place (the scoring-fixes card edits it once for both).
"""
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

import yaml

MAX_LINES = 8
MAX_CHARS = 5500          # ~1.5k tokens at ~3.7 chars/token
LINE_CAP = 240
MIN_SCORE = 2             # distinct keyword hits required
STALE_DAYS = 90           # source files older than this score -1

# Infra retired from the fleet — lines referencing it are stale by
# definition. Dropped unless the line still hits >=2 task keywords.
# NEEDS PERIODIC REVIEW as hosts retire or return to service.
RETIRED_RE = re.compile(r"\bidc01\b", re.I)

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

# Lesson bank (cross-repo-lesson-harvest): kind=lesson docs in the
# devin-handoff collection — written by dispatch_repos.bank_outcome_lessons
# at every close-out, keyed lesson/<task_id>/<n>. Same MDDB_BASE_URL
# convention as kanban-dispatch.
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
BANK_COLLECTION = os.environ.get(
    "LESSON_BANK_COLLECTION", "ada-ha-bank-devin-handoff")
BANK_LIMIT = 500              # kind=lesson docs fetched per refresh
BANK_TTL = 60                 # seconds between /v1/search refreshes
_BANK_CACHE = [0.0, []]       # [fetched_at, docs] — also caches failures

STOPWORDS = {
    "this", "that", "with", "from", "into", "when", "then", "than",
    "have", "been", "will", "would", "should", "could", "about", "after",
    "before", "the", "and", "for", "are", "was", "were", "not", "all",
    "any", "each", "card", "task", "work", "spec", "your", "them",
    "they", "their", "there", "here", "what", "which", "while",
}


def _tokens(s: str) -> list:
    return re.findall(r"[a-z0-9][a-z0-9_.-]{2,}", (s or "").lower())


def keywords(card: dict, host: str, repo: str) -> tuple:
    """(task_kws, host_repo_kws) — card-derived keywords vs host+repo
    tokens. Task kws qualify a line; host/repo kws only rank it."""
    parts = [str(card.get(k) or "")
             for k in ("id", "title", "brief", "spec", "note")]
    parts += [str(t) for t in (card.get("tags") or [])]
    task = {t for t in (s.strip("._-") for s in _tokens(" ".join(parts)))
            if len(t) >= 4 and t not in STOPWORDS}
    host_repo = {t for t in
                 (s.strip("._-") for s in _tokens(f"{host or ''} {repo or ''}"))
                 if len(t) >= 3}
    return task, host_repo - task


def _score(text: str, kws: set) -> int:
    """Distinct keyword hits on word boundaries — 'test' does not match
    'latest'/'protest', 'card' does not match 'discard'. Compound tokens
    (ada-voice, ssot.kanban) count whole and by parts; edge punctuation
    is stripped so 'tony-omen.' still matches 'tony-omen'."""
    tl = (text or "").lower()
    toks = ({t.strip("._-") for t in _tokens(tl)}
            | set(re.findall(r"[a-z0-9]+", tl)))
    return len(toks & {k.strip("._-") for k in kws})


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
        if not isinstance(doc, dict):
            continue
        for text in _walk_fields(doc):
            for line in _lesson_lines(text):
                out.append((line, 1, p))
    return out


def _comms_candidates(root: Path) -> list:
    out = []
    for p in sorted(root.glob("docs/ssot/kanban/cards/*.yml")):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        for c in (doc.get("comms") or []):
            text = (str(c.get("text") or "") if isinstance(c, dict)
                    else str(c or ""))
            if COMMS_RE.search(text):
                out.append((_clip(f"[{p.stem}] {text}"), 2, p))
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
                out.append((_clip(m.group(1)), 0, p))
    return out


def _bank_docs() -> list:
    """kind=lesson docs from the devin-handoff bank, BANK_TTL-cached.
    Fail-open: an unreachable bank warns on stderr (at most once per
    TTL) and yields no docs — the primer must never stall a dispatch
    on mddb. LESSON_BANK=0 disables the source."""
    if os.environ.get("LESSON_BANK", "1") == "0":
        return []
    now = time.time()
    if now - _BANK_CACHE[0] < BANK_TTL:
        return list(_BANK_CACHE[1])
    try:
        req = urllib.request.Request(
            f"{MDDB}/search",
            data=json.dumps({
                "collection": BANK_COLLECTION,
                "filterMeta": {"kind": ["lesson"]},
                "limit": BANK_LIMIT}).encode(),
            headers={"Content-Type": "application/json"})
        body = json.load(urllib.request.urlopen(req, timeout=10))
        docs = body if isinstance(body, list) else []
    except Exception as e:
        print(f"warn: lesson bank unreachable: {e}", file=sys.stderr)
        docs = []
    _BANK_CACHE[0], _BANK_CACHE[1] = now, docs
    return list(docs)


def _bank_candidates() -> list:
    """Bank lessons at outcome-doc rank — each contentMd line was
    already extracted from a `lessons:` list at close-out, so no
    signal re-filter. src is the doc key (non-Path -> never stale)."""
    out = []
    for d in _bank_docs():
        for ln in str(d.get("contentMd") or "").splitlines():
            ln = ln.strip()
            if ln:
                out.append((_clip(ln), 0, d.get("key") or "bank"))
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
                        3, p))
    return out


def _stale(path, now: float) -> bool:
    """Source file untouched for >STALE_DAYS -> its lines score -1.
    Non-path sources (bank doc keys) carry no mtime — never stale."""
    if not isinstance(path, Path):
        return False
    try:
        return (now - path.stat().st_mtime) > STALE_DAYS * 86400
    except OSError:
        return False


def _select(cands: list, card: dict, host: str, repo: str,
            max_lines: int, max_chars: int) -> list:
    """Shared dedupe + keyword-score + rank + cap path for both the
    pitfalls and the positive channel - eligibility lives here once so
    both channels apply the same rules (task-kw eligibility, retired-
    infra filter, staleness demotion)."""
    task_kws, host_repo_kws = keywords(card, host, repo)
    kws = task_kws | host_repo_kws
    now = time.time()
    seen, scored = set(), []
    for text, rank, src in cands:
        key = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        task_hits = _score(text, task_kws)
        if not task_hits:
            continue  # host/repo tokens rank but cannot qualify a line
        if RETIRED_RE.search(text) and task_hits < 2:
            continue  # retired infra unless still on-topic for the card
        s = _score(text, kws)
        if _stale(src, now):
            s -= 1
        if s >= MIN_SCORE:
            scored.append((-s, rank, text))
    scored.sort()
    lines, total = [], 0
    for _, _, text in scored:
        if len(lines) >= max_lines or total + len(text) > max_chars:
            break
        lines.append(text)
        total += len(text)
    return lines


def build(card: dict, host: str, repo: str = "",
          root: Path | None = None) -> list:
    """Top MAX_LINES lesson lines for this card, char-capped."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    task_kws, host_repo_kws = keywords(card, host, repo)
    kws = task_kws | host_repo_kws
    cands = (_outcome_candidates(root) + _bank_candidates()
             + _job_candidates(root) + _comms_candidates(root)
             + _kb_candidates(root, kws))
    return _select(cands, card, host, repo, MAX_LINES, MAX_CHARS)


def format_block(lines: list, host: str, repo: str) -> str:
    body = "\n".join(f"- {l}" for l in lines)
    return (
        "---\n"
        "KNOWN_PITFALLS — lessons harvested from past dispatches/jobs "
        f"matching this card (host={host}, repo={repo}); "
        "check before acting:\n" + body)


# --------------------------------------------------------------------
# Positive channel — KNOWN_GOOD lines harvested from first-try-verified
# work (card positive-signal-primer).

GOOD_MAX_LINES = 4
GOOD_MAX_CHARS = 1200

# Success-signal words a comms/outcome line must carry to count as
# "what worked" — word-bounded so "unmerged"/"unverified" don't count;
# keeps pure process chatter out.
GOOD_SIGNAL_RE = re.compile(
    r"\b(?:worked|clean(?:ly)?|merged|verified)\b|passed first|first try",
    re.I)

# Process-noise comms lines carry signal words but name no approach
# (dispatch bookkeeping, merge-sweep bookkeeping, queue chatter).
GOOD_NOISE_RE = re.compile(
    r"queued for processing|^claimed\b|\bdispatched\b|started devin-task|"
    r"ref assigned|\barchived\b|\bdefers\b|primer injected|run finished|"
    r"put on hold|armed (for|as) dispatch|merge-sweep|"
    r"no session/worktree|→ origin/|auto-merged dispatch|picked up|"
    r"auto-merge not done|push: fatal|worktree kept|unmerged commits|"
    r"close will block|could not read",
    re.I)

# Job-doc fields harvested for the positive channel (plus any key
# matching GOOD_KEY_RE).
GOOD_KEYS = {"wins", "worked", "success_patterns", "what_worked"}
GOOD_KEY_RE = re.compile(r"wins?\b|worked|success_patterns", re.I)

GOOD_MIN_LEN = 30          # a substantive comms line, post-clip


def _good_pieces(text: str) -> list:
    """Split a comms/outcome blob into candidate positive lines."""
    out = []
    for raw in str(text).splitlines():
        raw = raw.strip()
        if not raw:
            continue
        pieces = [raw] if len(raw) <= LINE_CAP else re.split(
            r"(?<=[.!?])\s+|(?=VERIFIED:|NOTE:)", raw)
        out.extend(pieces)
    return out


def _card_good_line(doc: dict, card_id: str) -> tuple:
    """One distilled good line for a verified card: the first substantive
    comms/outcome line carrying a success signal, else the card's own
    spec-summary line. Returns (line, rank); empty line means skip."""
    texts = [str(c.get("text") or "")
             for c in (doc.get("comms") or []) if isinstance(c, dict)]
    a = doc.get("action")
    if not isinstance(a, dict):
        a = {}
    for k in ("outcome", "result"):
        if a.get(k):
            texts.append(str(a[k]))
    if doc.get("outcome"):
        texts.append(str(doc["outcome"]))
    for t in texts:
        for p in _good_pieces(t):
            line = _clip(p)
            if (len(line) >= GOOD_MIN_LEN and GOOD_SIGNAL_RE.search(line)
                    and not GOOD_NOISE_RE.search(line)):
                return f"[{card_id}] {line}", 1
    for raw in str(doc.get("spec") or doc.get("title") or "").splitlines():
        head = _clip(raw)
        if head:
            return f"[{card_id}] {head}", 2
    return "", 9


def _good_card_candidates(root: Path) -> list:
    """One line per card that verified clean on its first attempt."""
    out = []
    for p in sorted(root.glob("docs/ssot/kanban/cards/*.yml")):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        a = doc.get("action")
        if not isinstance(a, dict) or a.get("verified") is not True:
            continue
        try:
            if int(a.get("attempts") or 0) > 1:
                continue
        except (TypeError, ValueError):
            continue
        line, rank = _card_good_line(doc, str(doc.get("id") or p.stem))
        if line:
            out.append((line, rank, p))
    return out


def _walk_good_fields(node):
    """Yield text under wins/worked/success_patterns keys, any depth."""
    if isinstance(node, dict):
        for k, v in node.items():
            kl = str(k).lower()
            if kl in GOOD_KEYS or GOOD_KEY_RE.search(kl):
                yield from _texts(v)
            else:
                yield from _walk_good_fields(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_good_fields(v)


def _good_job_candidates(root: Path) -> list:
    """wins/worked/success_patterns fields in docs/ssot/jobs/**/*.yml."""
    out = []
    for p in sorted(root.glob("docs/ssot/jobs/**/*.yml")):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        for text in _walk_good_fields(doc):
            for piece in _good_pieces(text):
                line = _clip(piece)
                if len(line) >= 15:
                    out.append((_clip(f"[{p.stem}] {line}"), 0, p))
    return out


def _positive_candidates(root: Path) -> list:
    """Positive candidates: first-try-verified cards + job-doc wins."""
    return _good_card_candidates(root) + _good_job_candidates(root)


def build_good(card: dict, host: str, repo: str = "",
               root: Path | None = None) -> list:
    """Top GOOD_MAX_LINES positive lines for this card, char-capped."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    return _select(_positive_candidates(root), card, host, repo,
                   GOOD_MAX_LINES, GOOD_MAX_CHARS)


def format_good_block(lines: list) -> str:
    body = "\n".join(f"- {l}" for l in lines)
    return (
        "---\n"
        "KNOWN_GOOD — approaches that verified clean on similar work:\n"
        + body)
