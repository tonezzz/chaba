---
category: operations
type: runbook
status: verified
---

# OpenChamber `claude-agent` provider wiring

The `claude-agent` provider (opencode >= 2.2.x) runs the local Claude Code
binary through the Agent SDK — Anthropic **subscription** auth, no API key.
It is a separate provider lane: it is **not** routed through LiteLLM. Do not
touch the LiteLLM lane (`litellm` provider, `~/.config/secrets/litellm-*.env`,
the `10-litellm-env.conf` systemd drop-in).

Canonical procedure: **`scripts/claude-code/openchamber-wire.sh`** — one
idempotent script that does the whole recipe on a host. Verified on tony-dell
2026-11-18 (wired manually, then re-verified by the script incl. a live
`claude-agent/haiku` smoke turn).

## Quickstart

```bash
# on the OpenChamber host itself
scripts/claude-code/openchamber-wire.sh            # wire (idempotent)
scripts/claude-code/openchamber-wire.sh --check    # verify only, no writes
scripts/claude-code/openchamber-wire.sh --smoke    # wire + one real haiku prompt

# from any host with ssh access — the script re-executes itself remotely
scripts/claude-code/openchamber-wire.sh --host tony-omen --check
scripts/claude-code/openchamber-wire.sh --host tony-omen
```

Port is auto-discovered (systemd user unit `ExecStart --port`, then process
args, then `:3000`); override with `--port N`. Pin defaults to
`CLAUDE_CODE_VERSION=2.1.327`.

## Prerequisites per host

1. **Pinned claude-code install** at
   `~/CascadeProjects/tony-projects/claude-code`
   (`install.sh`/`update.sh` in that dir; the script installs it if missing —
   needs npm/Node 20+).
2. **Claude login done on that host** — `claude auth status` must report
   `loggedIn:true`. OAuth login cannot be automated; on a headless host use
   `claude setup-token` or run `claude auth login` once over an interactive
   session. On Linux, creds may live in the keyring rather than
   `~/.claude/.credentials.json` — trust `claude auth status`, not the file.
3. **OpenChamber running** (`@openchamber/web`, `openchamber.service`).
   The script writes `OPENCODE_CLAUDE_PATH` into the user-level environment
   store so the managed opencode subprocess gets it.

## The manual recipe (what the script does)

1. `PUT /api/environment` `{variables:{OPENCODE_CLAUDE_PATH:"<abs path to
   node_modules/.bin/claude>"}}`.
   - The env store is **cached in memory** — editing
     `~/.config/openchamber/environment.json` directly does NOT apply. Use
     the API or Settings > General > Environment variables.
   - PATCH semantics: a string sets, `null` removes, omitted names keep.
   - `GET /api/environment` returns `{names:[...]}` only — values are never
     readable via the API (secrets-safe). The script diffs against the
     on-disk file for change detection.
2. `POST /api/config/reload` — restarts managed opencode; defers while
   sessions are busy, so model availability may lag.
3. `opencode auth login claude-agent --method claude-login` —
   non-interactive, records an `external` credential
   (`{"type":"external","methodID":"claude-login"}` in
   `~/.local/share/opencode/opencode.db` `credential` table).
4. Verify: `GET /api/model` lists `claude-agent/{opus,sonnet,haiku}` enabled.

### API auth

Mint a UI session JWT yourself — the API has no machine token:

- secret = raw contents of `~/.config/openchamber/jwt-secret` (UTF-8),
- payload `{type:"ui-session", iat, exp}`, HS256,
- send as cookie **`oc_ui_session_<port>`** (the request port is folded into
  the cookie name; bare `oc_ui_session` only when the Host has no port).

Fallback: `POST /auth/session {password: $OPENCHAMBER_UI_PASSWORD}` (from
`~/.config/openchamber/startup.env`) returns the same cookie.

### Smoke-prompt gotchas

- Session model switch: `POST /api/session/<id>/model` with
  `{model:{id:"haiku",providerID:"claude-agent",modelID:"haiku"}}`.
  **`id` must be the bare model id** — `claude-agent/haiku` doubles the
  prefix and 400s.
- Prompt body is `{text:"..."}` on opencode >= 2.3 (older 2.x took
  `parts[]`). The response is an admission (`delivery:"steer"`); poll
  `GET /api/session/<id>/message` for the assistant message with
  `model.providerID=="claude-agent"` and `finish` set.

## Fleet rollout state (probe 2026-11-18)

| host | OpenChamber | opencode | claude-code install | claude login |
|---|---|---|---|---|
| tony-dell | yes (:3000, `openchamber.service`) | 2.3.2 | 2.1.327 | yes — **wired + smoke-verified** |
| tony-omen | no | no | yes | yes (.credentials.json) |
| tony-macbook | no | yes (`~/.local/node/bin`) | no | no |
| idc02 | no | host bin v2.2.7 + 2 podman workers (see note) | no | no |
| kk-mac | no | no | no | no |
| mn01, idc03, con01, michael-ha | no | no | no | no |

tony-dell is currently the **only** OpenChamber host, so "roll out" today =
re-verified idempotently there. For a new OpenChamber host: install
OpenChamber first (service + `ssot.audit.hosts.yml` declaration per
host-hygiene rules), install pinned claude-code, `claude auth login` once,
then run this script. Standalone `opencode serve` (no OpenChamber) can use
the same provider by exporting `OPENCODE_CLAUDE_PATH` in its own environment
plus step 3 — outside this script's scope.

### idc02: no injection target (probe 2026-11-18, card claude-agent-idc02-opencode)

There is **no host-level** `opencode serve --hostname 0.0.0.0 --port 4096`
on idc02 — both matching processes live inside rootless podman containers
on private podnets (quadlets in `~/.config/containers/systemd/`):

- **ada-code** (opencode v2.2.6) — Ada's control-plane responder backend;
  LiteLLM-keyed, tool-restricted. A worker, not a user-facing model surface.
- **jack-opencode** (opencode **1.19.4** — predates the claude-agent
  provider, which needs >= 2.2.x) — Jack's isolated web IDE, reachable only
  through the jack-enroll gateway. LiteLLM-only by committed config
  (`stacks/idc02/jack-ide/opencode/opencode.json`); its documented isolation
  posture forbids host mounts beyond workspace + disposable home.

`OPENCODE_CLAUDE_PATH=<host path>` cannot help either container: the host
path is not mounted, container env comes only from quadlet
`Environment=`/`EnvironmentFile`, and claude OAuth creds would have to live
inside each container's HOME. Wiring claude-agent into jack-ide is a design
change (image rebuild to opencode >= 2.2, scoped read-only claude-code
mount, OAuth login inside the container, anthropic egress from the podnet)
— a Tony decision, tracked on card `claude-agent-idc02-opencode`. If Jack
needs Claude-class models without breaking isolation, the in-model path is
a LiteLLM alias, not this provider.

Also observed on idc02: a dormant leftover
`/tmp/ocv2/opencode-bin serve --service` (loopback :49374, orphaned to init
since 2026-11-08, launch PWD = ada-opencode workspace, no children, no
connections) — not the :4096 surface; cleanup candidate.

## Gotchas

- **Auth is per-host.** The claude OAuth token lives in each host's
  keyring/`~/.claude` — wiring a new host needs a real login there once.
- **Reload deferral.** `POST /api/config/reload` waits out busy sessions;
  re-run `--check` a minute later if models don't show immediately.
- **SameSite=Strict cookie.** The UI session cookie only flows same-site —
  irrelevant for localhost API calls, matters only for browser/iframes.
