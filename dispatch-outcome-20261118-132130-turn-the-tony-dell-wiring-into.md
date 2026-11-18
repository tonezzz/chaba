# claude-code-openchamber-provider-rollout — outcome

## What was delivered

- **`scripts/claude-code/openchamber-wire.sh`** — the tony-dell recipe as a
  single idempotent bash script. Modes: default `wire`, `--check` (verify
  only, exit 1 on failure), `--smoke` (real claude-agent/haiku prompt),
  `--host <name>` (re-executes itself over ssh), `--port`, `--force`,
  `--no-reload`. Steps: ensure pinned claude-code install
  (`~/CascadeProjects/tony-projects/claude-code`, pin `CLAUDE_CODE_VERSION`,
  default 2.1.327) → `claude auth status` gate → OpenChamber port discovery
  (unit ExecStart > process args > :3000) → UI auth (mints HS256
  `{type:"ui-session"}` JWT from `~/.config/openchamber/jwt-secret`, cookie
  `oc_ui_session_<port>`; password-session fallback) →
  `PUT /api/environment {variables:{OPENCODE_CLAUDE_PATH:<bin>}}` →
  `opencode auth login claude-agent --method claude-login` →
  `POST /api/config/reload` (only when something changed) → verify
  `GET /api/model` lists enabled claude-agent models.
- **`docs/kb/openchamber-claude-agent-provider.md`** — runbook: quickstart,
  prerequisites, the manual recipe, API-auth details, smoke-prompt gotchas,
  per-host fleet state, and LiteLLM-lane boundary (untouched).

## Verified live on tony-dell

- `--check`, `wire`, `--force`, `--smoke` all pass. `--force` exercised the
  full write path: PUT 200, credential re-record, `POST /api/config/reload`
  200, models re-verified after reload. `--smoke` created a session, set
  `claude-agent/haiku` (bare id), sent `{text}` prompt, and polled a real
  assistant reply ("ok", providerID claude-agent, finish stop).
- Idempotency confirmed: fully-wired host → zero writes, reload skipped.

## Rollout finding

**tony-dell is the only OpenChamber host in the fleet today** — probed
tony-omen, tony-macbook, macbook, kk-mac, mn01, idc02, idc03, con01,
michael-ha over ssh: no openchamber CLI/config/process/unit anywhere else.
So "apply to remaining OpenChamber hosts" is a no-op; the script + runbook
are the rollout mechanism for future installs. Nearest-ready: tony-omen
(claude-code + claude login present, needs OpenChamber itself);
tony-macbook and idc02 have opencode but no claude install/login.

## Recipe corrections found while scripting

- Prompt body on opencode 2.3.x is `{text:"..."}` (the `parts[]` shape in
  older notes 400s with `Missing key at ["text"]`).
- Prompt is async (`delivery:"steer"`); replies are polled from
  `GET /api/session/<id>/message` (assistant msg with `model.providerID` +
  `finish`).
- `GET /api/environment` returns names only — the script diffs the on-disk
  `environment.json` for change detection and warns when unreadable.

## How to verify

```
scripts/claude-code/openchamber-wire.sh --check    # tony-dell: all green
scripts/claude-code/openchamber-wire.sh --smoke    # real haiku turn
scripts/claude-code/openchamber-wire.sh --host <h> # when another host installs OpenChamber
```
