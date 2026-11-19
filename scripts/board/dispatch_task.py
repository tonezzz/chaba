#!/usr/bin/env python3
"""dispatch_task — shared devin-lane task-text composition.

kanban-dispatch.build_task and runner-agent's devin path each used to
assemble the dispatch prompt by hand; only the kanban-dispatch copy
injected the lesson primer, so ~96% of dispatches (the runner-agent
lane, ~893 claims) ran unprimed and the lesson loop never fired
(runner-agent-primer-coverage; primer-efficacy measurement
2026-11-09). build_task_text() is the single source for the composed
text — spec + TASK_RAILS + KNOWN_PITFALLS + KNOWN_GOOD + RETRY_RAILS +
REPORT_RAILS — so future rail blocks land in both lanes at once.

runner-agent deploys as a single file and resolves this module from a
local chaba checkout (same pattern dr_module() uses for
dispatch_repos); when no checkout is importable the devin path falls
back to plain spec + RAILS — the primer is advisory, never a claim
blocker. KANBAN_PRIMER=0 / KANBAN_PRIMER_GOOD=0 stay honored here.
"""
import os
import sys
from pathlib import Path

import lesson_primer as lp


def _act(card: dict) -> dict:
    """card['action'] read accessor — schema says dict, but marker cards
    carry scalars ('spec-review'). Returns {} for non-dict WITHOUT
    writing, so read-only passes don't stamp action:{} onto cards."""
    a = card.get("action")
    return a if isinstance(a, dict) else {}


TASK_RAILS = """
---
Rails: you are processing kanban card '{id}' (docs/ssot/kanban/cards/{id}.yml).
- Work in the worktree devin-dispatch gave you; do NOT push unless the
  card spec explicitly says to.
- While you work, post progress to the card so the board stays live:
    curl -s -X POST {api}/comment \\
      -H 'Content-Type: application/json' \\
      -d '{{"id":"{id}","from":"devin","text":"<short status>"}}'
- When done, post a final comms entry summarizing outcome + where the
  deliverables are. The dispatcher will mark the action done and move
  the card to review.
- If you need Tony to answer something, raise a board request — do NOT
  edit the card YAML directly (that races the API's flock):
    curl -s -X POST {api}/request \\
      -H 'Content-Type: application/json' \\
      -d '{{"id":"{id}","from":"devin","ask":"<question>"}}'
- If you raised a request and kept working, the answer may arrive while
  you run: board-api appends it to $TASK_DIR/answers.jsonl (one JSON
  object per line: {{"at","card","from","kind","request_id","answer"}}).
  Check that file before finishing; newest line wins per request_id.
- answers.jsonl lines may also carry kind:"comment" — card comms pushed
  live (Tony's notes, Ada's [opinion]-tagged report takes). Treat them
  as review input to weigh; request_id/answer lines (kind:"answer")
  remain the authoritative answer channel.
- If the card opts into the CI pipeline (a `pipeline: ci` field), run
  `python3 scripts/ci/card-pipeline.py {id} --api {api}` near the end —
  it audits your worktree diff and records benchmark before/after on the
  card (docs/ssot/ssot.ci.yml).
- End your dispatch-outcome doc with a `lessons:` list — 0-5 short
  gotcha lines (one `- ` item each; `lessons: []` if none). The dispatch
  primer harvests them into the next run's KNOWN_PITFALLS block.
""".strip()

# Appended after TASK_RAILS when the card was requeued after a failed
# attempt (action.attempts > 0 or action.last_failure set) — the next
# session gets the failure evidence instead of a blind re-run.
RETRY_RAILS = """
---
This is attempt {n} for this card — the previous run did NOT merge/verify
cleanly. Prior failure: {failure}
- Read the card's comms for the full trail before starting:
    curl -s {api}/cards | python3 -c "import sys,json; print(json.dumps([c.get('comms') for c in json.load(sys.stdin).get('cards',[]) if c.get('id')=='{id}'], indent=1))"
- Fix the reported failure FIRST; do not repeat the failed approach.
""".strip()

# Design docs/design/report-session-loop.md §2b — appended after
# TASK_RAILS when the card carries `report: <cms-slug>`; the session
# keeps ada-cms-pages/<slug> updated via scripts/ada/cms-report-note.py.
REPORT_RAILS = """
This card is report-linked: ada-cms-pages/{slug}.
- Read the report FIRST: python3 scripts/ada/cms-report-note.py {slug} --read
- As you work, mirror progress into the report's session log:
    python3 scripts/ada/cms-report-note.py {slug} --note "<what changed>"
  (appends meta.timeline + the <!-- session-log:auto --> managed block;
   merges meta per the writer contract — never bare-replace a page)
- Before finishing: the report must reflect the outcome. The report is
  the long-lived artifact; this card is the tracking surface.
""".strip()


def build_task_text(card: dict, host: str, api: str,
                    root: Path | None = None) -> tuple:
    """Compose the devin-lane dispatch prompt for `card`.

    Returns (task_text, primer_lines, good_lines) — callers log the
    line lists to card comms (kanban-dispatch start_pending's
    'primer injected N lesson(s)' note) so the board shows exactly
    what the primer added. `root` is the corpus root the primer scans
    (docs/ssot/jobs, docs/kb, outcome docs, card comms); None lets
    lesson_primer default to its own repo root — the right answer when
    this module was resolved out of a chaba checkout.
    """
    spec = (card.get("spec") or "").strip() \
        or f"{card.get('title','')}\n\n{card.get('note','')}"
    task = spec + "\n\n" + TASK_RAILS.format(id=card["id"], api=api)
    repo = (_act(card)).get("repo", "chaba")
    primer_lines: list = []
    good_lines: list = []
    if os.environ.get("KANBAN_PRIMER", "1") != "0":
        try:
            primer_lines = lp.build(card, host, repo, root)
        except Exception as e:  # primer is advisory — never block a run
            print(f"warn: lesson primer failed: {e}", file=sys.stderr)
    if primer_lines:
        task += "\n\n" + lp.format_block(primer_lines, host, repo)
    if os.environ.get("KANBAN_PRIMER_GOOD", "1") != "0":
        try:
            good_lines = lp.build_good(card, host, repo, root)
        except Exception as e:  # good primer is advisory too
            print(f"warn: good primer failed: {e}", file=sys.stderr)
    if good_lines:
        task += "\n\n" + lp.format_good_block(good_lines)
    a = _act(card)
    attempts = int(a.get("attempts") or 0)
    if attempts > 0 or a.get("last_failure"):
        task += "\n\n" + RETRY_RAILS.format(
            id=card["id"], api=api, n=attempts + 1,
            failure=str(a.get("last_failure")
                        or "(no detail — inspect the card comms)")[:400])
    slug = str(card.get("report") or "").strip()
    if slug:
        task += "\n\n" + REPORT_RAILS.format(slug=slug)
    return task, primer_lines, good_lines
