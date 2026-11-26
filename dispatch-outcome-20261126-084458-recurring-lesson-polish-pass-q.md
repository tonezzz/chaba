# Dispatch outcome — lesson-polish-run (20261126-084458, attempt 3)

## Result

Recurring lesson-polish pass complete. The 2026-11-26 07:40 audit flagged
7 lessons, all `R1:overdue` (every one had `next_review=2026-11-25` — their
first spaced review came due the day after the previous pass cleared the
190-flag backlog). Re-filed all 7 through `POST /lesson` with explicit
`next_review=2026-12-03` override.

- **Before:** 227 lessons, 7 polish-flagged (65 flagged rows total incl.
  out-of-scope R2/R5).
- **After:** 227 lessons, **0 R1/R3/R4 flags**; 61 total flagged = R2 thin
  ×6 (human-gated) + R5 consider-thai ×55 (exemptions; agent-tool-surfaces
  gained auto-Thai on re-file, clearing one R5).
- Verified: all bodies byte-identical via direct MediaWiki API diff
  (agent-tool-surfaces = identical EN + appended Thai); `learned_at`,
  `status`, `level`, `source` preserved; all 7 on canonical
  `lesson_wiki_title(topic)` titles — no dup hazard. Audit report:
  `docs/reports/lesson-audit/lesson-polish-after-2026-11-26.json`.

## Incident: board-api wedge on idc03 (resolved)

Mid-pass (~09:00–09:17Z) `chaba-board-api` stopped answering everything —
main thread deadlocked in `Thread.start()`, zero responses ~20min, all
doors 503/504. Manual `systemctl --user restart chaba-board-api.service`
restored it instantly; the pending write then landed in 8s. Carded as
**KNB-1423** (`board-api-accept-loop-wedge-auto-restart-7dd2f1`, backlog).

## Per-lesson actions

```
lesson-021a96fe34da claude-code-install      R1:overdue -> next_review 2026-12-03
lesson-75daf5e2997c claude-code-update      R1:overdue -> next_review 2026-12-03
lesson-7a0c0f5dc791 claude-code-openchamber R1:overdue -> next_review 2026-12-03
lesson-7bc595208216 agent-tool-surfaces     R1:overdue -> next_review 2026-12-03 (+auto-Thai, R5 cleared)
lesson-9a1db3e435c5 claude-code-standard    R1:overdue -> next_review 2026-12-03
lesson-b00c79064ad9 claude-code-auth        R1:overdue -> next_review 2026-12-03
lesson-ef9b09a8f8db ada-deploy-flow         R1:overdue -> next_review 2026-12-03
```

Before/after counts + action list posted to `lesson-polish-run` and
`lesson-audit-scheduled`.

## Trail

- `docs/ssot/jobs/education/2026-11-26-lesson-polish-pass.yml` — run record,
  incident writeup, verification method, pitfalls for future passes.
- `docs/reports/lesson-audit/lesson-polish-after-2026-11-26.json` — post-pass
  audit (227 lessons / 0 polish flags).

## Verify

```
POST https://idc03.taila0626a.ts.net:10000/lesson {"op":"list","content":1}
# then scripts/lessons-audit.py audit_one per row — expect 0 R1/R3/R4
# spot-check: wiki page Education:Claude-Code-Install shows
#   next_review=2026-12-03, learned_at=2026-11-18, updated=2026-11-26
```

lessons:
- board-api can wedge with main thread stuck in Thread.start() under load — journalctl stack dump + `systemctl --user restart chaba-board-api` is the fix; carded KNB-1423 for a real watchdog.
- When board-api is unresponsive, verify lesson writes via direct MediaWiki API (bot login from ~/.config/secrets/wiki-h3-gizmo.env on idc03) — bypasses the door entirely and is much faster than op:get (which rescans all ~227 Education: pages per call).
- html.escape(stored wikitext) resubmit via /lesson round-trips byte-identical — confirmed again on 7/7 bodies incl. Thai sections.
- Passing no_th:true on Thai-bearing lesson content skips re-translation WITHOUT setting meta.no_th; on Thai-free non-exempt content it would wrongly set the exemption — let the door auto-translate instead.
- Lessons due ON the audit date are not yet overdue — expect a small R1:overdue tail every day after a big polish pass; this is normal spaced-repetition cadence, not a regression.
