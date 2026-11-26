# dispatch-outcome — grand-rename (phase 1: audit + gate)

## What was found

The grand-rename card's `spec:` field is **stale** — byte-identical to its
2026-10-16 creation, still describing the original persona-first scheme
(`member-ai`, `chaba-ai`, `kraut-ai`, `<persona>-ai.env`). The committed
decision the same day (aafeadfad, "Tony's scheme") switched to family-first
`ada-ai-<role>`, and the only deployed lane — `ada-ai-kraut.service` — follows
family-first. Spec was never updated.

Live audit on idc03 (all verified via SSH, not memory):

- **7 backend lanes live**: ada-ha-tony :8002, ada-ai-kraut :8003 (DONE),
  ada-dev :8005, ada-ha-ada :8006, ada-kk :8007, ada-chaba :8008,
  ada-kk-dev :8009. ada-pi-pwa retired (no unit); member/guest root is
  tailscale-serve `/ → :8002`.
- **Two lanes missing from rename_map**: `ada-chaba.service` :8008 (house
  ops-brain for LINE group — renaming to ada-ai-chaba would collide with
  :8002's target) and `ada-ha-ada.service` :8006 (second HA-enabled lab).
- **Port collision**: kaewta's renumber target `:8004` is occupied by the
  chaba-vault obsidian server (tailscale-serve :8443).
- **Env/keypool spec stale**: HA lanes use per-home dirs
  `~/.config/secrets/<home>/{backend.env,keys.json}`; flat
  `ada-ha-*-keys.json` are unreferenced leftovers from the 2026-10-23
  secret-stores migration — cleanup candidates, not rename targets.
- **Path layer is tailscale-serve on idc03** (not caddy): `/`, `/ai/kraut`
  (live), `/apps/ha/ada-{tony,michael,ha,kk,dev}`. Consumers: idc02 Caddy
  rewrites `/chatui` + `/ada-ws/*` → `/apps/ha/ada-*` on idc03; idc03 Caddy
  `app.surf-thailand.com /apps/ha/ada-tony`.
- **michael-dev twin rename genuinely pending**: `michael-dev.service` +
  `mha-state-push.service` still running on idc02.
- Health endpoint is `/api/health` (all lanes 200; `/health` 404s).

## What changed (repo, dispatch branch, commit 50cd0e5f47)

- `docs/ssot/infrastructure/ssot.system-map.yml` — rename_map reconciled:
  scheme note flagging the stale spec, 7-lane unit table (added ada-chaba +
  ada-ha-ada with dispositions), corrected env/keypool semantics, real path
  layer documented, open_decisions refreshed (4 OPEN items).
- `docs/ssot/jobs/ada/2026-11-23-grand-rename-execution-runbook.yml` — new:
  full live inventory + per-lane execution procedure + verification steps.

## Gate raised

- Board request `phase-1-gate-card-spec-field-is-stale-pe-c97beb` on
  grand-rename: (1) scheme family vs persona ★family; (2) ada-chaba :8008
  ★keep; (3) ada-ha-ada :8006 ★ada-ai-lab; (4) kaewta port ★keep :8007 vs
  move obsidian; (5) member-ai ★no unit.
- `$TASK_DIR/needs-input.txt` written with the same question — session
  paused for operator decision before touching live units.

## Result

Phase 1 complete. Phases 2–7 (live unit/env renames, tailscale-serve + caddy
path changes, optional renumber, SSOT/scripts sweep, verification, alias
drop) are gated on the scheme answer — they rename production voice lanes
and a wrong guess would need a second pass over all of them.

## How to verify / resume

- `git show 50cd0e5f47` — reconciled rename_map + runbook.
- Live spot-check: `ssh idc03 'systemctl --user list-units "ada-*" | head;
  tailscale serve status'` — matches the runbook inventory.
- On answer (board request or needs-input reply): execute per
  `docs/ssot/jobs/ada/2026-11-23-grand-rename-execution-runbook.yml`
  `procedure_per_lane`, one lane at a time, `/api/health` + serve-mount
  checks after each.

lessons:
- "card spec: fields freeze at creation — check git history of the spec before trusting it; this one predated the scheme decision it claims to specify"
- "rename_map drifted from live fleet: two lanes (ada-chaba :8008, ada-ha-ada :8006) were never in the map — always enumerate live units before trusting the SSOT table"
- "port renumber plans need a live ss check: kaewta's :8004 target is occupied by the obsidian vault server"
- "Ada lane health is /api/health not /health; lane paths are tailscale-serve mounts on idc03, not caddy routes"
