# dispatch-outcome — document AI lane delegation procedure (ai-lane-delegation-procedure / OPS-0823)

## What changed

- **devin-kb (canonical doc):** `docs/tools/ai-lane-delegation.md` written to
  `tony-dell:~/devin-kb`, committed `3b26813` on `main` — NOT pushed (dispatch
  rails). Also linked from `docs/tools/ai-workforce-eval.md` phase-4
  deliverable. MDDB pickup happens via `sync-docs-to-mddb.py` on dell.
- **Lesson filed:** `scripts/lesson-add.py` → board-api `/lesson`,
  topic `ai-lane-delegation`, WP post 2295, next-review 2026-10-31.
- **Chaba worktree (branch dispatch/20261024-165135-…, commit 5e91fc24):**
  - `docs/ssot/ssot.procedures.yml` — new `ai-lane-delegate` entry in the
    ai/eval section pointing at the devin-kb doc.
  - `docs/ssot/jobs/workflow/2026-10-24-ai-lane-delegation.yml` — job trail:
    deliverable, all 3 pilot results, sharpened boundaries, verify commands.
- **Board:** 3 progress comms posted on `ai-lane-delegation-procedure`.

## Doc contents (the 5 spec items)

1. Routing rule: task-class → lane table (L0 codemod / L1 free flash-lite /
   L2-L3 paid / L4 Devin dispatch).
2. Per-lane go-live gates: bench pass on the class + mandatory inline
   verifier + blast-radius limit + spend headroom + explicit target_host.
3. Protocol: card → classify → route → gate → run → verify → escalate
   (L0→L1→L2→L3→L4→Tony; two clean fails = escalate, never silent retry),
   incl. the script-card recipe and the model-lane prompt contract.
4. Go-live matrix dated 2026-10-24: L0 pattern-fix LIVE; L1 single-step ops
   LIVE (gated); L1 multi-step/code NOT live; L2/L3 code-with-test LIVE
   (Fable 7/7 in 60s); L4 LIVE; OpenHands/local-CPU NOT live.
5. Roles: inline verifier, dispatcher, runner-agent, QC layer
   (session-audit/reopen_events/key-watch), Tony gates; babysitting-minutes
   is the true cost metric.

## Pilot on 3 real tasks — results

1. `timer-alert-idc03-ada-memory-sync` — free lane FAILED cleanly
   (multi-step remote diagnosis; also proved the target_host rule). The
   underlying alert later resolved via L4.
2. `stash-graveyard-triage` — free lane COMPLETED (7 stashes, all droppable).
3. `check-traffic-report-automation` — run this session on idc02 via
   `opencode run --model litellm/gemini-3.5-flash-lite` in-worktree.
   Run 1 FAILED: searched correctly but never wrote `verdict-pilot3.json`;
   the verifier gate caught it (missing artifact = fail, not false-done).
   Run 2 with the **artifact-first prompt contract** (write the JSON
   skeleton before searching, then rewrite filled) PASSED — verdict
   correct: no traffic-report automation exists (`stacks/services/
   traffic-cam` is snapshots only). Minor schema sloppiness noted
   (empty `related_components`).

New documented lesson: **write-then-fill rescues flash-lite's early-stop
failure mode; search-then-write loses it.**

## How to verify

- `ssh tony-dell 'cd ~/devin-kb && git log -1 --oneline docs/tools/ai-lane-delegation.md'`
  → expect `3b26813 docs(tools): AI lane delegation procedure …`
- `git show 5e91fc24 --stat` in this worktree.
- Card comms on `ai-lane-delegation-procedure` carry pilot #3 + doc comms.
- WP lesson: post 2295 (topic ai-lane-delegation).

## Open follow-ups (not blocking)

- devin-kb commit is local-only on tony-dell (`main` ahead 1) — push when a
  session is allowed to push remotes.
- `check-traffic-report-automation-a9645b` stays backlog (Tony chose
  "backlog as feature" 2026-10-11); pilot confirmed no report automation
  exists — accurate.
