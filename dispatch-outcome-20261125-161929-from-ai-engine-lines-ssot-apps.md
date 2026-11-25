# Dispatch outcome — ada-engine-self-report (ADA-0153)

Card `ada-engine-self-report` — from ai-engine-lines
(`ssot.apps.ada-engines.yml` contract_v1 + engine_registry): engines did
not announce who they are, so which engine answered a turn was not
auditable and engine swaps could not be verified mechanically.

## What changed (ada-voice repo — the actual deliverable)

Worktree `~/CascadeProjects/ada-voice-wt-engine-self-report`, branch
`dispatch/engine-self-report` off `origin/main` (a060335), commit
`0b034a1` — **not pushed** (dispatch rails; merge/push is the
operator's close-out step, same landing path as sibling
`dispatch/engine-contract-suite`).

`pwa_server.py`:

- `ENGINE_LINE = "ada"`, `ENGINE_CONTRACT_VERSION = "v1"` constants.
- `_engine_build_version()` — `ADA_ENGINE_VERSION` env override wins
  (release stamping for non-git engines), else `git rev-parse
  --short=12 HEAD` of the checkout, else `"unknown"`. Resolved once,
  cached in `_ENGINE_VERSION`.
- `engine_identity()` — returns `{engine_line, engine_version,
  contract_version}`.
- `_ready_event(session_id)` — builds the ws `ready` payload with the
  identity fields; used by BOTH ready send sites (initial session ready
  and the provider-reconnect ready, which is a new session boundary and
  needs identity too).
- `/api/health` — both return branches (normal and CHABA_MODE
  chaba-guest) gain the three fields as flat top-level keys.

`tests/test_engine_identity.py` — 6 unit tests (identity shape,
contract_version=v1, env override, git-sha fallback, ready payload,
/api/health in both CHABA_MODE branches).

`docs/ssot/jobs/ada/2026-11-25-engine-self-report.yml` — job trail with
field semantics, decisions, verification, follow-ups.

## Field semantics (per ssot.apps.ada-engines.yml)

- `engine_line`: `"ada"` — the product family; a future chaba-ops/edge
  engine reports its own line.
- `engine_version`: the deployed build — SSOT defines today's version
  AS the deployed upstream commit, so the git sha is the honest
  mechanical value; `ADA_ENGINE_VERSION` env lets a non-git engine
  stamp a real version.
- `contract_version`: `"v1"` — contract_v1 major; moves only on a
  breaking lane-contract change.

## Verification

- `pytest tests/test_engine_identity.py` — **6 passed**
- `pytest tests/ -x -q` (full suite, borrowed engine-contract venv) —
  **1986 passed, 7 skipped**
- `python3 -m py_compile pwa_server.py tests/test_engine_identity.py` —
  clean
- `scripts/tool-lint.py` — clean (69 warnings, none new)
- Live verification pending post-merge: `curl /api/health` on a lane +
  one /ws session asserting the ready event carries the fields.

## Notes / follow-ups

- Sibling card `ada-engine-contract-suite`'s `contract_health`
  scenario can extend its `/api/health` `contains` to assert
  `engine_line`/`contract_version` once both branches land (noted in
  the job trail).
- Same landing caveat as the sibling: this card's task meta is
  repo=chaba, so merge-sweep lands the chaba dispatch branch (this
  doc); the ada-voice branch `dispatch/engine-self-report` needs the
  same manual/operator merge path as `dispatch/engine-contract-suite`.

lessons:
- ada-voice dispatch worktrees can borrow a sibling worktree's .venv
  for pytest (engine-contract's venv ran this suite fine — dep_stubs
  covers missing heavy deps); no need to rebuild one per worktree.
- pwa_server.py has TWO ws 'ready' send sites (initial + provider
  reconnect) — engine/session metadata must go through a shared helper
  (_ready_event) or the reconnect path silently loses it.
- /api/health has two return branches (normal + CHABA_MODE
  chaba-guest) — identity fields must be added to both or guest lanes
  self-report nothing.
- contract_version belongs in the payload as a literal "v1" — do NOT
  derive it from git describe/tags; it is the lane-contract major, a
  different axis from engine_version (the deployed build sha).
