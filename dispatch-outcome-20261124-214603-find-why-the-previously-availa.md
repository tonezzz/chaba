# Dispatch outcome — ada-sweep-menu-regression-20261108

## What was found

The `/ada sweep` menu is not a standalone slash-command registration — it is a
bullet inside the `/ada` OpenCode custom command defined in
`.opencode/commands/ada.md`. **Client surface:** the ada-code OpenCode
workspace on idc02 at `~/.local/share/ada-code/workspace` — the project
directory the ada-ocb OpenChamber pane opens (ADA-0186 smoke sessions ran
there) and the deploy target of the governed `POST /opencode-command`
publisher on board-api (canonical `stacks/idc02/ada-code/commands/ada.md`).

**Why it disappeared:** on 2026-11-24 ~10:38 +07 the ada-code /
ada-code-enroll / jack-ide quadlets were retired
(`*.retired-20261124` under `~/.config/containers/systemd/`), the public
routes `ada-code.surf-thailand.com` / `opencode-ada.surf-thailand.com` were
removed from the Caddyfile, and the entire `~/.local/share/ada-code` tree —
including `workspace/` with `.opencode/commands/ada.md`, the ada-control MCP
config, and session state — was moved to
`~/backups/retired-opencode-20261124/`. Live opencode on idc02 is now host
`opencode-serve.service` (v2.4.1) plus OpenChamber at
`ada-ocb.surf-thailand.com`. With the project dir gone, the pane had no
`/ada` command file at all — so `/ada sweep` (and every other `/ada`
subcommand) vanished from the menu. The `ada_sweep` backend was never at
fault (idc03 ada-dev `/api/tools` lists it; untouched).

## What changed

- idc02: moved `~/backups/retired-opencode-20261124/ada-code/workspace` back
  to `~/.local/share/ada-code/workspace`. Only `workspace/` was restored —
  the quadlets, enroll units, Caddy routes, and the container-only dirs
  (`home/`, `state/`, `gdrive/`, `devin-summaries/`) remain retired/in backup.
- Trail: `docs/ssot/jobs/ada/2026-11-24-ada-sweep-menu-restore.yml`.

## Verification

- `POST /opencode-command {op:"verify"}` → `match:true`,
  canonical_sha == deployed_sha == `077aaff3…` (the governed canonical with
  the sweep native-menu block).
- `.opencode/commands/ada.md` contains the `/ada sweep [n]` bullet.
- MCP bridge smoke: `ada_mcp.py` (via `~/.local/venvs/ada-mcp`) starts and
  reports `ada-control bridge git-678b960 starting (tools=30)`.
- Note: opencode reads `.opencode/commands/` at session start — an
  already-open pane session may need a reload before the menu reappears.

## Follow-ups (not done — flagged on the card/job note)

- If the Ada OpenCode responder is meant to be fully retired, the durable
  fix is re-homing `commands/ada.md` + the ada-control MCP stanza into the
  ada-ocb workspace (`~/CascadeProjects/ada-ocb/.opencode/`); otherwise the
  restored path keeps the publisher and pane working as before.

lessons:
- `/ada sweep` was never a separate command file — it is a bullet inside `opencode/commands/ada.md`; grep for the parent command before assuming a missing registration.
- Retiring a quadlet stack on idc02 also means checking `~/.local/share/<app>` — the OpenChamber pane used the container's workspace dir as its project root, so moving it broke the client surface even though the container itself was the retired part.
- The `opencode-command` publisher's `verify` op is a fast way to prove deployed==canonical for ada-code command files.
