# Dispatch outcome — opencode-task-agent-profiles

Card: `opencode-task-agent-profiles` · Runner: `idc02` ·
Branch: `dispatch/20261027-194243-add-task-scoped-opencode-agent` ·
Date: 2026-10-27

## What changed

**New profile layer** — `evals/opencode-lane/profiles/<id>/` holds
`profile.yml` (policy) plus a `fixture/` (task.yaml contract,
prompt.md, held-out verify.py, inputs). Four profiles shipped:

| profile | status | scope |
|---|---|---|
| `ops-readonly` | enabled, S1–S3 | host/MCP health reports, bounded bash allowlist, no writes |
| `ssot-research` | enabled, S1–S3 | read-only SSOT retrieval, mandatory resolvable citations, **no bash** |
| `storage-dryrun` | enabled, S1–S3 | inventory + classification only; `deletions:[]`/`dry_run:true` enforced by deterministic policy in runner + held-out verifier |
| `branch-code` | **disabled**, unattended:false | isolated-worktree code profile — defined for validation, admits nothing; unmapped in routing |

**`scripts/devnest/opencode_profiles.py`** (new, ~870 lines) —
`list / lint / check / render / run / classify`. `render` writes a
run-local `opencode.json`: profile agent only, builtin
`build`/`plan`/`general` disabled, MCP rendered only when the host's
allowlist proxy exists (idc02 has none → zero MCP), permission rules
from the profile. `run` = lint + envelope⊆profile narrowing check +
lane admission + `opencode run --agent <profile>` (OPENCODE_CONFIG
points at the rendered config; global config keeps zero MCP) +
message-mode artifact extraction + held-out verify + durable metric.

**`lane_gate.py`** — `profile:` envelope field; for non-shadow
opencode jobs: `missing_profile`, `unknown_profile`,
`profile_disabled`, `profile_not_unattended` denials; `profile`
recorded on every metric.

**`runner-agent.py`** — a lane reaches `opencode run` only when a
profile resolves (`action.profile` wins, else `LANE_PROFILES`:
`free_lane → ops-readonly`). No profile → Devin dispatch path. The
generic build agent is never addressed unattended.

**Envelopes** — `evals/opencode-lane/jobs/p1-{ops-readonly,
ssot-research,storage-dryrun}-idc02.yaml` (S1 canaries) +
`p5-branch-code-disabled.yaml` (validation-only).

**Tests** — `tests/devnest/test_opencode_profiles.py` (44 tests) +
test_lane_gate additions; **116 devnest tests pass**.

## Results (acceptance)

- **Profile config validates**: `opencode_profiles.py lint` clean for
  all 4; `check` passes the 3 enabled envelopes, denies branch-code.
- **ops-readonly real job**: PASS — true idc02 health snapshot,
  verifier re-collected every fact within tolerance; final run
  `evals/opencode-lane/runs/p1-ops-readonly-idc02-20261027-203427`,
  0 denials.
- **ssot-research real job**: PASS — board-api write path +
  card-union driver answer with 3 resolvable citations;
  `runs/p1-ssot-research-idc02-20261027-202415`, 0 denials.
- **storage-dryrun refuses unsafe candidates**: PASS — all 7 seeded
  traps refused (`protected_root`), 2 legit pycache proposals
  `automatic_ok`, `deletions:[]`, `dry_run:true`;
  `runs/p1-storage-dryrun-idc02-20261027-203100`, 0 denials.
- **Metrics durable**: 12 records in
  `~/.local/state/opencode-lane/metrics.jsonl` with profile identity,
  tokens, wall_s, denials, failure reasons — including the
  `quota_exceeded:S1 did 3/3` denial the gate itself produced.
- **branch-code not enabled**: profile `status: disabled`, denied on
  every axis at admit (`profile_disabled`, `profile_not_unattended`,
  `wrong_stage`, `denied_path`, `env_gate`); unmapped in
  `LANE_PROFILES`. **cleanup-apply does not exist.**

## Iteration findings (shipped in this branch)

- `extract_artifact` returned a nested `{citation}` over the outer
  artifact → now takes the last **top-level** JSON object.
- A verifier crash lost a run (no metric, stale inflight) → `_verify`
  fails closed and still records the metric.
- Scope-diff flagged runner landings (`runs/`, artifact path) →
  excluded.
- `cat /proc/*` in the ops bash allowlist could never fire under
  `external_directory:deny` → removed; prompts teach allowed
  equivalents + one-command-per-call.
- Cmd-level verifier-peek audit flagged fixture paths appearing as
  proposal *data* → only `verify.py` reads flag now (file-arg peeks
  stay strict); `2>/dev/null`/`>&fd` no longer count as redirect
  writes.
- S1 quota counter was reset 3× during canary iteration (documented
  in `stage.json` history — the quota gate fired correctly each time).

## How to verify

```bash
python3 scripts/devnest/opencode_profiles.py lint        # 4 profiles OK
python3 scripts/devnest/opencode_profiles.py list
python3 scripts/devnest/opencode_profiles.py check \
    evals/opencode-lane/jobs/p1-ops-readonly-idc02.yaml
python3 scripts/devnest/lane_gate.py admit \
    evals/opencode-lane/jobs/p5-branch-code-disabled.yaml  # denied
python3 -m unittest discover -s tests/devnest -p 'test_*.py'  # 116 pass
ls evals/opencode-lane/runs/p1-*/verdict.json            # pass verdicts
tail -3 ~/.local/state/opencode-lane/metrics.jsonl       # durable ledger
```

Docs: `evals/opencode-lane/PROCEDURE.md` (profiles section) +
`docs/ssot/jobs/devnest/2026-10-27-opencode-task-agent-profiles.yml`.
