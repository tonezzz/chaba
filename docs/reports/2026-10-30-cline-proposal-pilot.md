# Bounded analysis-only pilot: OpenCode -> Cline proposal workflow

- Parent card: `opencode-cline-idea-proposal-workflow` (DEV-0975)
- Linked: `cline-kanban-con01-pilot` (KNB-0925), `cline-kanban-nest-worker-adapter` (KNB-0932) — distinct from the Nest-to-Cline *execution* adapter
- Pilot lane card: `cline-proposal-pilot-edu-no-th` (DEV-1004)
- Target card under analysis: `education-lesson-no-th-marker-readback` (OPS-1000), snapshot v1 `SNAP-edu-no-th-v1:d4cc6b50`
- Date: 2026-10-30 · Runner: mn01 · Mode: unattended devin-dispatch

## 1. Live-state verification (done before any run)

| Surface | Verified state | Evidence |
|---|---|---|
| Task-submission path | `cline-intake.timer` (15m) on con01 -> `intake.py --execute --limit 1` -> `bridge.py` -> `podman exec cline-kanban kanban task create/start` on disposable `/workspace`; wait_for_review -> collect_patch -> board-api `/comment` + card -> review | `systemd/generated/con01/cline-intake.*`, `ssot.jobs.yml` job `cline-intake`, `scripts/colab/packs/cline-kanban-nest-bridge/` |
| Adapter status | WORKING — `cline-intake-smoke` ran 2026-10-29 20:55, task 0bcda produced a 2116B patch and auto-moved to review (verdict: pipeline proven, content hallucinated as expected for 7B) | done card `cline-intake-smoke` |
| Model/provider | Ollama on tony-omen `http://100.75.102.88:11434/v1`; allowlisted pairs in bridge.py: ollama/qwen3:4b, ollama/qwen2.5:7b, openrouter/or-free-* (unused; paid blocked). LIVE from mn01: `/v1/models` 200, qwen2.5:7b + qwen3:4b present | live probe 2026-10-30 |
| Privacy boundary | Tailnet-only proxy `:3484` enforces BasicAuth: unauth GET `/` and `/api/tasks` -> 401 from mn01. App `:3485` unpublished on dedicated bridge; disposable `/workspace` git repo; no Chaba repo mounts; no secrets in agent container; auto-review/auto-commit off | live probe + stack.yml + audit SSOT |
| Finding (hygiene) | `cline-intake.timer` deployed via ssot.jobs.yml but NOT declared in con01 `expected_services` — fixed in this worktree (drift would flag it unexpected) | ssot.audit.hosts.yml |

## 2. Pilot design

- **Snapshot**: verbatim card YAML at `origin/master e6e3f683` + sha256 `d4cc6b50…` + card `updated 2026-10-30 10:57` in `evals/cline-proposal-pilot/manifest-v1.json`. Stale = hash or `updated` drift.
- **OpenCode role (intake)**: structured draft {goal, scope, constraints, done_condition, missing_questions, assumptions} via direct Ollama call — opencode CLI is not installed on mn01; same model family (qwen2.5:7b) as the eval profile. Substitution recorded, not hidden.
- **Cline role (analysis)**: two arms on the SAME brief — (a) live lane: board-api-created backlog card tagged `cline` picked up by the real intake timer on con01; (b) mn01 shadow: identical wrapped prompt through Ollama so content is inspectable from this runner (lane artifacts stay on con01's filesystem — a known retrievability limit).
- **Isolation finding**: the Cline task workspace is deliberately empty — it cannot see other cards/SSOT. "Compare with existing cards/procedures" only works via a context digest injected into the prompt (<=3000 chars). Marked as architecture constraint for the repeatable workflow.

## 3. Results

### Intake pass (OpenCode role, qwen2.5:7b, mn01)
- 53.2s, 739 tokens (546 in / 193 out). JSON-valid structured draft.
- Captured: correct goal; all 3 explicit constraints verbatim.
- Weak: done_condition vague (missed the regression-coverage requirement); missing_questions 1/3 useful ("how is WP REST meta registration handled" is the actual crux; other two generic).

### Shadow proposal (Cline role, qwen2.5:7b, mn01)
- 157.2s, 1730 tokens (717 in / 1013 out), 4623 chars, all 7 required sections, sentinel marker verbatim.
- Factual accuracy: no hallucinated systems/paths/URLs (unlike the earlier smoke). Conservative [E]/[A] labeling — treated injected context as assumption, correct given isolation.
- Dup detection: correctly classified `audit-miss-education-lesson-write-timeout` as adjacent-not-duplicate.
- Thin: viewpoints generic; options restate the spec's two branches without new analysis; open questions soft.

### Live lane run (con01, real intake path)
- Pilot card `cline-proposal-pilot-edu-no-th` (DEV-1004) created 14:52 +07 via board-api `/card`, pushed to origin by ~15:01, **still `backlog` at 16:03 — no pickup after ~70 min**. Envelope verified end-to-end offline against the live card file: `intake.card_to_spec` parses it and `bridge.validate_spec` passes (job_key `cline-cline-proposal-pilot-edu-no-th`, ollama/qwen2.5:7b, 900s, sentinel `SNAP-edu-no-th-v1:d4cc6b50`, prompt 2879ch).
- **Lane-arming finding**: 70+ min without pickup means either `cline-intake.timer` is not enabled on con01 or con01's chaba checkout doesn't sync on its own — the 2026-10-29 smoke's ~17-min turnaround is more consistent with a manual `intake.py --execute` run than a live timer. `chaba-repo-sync` is also not declared for con01. The submission *code* is deployed and contract-verified; the *scheduler* is unproven. Needs on-host check (`systemctl --user list-timers cline-intake.timer chaba-repo-sync.timer`) — flagged to Tony; the pilot card remains queued at the lane head and will run whenever intake actually executes.
- **Queue-starvation finding (live)**: two other backlog cards carry tag `cline` with no lane config — `repo-choice-decision-policy` (created 09:01) and `jack-llm-stack-agent-eval` (14:53). `intake.py --limit 1` processes only the first alphabetically-sorted candidate; a card missing `cline.deliverable` is skipped *silently* (journal only — no comment, no move). `repo-choice-decision-policy` had already starved the lane since 09:01; once this pilot clears, `jack-llm-stack-agent-eval` becomes the permanent head-of-line blocker. Heads-up comments posted on both cards.
- **Write-path note**: `intake.py` defaults `BOARD_API` to `https://tony-dell.taila0626a.ts.net/apps/board-api` (alive — likely a route to idc03); the generated unit carries no override, yet the smoke's comments landed canonically. Works empirically, but the default URL is misleading post-OPS-0725.
- **Snapshot staleness**: target card `updated` unchanged (2026-10-30 10:57) through the run — snapshot v1 remained current.

## 4. Metrics summary

| Metric | Value |
|---|---|
| Intake latency / tokens | 53.2s / 739 |
| Shadow analysis latency / tokens | 157.2s / 1730 |
| Lane end-to-end | NOT completed — no pickup in >70 min (timer likely unarmed on con01; see findings) |
| Factual accuracy | shadow: 0 unsupported claims detected; thin but honest |
| Missing-question capture | 1/3 genuinely useful |
| Tony corrections/intervention | 0 (unattended run; review request raised) |
| Card/task view consistency | sentinel contract + column transition observed in smoke; pilot pending |
| Stale snapshot detection | manifest hash + card `updated` — re-checked at collection |

## 5. Acceptance evaluation

- [x] Cold reader can follow proposal from either linked surface (shadow file + card comms + this report)
- [x] Decisions/status canonical on Chaba — Cline only wrote its deliverable file; the only board write is intake.py's lane contract on its own wrapper card
- [x] Stale snapshots detectable (manifest hash + updated field)
- [x] No unsupported claims in shadow output; no unapproved actions (local free model only, verified live before use)
- [~] One safe pilot — the shadow arm completed cleanly; the live lane arm is correctly armed at the queue head but its scheduler is unproven (>70 min no pickup). Counts as a partial pass pending the on-host timer check.
- [ ] Independent review — raised as board request for Tony (gate for procedure updates)

## 6. Recommendations (if repeatable after review)

1. Lane prompt should carry a context digest (done here) — repeatability needs a digest-builder, not ad-hoc writing.
2. Proposal artifacts are invisible off con01 — add a deliverable-content excerpt (first N lines) to the intake comment, or publish the patch to a retrievable surface.
3. Fix lane starvation: `intake.py` should skip unconfigured `cline`-tagged cards instead of stopping at the first candidate (scan all, pick first *valid*), and/or post a "missing cline config" comment on skipped cards so the failure is visible. This is a real, currently-active bug.
4. The smoke card carries two identical result comments — board-api /comment is not at fault (deliver_comment only relays); likely overlapping intake executions (manual + timer tick) before the review move landed. Worth an idempotency note, not a board-api fix.
5. Procedure updates (idea-intake, ai-lane-delegate): DEFER until Tony's independent review passes — one pilot is not "repeatable".
