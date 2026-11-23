# Dispatch outcome — opencode-closeout-probe-omen (attempt 2)

## What changed

- `README.md`: appended one marker line — `opencode free_lane probe tony-omen 2026-11-23`.
  The append was performed **by OpenCode itself** (`opencode run --auto`,
  agent `build`), not by Devin — that is the probe's point.
- This outcome doc.

## OpenCode free_lane run (the probe result)

- Executor: `opencode` 1.19.4 (`/home/tony/.npm-global/bin/opencode`) on
  tony-omen, in this dispatch worktree.
- Lane/model: `free_lane` → `litellm/gemini-3.5-flash-lite` per
  `LANE_MODELS` in `scripts/board/runner-agent.py`.
- **Model deviation (key ACL):** the chaba `LITELLM_KEY`
  (`~/.config/secrets/litellm-chaba.env`) is denied
  `gemini-3.5-flash-lite` by the idc03 LiteLLM proxy
  (`key_model_access_denied`, HTTP 403 — key ACL, not model missing).
  The same key **does** serve `gemini-3.5-flash-lite-free`
  (the free-route alias of the same flash-lite model), plus
  `gemini-3.5-flash`, `gemini-2.5-flash-lite`, `bench`.
- **Config gap:** `gemini-3.5-flash-lite-free` was not declared under
  the `litellm` provider in `~/.config/opencode/opencode.json`
  (`ProviderModelNotFoundError`). Worked around with a run-local
  `OPENCODE_CONFIG` (`/tmp/opencode-probe-config.json`) declaring it —
  the same render-a-run-local-config pattern `opencode_profiles.py`
  uses. No user config was modified.
- Result: run exited 0; the agent edited README.md and nothing else
  (verified: `git diff` = exactly +1 line).
- First attempt at the run also hit a transient `ECONNREFUSED` once;
  a retry worked. Watch for flaky first-call connectivity to
  100.102.134.91:4000.

## Verifier

- `git diff` on the worktree = exactly one appended line in README.md.
- opencode run rc=0, model `gemini-3.5-flash-lite-free`,
  provider `litellm` (log: /tmp/opencode-probe3.log on tony-omen).
- `git push --dry-run origin HEAD` succeeded — the push guard that
  deferred this card for a month no longer applies from the dispatch
  worktree (SSH deploy key `github-chaba` works here; the guard was
  probing `~/CascadeProjects/chaba`, not the worktree).

## Commit/push + auto-merge

- Committed on `dispatch/20261123-183844-append-one-marker-line-to-read`
  and pushed to `origin` (github.com:tonezzz/chaba).
- Auto-merge: the dispatcher's phase-B close_out
  (`dispatch_repos.close_out` — checkpoint, push, goals gate, test gate,
  `--no-ff` merge into `origin/master`) runs after session end when it
  stamps `action.task_id` + `merge_pending`. Card action carries no
  `task_id` mid-session, so in-session close_out is not possible; the
  pushed branch is the strand-proof deliverable.

## Prior-failure diagnosis

Attempt 1 (`20261117-192751`) left zero commits — its worktree still
exists, clean tree, `origin/master..HEAD` empty, branch never reached
origin. That is the `dispatch-empty-closeout-verification-gap` class:
the session produced nothing and exited 1 (likely died before/at the
opencode step — the same key-ACL denial hit here is a plausible cause).

## How to verify

- `git log origin/master..dispatch/20261123-183844-append-one-marker-line-to-read`
  → README marker + this doc.
- `tail -1 README.md` on the branch → `opencode free_lane probe tony-omen 2026-11-23`.
- After close-out: marker line present on `origin/master`, card comms
  show `auto-merged <sha>`.

## Follow-ups worth a card/comm

- `litellm` virtual-key ACL on idc03: `gemini-3.5-flash-lite` denied
  for the chaba key while `gemini-3.5-flash-lite-free` is allowed —
  either grant the key the non-free id or re-point `LANE_MODELS.free_lane`
  / `~/.config/opencode/opencode.json` at the `-free` alias. Until then
  every `free_lane` opencode run on tony-omen fails admission-time.

lessons:
- opencode `-m` only accepts models declared in the loaded config —
  undeclared proxy models fail ProviderModelNotFoundError; render a
  run-local OPENCODE_CONFIG instead of editing the user config.
- LiteLLM `/v1/models` listing is not proof of access: chat completion
  can still return key_model_access_denied per virtual-key ACL.
- The tony-omen push guard deferred on `~/CascadeProjects/chaba` but
  dispatch worktrees push fine (github-chaba SSH deploy key) — probe
  the worktree, not the exec checkout.
