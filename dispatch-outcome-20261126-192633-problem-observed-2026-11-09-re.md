# dispatch-outcome — runner-per-executor-caps (OPS-1284), attempt 2

## What changed

`scripts/board/runner-agent.py` — claim capacity is now split per
executor class:

- `RUNNER_CAP` (default 2) counts LOCAL executors only
  (devin/opencode/claude/script/container). New `RUNNER_REMOTE_CAP`
  (default 6, 0 disables) counts `RUNNER_REMOTE_EXECUTORS` (default
  `jules,nlm_batch,kk_mac_local`). A host holds cap_local + cap_remote
  claims concurrently — a jules/nlm-saturated host still claims local
  work and vice versa.
- Load gate is per-class (the OPS-1182 script split generalized):
  under `RUNNER_MAX_LOAD_PC` overload, `claim_pass` computes allowed
  gate classes — script claims need `RUNNER_SCRIPT_MAX_LOAD_PC` (2.0),
  remote claims need `RUNNER_REMOTE_MAX_LOAD_PC` (default 0 =
  load-independent, still bounded by lane quotas), heavyweight local
  claims hold. Non-overload capacity reasons still skip the whole pass.
- New `claim_executor(card)` resolves the executor a claim will run
  under (declared executor, nlm_batch lane pin, JEV kk-route,
  kk_mac_tried/servable fallback) — mirrored by `_cap_counts`,
  `_claim_gate`, `_gate_hint`, `_load_gate_classes`. State entries
  (`st[cid]["ex"]`) record the executor resolved AFTER `start_task` so
  an in-claim kk_mac→local fallback reclassifies correctly; entries
  without `ex` count local (conservative).
- `claim_pass` `note_defer(kind="cap")` per declined card names the
  holding cap; `verdict_pass` (/ready projection) mirrors the same
  per-class gate+cap order. `_note_capacity_skip` hostgate notes are
  now gate-class aware (`_gate_hint`) so exempt classes aren't noted.
- `reconcile_pass` zombie-restart cap check and adopt/restart state
  entries use the per-class counts; `finish_pass` kk fallback flips
  `ex`; duplicated dead nlm_batch block removed from `start_task`.

Ops surface (caps live in unit env drop-ins, same as RUNNER_CAP):

- `scripts/board/runner-cap.sh` — optional 4th arg `[remote-cap]` →
  `RUNNER_REMOTE_CAP` drop-in line (no mem ceiling — remote claims do
  ~zero local work).
- `ansible/playbooks/runner-cap.yml` — `runner_remote_cap` host_var;
  written only when defined (Linux drop-in + macOS plist lineinfile).
- `scripts/ops/kk-mac-runner-onboard.sh` — plist template gained the
  `RUNNER_REMOTE_CAP` key so the ansible lineinfile has a key to
  update (backrefs only rewrites existing keys).
- `scripts/devin/runner-tooling.manifest.json` — `runner_agent.sha256`
  pin bumped in the same change (contract test + sync/self-update gate).
- `docs/ssot/kanban/ssot.kanban.yml` — runner_hosts/load_gate prose
  updated for the split; kk-mac fleet prose gained a `(dispatch+script)`
  types declaration.

Tests: `tests/board/test_runner_agent_remote_cap.py` — 13 tests:
claim_executor resolution (nlm_batch remote, kk_mac servable/tried
fallback, local types), _cap_counts split, _capacity_reason fires only
when BOTH classes full, claim_pass end-to-end (local cap full + remote
free claims nlm_batch; remote cap full + local free claims devin;
load above every ceiling still claims remote but not devin/script;
mid-band load claims script+remote; both caps full skips pass; cap
declines land as 'cap' defer notes; state records actual executor).

Trail doc: `docs/ssot/jobs/kanban/2026-11-26-runner-per-executor-caps.yml`.

## Result

- `python3 -m pytest tests/board` — **1078 passed, 17 subtests**
  (full suite, ~13 min). Includes the 13 new tests.
- Fixed a PRE-EXISTING unrelated failure found by the suite:
  `test_queue_starvation.py::test_kkmac_is_declared` — the kk-mac
  runner_fleet prose named no served types so `fleet_capabilities`
  defaulted it to dispatch-only. Declared `(dispatch+script)` matching
  the e2e-verified script claim; verified the failure existed on HEAD
  before my change.
- Also fixed the expected `test_runner_tooling_contract` pin failure
  by bumping `runner_agent.sha256` (4259ca6f…0755).

## How to verify

- `python3 -m pytest tests/board/test_runner_agent_remote_cap.py -v`
- `python3 -m pytest tests/board/test_runner_tooling_contract.py
  tests/board/test_queue_starvation.py`
- Env surface: `RUNNER_REMOTE_CAP`, `RUNNER_REMOTE_MAX_LOAD_PC`,
  `RUNNER_REMOTE_EXECUTORS` documented in the runner-agent.py header
  and ssot.kanban.yml runner_hosts/load_gate.
- Ops: `scripts/board/runner-cap.sh <host> <cap> [gate] [remote-cap]`;
  ansible `runner_remote_cap` host_var.

## Notes / non-goals

- jules stays in the default `RUNNER_REMOTE_EXECUTORS` set for contract
  completeness — the lane is retired (provider EOL, removed from
  EXECUTORS 2026-11-20); live remote classes are nlm_batch +
  kk_mac_local. A stale jules pin fails closed in claimable().
- No fleet env changes were made — defaults apply on next
  runner-agent sync (pin bump gates that via sync-runner-tools.sh).
- Dispatch rails: no push, no commit to default branch, no deploy.

lessons:
- runner-tooling.manifest.json must be rewritten with a targeted
  string replace, not json.dump — the file's 2-space indent means a
  naive rewrite reformats all 34 lines and pollutes the diff.
- tests/board needs generated stacks/web/public/apps/board2/index.html
  (gitignored, scripts/render-board2.py) or
  test_control_pane_projection fails on a fresh worktree — generate it
  before assuming a suite failure is yours.
- fleet_capabilities parses the runner_fleet PROSE in ssot.kanban.yml
  with regexes — a host entry with no `(type+type)` paren silently
  defaults to dispatch-only; test_kkmac_is_declared caught a real
  stale-prose gap.
- claim-loop cap accounting: once BOTH classes hit cap the loop breaks,
  so per-card cap-decline defer notes only land for cards evaluated
  before that point — order test cards accordingly.
