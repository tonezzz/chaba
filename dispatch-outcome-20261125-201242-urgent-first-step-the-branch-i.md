# Dispatch outcome — ada-voice-land-text-mode-session-persist

Card: `ada-voice-land-text-mode-session-persist` (push stranded branch, merge to main, deploy idc03, verify summary inflow)

## What changed / was found

- **Rescued the stranded commit.** On tony-macbook `~/CascadeProjects/ada-voice-wt-text-mode-persist`: `git fetch origin && git rebase origin/main` (clean — c14758b became `0f2212b`), then `git push origin dispatch/text-mode-session-persist`. Branch is now on GitHub, safe from merge-sweep GC.
- **Merged to main.** Live `~/CascadeProjects/ada-voice` on tony-dell is dirty on someone else's branch (`ada-consult-pr12-edit`), so I merged in a detached worktree (`/tmp/ada-voice-land-tmp`): `merge --no-ff` → `5a5379a`, pushed `HEAD:main`. Convention-matching merge commit; the dirty checkout was not touched.
- **Deployed on idc03.** `~/.local/bin/deploy-ada.sh`: ff `a060335 → 5a5379a`, tool-lint clean, pytest **2022 passed**, no live ws sessions to drain, all 9 units restarted and verified active.
- **Verified end-to-end.** Drove `ws://127.0.0.1:8009/ws?mode=text` on ada-kk-dev (instance `kk-dev`, key `user-kk-dev`), one text turn → `response_completed` → clean close. Journal showed `daily rollup regenerated over 1 session(s)`; MDDB `ada-ha-recall-summary-kk-dev` now holds `session-2026-11-25-1b315de0ac` with `kind=session-summary`, `date=2026-11-25` and a real LLM summary. The recall-summary inflow is restored.
- **Negative test (bonus).** Same flow on ada-dev: LiteLLM key `ada-dev-2` is at cap ($10.004/$10, resets 2026-12-01 — already carded as `budget-watch-ada-dev-2`). Turn 422'd, session closed, `persist()` ran and logged `summary failed`/`session_summary failed` as errors — graceful, no crash, service stayed active.

## Key finding — deploy topology gotcha

idc03's ada-voice `origin` is **not GitHub** — it is `ssh://tony-dell/home/tony/CascadeProjects/ada-voice`. `deploy-ada.sh` ff-merges `origin/main`, which resolves to **tony-dell's local `main` ref**, not `github.com/tonezzz/ada-voice@main`. Dell's `main` was 9 behind (checkout sits on a feature branch) so the first deploy attempt reported `already at origin/main (a060335)` — a stale-ref false negative that would have restarted prod on old code. Fixed by ff-ing dell's `main` via the clean `/tmp/ada-voice-ssot-get` worktree (`git merge --ff-only origin/main` → `5a5379a`). **After any ada-voice GitHub push, confirm dell's local `main` == `origin/main` before deploying.** Full write-up: `docs/ssot/jobs/ada/2026-11-25-text-mode-session-persist-land.yml`.

## Result

DONE — fix landed (`5a5379a` on ada-voice main), deployed to all idc03 ada services, session-summary inflow verified producing docs. Outstanding time-based check: next `ada-memory-distill` run Sun 2026-11-30 09:45 +07 should report >0 new docs (inflow source now exists).

## How to verify

- `ssh idc03 'cd ~/CascadeProjects/ada-voice && git log --oneline -2'` → `5a5379a`
- `systemctl --user is-active ada-ha-tony ada-dev ada-kk-dev ada-line-relay ada-tg-relay` on idc03 → all active
- MDDB: collection `ada-ha-recall-summary-kk-dev`, key `session-2026-11-25-1b315de0ac`, meta `kind=session-summary`

lessons:
- idc03 deploy-ada.sh fetches `origin` = tony-dell's LOCAL checkout path, not GitHub — a GitHub push alone is not deployable; dell's `main` ref must be ff'd to `origin/main` first or the deploy silently gates old code ("already at origin/main" lie).
- Killing the local `ssh` client does NOT kill the remote python — the ws stayed open and `active_sessions` stayed 1 until the remote pid was killed on idc03.
- A ws receive loop that checks its deadline only inside `async for` blocks forever when no frames arrive — wrap in `asyncio.wait_for`.
- ada-dev's LiteLLM key `ada-dev-2` is budget-capped until 2026-12-01 — use ada-kk-dev (`user-kk-dev` key, :8009) for live text-mode verification until then.
