#!/usr/bin/env python3
"""bounded.py — shared budget/noise machinery for rendered surfaces.

Extracted from scripts/chaba/render-memory.py (2026-10-09) so the report
pipeline (bounded_surfaces in docs/ssot/infrastructure/ssot.reports.yml)
and the memory render enforce the same knobs with the same semantics —
no hand-rolled truncation or ad-hoc filtering in generators.

Helpers:
  apply_budget(lines, soft, hard)   char budget over lines, truncation markers
  dedupe_consecutive(entries, ...)  collapse repeats with a ×N marker
  drop_patterns(items, pats, ...)   regex suppression, returns dropped count
  filter_status(vals, skip)         drop dict items by their status field
  cap_entry(text, max_chars)        per-entry/finding head cap
  keep_last(entries, n)             keep the newest n entries (0/None = all)
  enforce_surface(blocks, ...)      whole-surface budget: ordered shed + hard cut
"""
import re


def apply_budget(lines, soft, hard):
    """Returns (kept_lines, truncated_count)."""
    if not soft and not hard:
        return lines, 0
    cap = soft or hard
    out, total = [], 0
    for ln in lines:
        if total + len(ln) + 1 > cap and out:
            return out + [f"…(truncated — {len(lines) - len(out)} more lines in source)"], len(lines) - len(out)
        out.append(ln)
        total += len(ln) + 1
    joined = "\n".join(out)
    if hard and len(joined) > hard:
        joined = joined[: hard - 60] + "\n…(hard-truncated)"
        return joined.splitlines(), len(lines) - len(out) + 1
    return joined.splitlines(), 0


def dedupe_consecutive(entries, mark_plain=False):
    """Collapse consecutive entries that differ only in the heading line
    (e.g. repeated scenario-run failures) into one entry marked "×N".

    An entry's dedupe key is its body: everything after a leading '#'
    heading, or the whole entry when it has no heading. With mark_plain
    the ×N marker is appended to the first line of heading-less entries
    too (report table rows); the default preserves memory-render
    behavior where only '#'-headed entries carry the marker."""
    deduped = []
    for e in entries:
        lines = e.splitlines()
        body = "\n".join(lines[1:]).strip() if lines and lines[0].startswith("#") else e
        if not e.strip():
            # blank separators never collapse — and must not be merge
            # targets either (a "" body would swallow a following
            # heading-only entry whose body is also "")
            deduped.append([e, object(), 1])
        elif deduped and deduped[-1][1] == body:
            deduped[-1][2] += 1
        else:
            deduped.append([e, body, 1])
    out = []
    for e, _body, n in deduped:
        if n == 1:
            out.append(e)
        elif re.search(r"^#", e, flags=re.M):
            out.append(re.sub(r"^(#+.*)$", rf"\g<1> ×{n}", e, count=1, flags=re.M))
        elif mark_plain:
            lines = e.splitlines()
            lines[0] = f"{lines[0]} ×{n}"
            out.append("\n".join(lines))
        else:
            out.append(e)
    return out


def drop_patterns(items, patterns, key=None):
    """Drop items matching any regex in patterns.

    items: list of strings, or list of dicts when `key` names the field
    to test. Returns (kept_items, dropped_count) so the caller can render
    a '…(N routine findings suppressed)'-style awareness marker."""
    pats = [re.compile(p) for p in (patterns or [])]
    if not pats:
        return items, 0
    kept, dropped = [], 0
    for it in items:
        if key is None:
            text = it if isinstance(it, str) else str(it)
        else:
            text = str(it.get(key) or "") if isinstance(it, dict) else ""
        if any(p.search(text) for p in pats):
            dropped += 1
            continue
        kept.append(it)
    return kept, dropped


def filter_status(vals, skip):
    """Drop dict items whose 'status' field is in skip — the memory
    render's skip_status query knob."""
    skip = set(skip or [])
    if not skip:
        return vals
    return [v for v in vals
            if not (isinstance(v, dict) and v.get("status") in skip)]


def cap_entry(text, max_chars):
    """Per-entry head cap — a single entry/finding longer than max_chars
    is truncated with a source pointer rather than allowed to eat the
    whole section budget (memory's entry_max_chars)."""
    if not max_chars or len(text) <= max_chars:
        return text
    return (text[: max_chars - 40].rstrip()
            + f"\n…({len(text) - max_chars + 40:,} more chars in source)")


def keep_last(entries, n):
    """Keep the newest n entries (rolling sources append newest-last).
    n of 0/None keeps everything — entries[-0:] would silently do that
    anyway, but saying so is the point of the helper."""
    if not n:
        return entries
    return entries[-n:]


def enforce_surface(blocks, limits, overflow_order, shed_text=None):
    """Surface-level budget for a multi-section rendered document —
    the report-pipeline counterpart of render-memory's enforce_global.

    blocks: [{id, text, ...}] in render order. While the joined surface
    exceeds limits.soft, blocks named in overflow_order are shed in
    order — replaced by shed_text(block) when given, else removed.
    Blocks not named in overflow_order (e.g. the preamble) are never
    shed. limits.hard then hard-cuts the joined text.

    Returns (text, shed_ids, over_hard)."""
    soft = (limits or {}).get("soft")
    hard = (limits or {}).get("hard")
    blocks = [dict(b) for b in blocks]
    shed = []

    def total():
        return sum(len(b["text"]) + 2 for b in blocks)

    if soft:
        for sid in overflow_order or []:
            if total() <= soft:
                break
            for i, b in enumerate(blocks):
                if b["id"] == sid:
                    shed.append(sid)
                    if shed_text is not None:
                        blocks[i]["text"] = shed_text(b)
                    else:
                        del blocks[i]
                    break
    text = "\n\n".join(b["text"] for b in blocks)
    over_hard = bool(hard and len(text) > hard)
    if over_hard:
        text = text[: hard - 80] + "\n\n…(global hard limit reached — truncated)\n"
    return text, shed, over_hard
