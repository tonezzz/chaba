# Dispatch outcome — follow-up to OPS-0184 (claude-agent-idc02-opencode)

Runner: idc02 · Branch: `dispatch/20261118-135051-follow-up-to-ops-0184-done-scr` · Commit: `91b06ea27c`

## What was found

**Scope 1 — launch path + env injection.** There is **no host-level**
`opencode serve --hostname 0.0.0.0 --port 4096` on idc02. Both matching
PIDs live inside rootless podman containers (conmon parents), each on its
own private podnet, launched by generated systemd user quadlets
(`~/.config/containers/systemd/`):

- `ada-code` — Ada OpenCode control-plane responder backend, opencode
  **v2.2.6**, LiteLLM-keyed (`ada-code.env`), tool-restricted.
- `jack-opencode` — Jack's isolated web IDE behind the jack-enroll
  gateway, opencode **1.19.4** (predates the claude-agent provider, which
  needs >= 2.2.x), LiteLLM-only by committed config
  (`stacks/idc02/jack-ide/opencode/opencode.json`).

`OPENCODE_CLAUDE_PATH=<host path>` is therefore a no-op injection target:
the host path is not mounted in either container, container env comes only
from quadlet `Environment=`/`EnvironmentFile`, and idc02 has neither the
pinned claude-code install (`~/CascadeProjects/tony-projects/claude-code`
missing) nor claude auth (`~/.claude/.credentials.json` absent). The
host install was deliberately **not** performed — it cannot help the
containers and would be undeclared host clutter.

Bonus finding: a dormant leftover `/tmp/ocv2/opencode-bin serve --service`
(loopback :49374, orphaned to init since 2026-11-08, launch PWD =
ada-opencode workspace, no children, no connections) — not the :4096
surface; flagged to Tony as a cleanup candidate.

**Scope 2 — meant to serve model sessions?** ada-code: no — a worker
backend. jack-opencode: yes, but only for Jack and only through the
LiteLLM lane by documented design (isolation posture forbids host mounts).
Wiring claude-agent into it is a design change (image rebuild, scoped ro
claude-code mount, OAuth inside disposable HOME — needs Tony, anthropic
egress from podnet). Raised to Tony as a board request with options
(close [recommended] / wire-jack / litellm-claude).

**Scope 3 — tony-dell re-check.** `openchamber-wire.sh --host tony-dell
--check` re-run: all green (pinned 2.1.327, oauth logged in, env var
registered, credential stored, models enabled). No periodic timer exists;
`--check` is read-only and safe to re-run after any openchamber update.

## What changed

- `docs/kb/openchamber-claude-agent-provider.md` — idc02 fleet row
  corrected; new "idc02: no injection target" section.
- `docs/ssot/jobs/devnest/2026-11-18-idc02-opencode-claude-agent-probe.yml`
  — new job doc with the full trail.

## Result / status

Investigation complete; no host mutation performed (nothing safe+useful to
mutate — the only real injection paths are design changes gated on Tony).
Card has a comment with findings + a pending board request for direction.
Awaiting Tony's answer on the jack-ide question; the card can close as
documented if he picks the recommended option.

## How to verify

```bash
# on idc02
pgrep -af "opencode serve"            # :4096 PIDs have conmon parents
podman exec jack-opencode opencode --version   # 1.19.4
podman exec ada-code      opencode --version   # v2.2.6

# anywhere with ssh
scripts/claude-code/openchamber-wire.sh --host tony-dell --check
```
