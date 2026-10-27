# Dispatch outcome — dead-mcp-servers-triage-cd54fe

Decided repair-vs-retire for the 4 dead/at-risk MCPs from AUD-0886, verified live
on the hosts, applied host-side config removal/repair, and recorded decisions in SSOT.

## Verdicts

- **notebooklm → REPAIR (repoint to mn01).** The `notebooklm-mcp` container on mn01
  is up 5d and authenticated (`nlm notebook list` works). The dell side was stale:
  `notebooklm-mcp.service` **and** `notebooklm-rest.service` were crash-looping
  (~35.8k restarts each) because their quadlets sit in
  `~/.config/containers/systemd/migrated-off/` — the podman quadlet generator still
  scans subdirectories, so the units kept generating and pulling the missing
  `localhost/notebooklm-*` images. Fix: masked both units on dell; repointed
  `mcp-notebooklm-ssh.sh` (omen), `mcp-notebooklm.sh` (dell), and `~/.local/bin/nlm`
  (both, arg-safe via `printf %q`) to `ssh mn01 podman exec`. Verified end-to-end:
  MCP initialize via the new wrapper on omen returns gemini-notebook-mcp 4.0.3, and
  `nlm notebook list` works from omen+dell. This also repairs the nightly
  `notebooklm-kb-sync.timer` on omen, which was exit-0 while logging ~22 errors/run.
  The notebooklm-rest `:3011` facade was NOT rebuilt on mn01 (no active consumers).

- **workflows → RETIRE.** No unit/image/container on any host, no timer/cron
  invokes it, all 7 YAML under `workflows/` are demo health checks superseded by
  dedicated units + board-api queue/action/pipeline verbs. Removed from
  `mcp_config.json` on omen+dell; deleted the dead `workflows-mcp.service` file on
  omen; SSOT marked retired (ssot.mcp.yml, ssot.mcp-wrappers.yml,
  ssot.health.home.mcp.yml check removed, ssot.automation.yml, registry).

- **docs → RETIRE.** `@arabold/docs-mcp-server` dies at startup on Playwright
  browser auto-install; index stale since 2026-09-12; corpus covered by mddb
  kb-system + ssot-search + rg. Repair cost (chromium on a host being wound down)
  not justified. Removed from `mcp_config.json`; SSOT marked retired. `docs-trade`
  (different server) unaffected.

- **mcp-focus → RETIRE (superseded).** Last `mcp_focus`-sourced session log entry
  2026-09-09; focus files untouched since 10-18; intake now via board-api `/inbox`
  (used today) and `focus-dispatcher-overnight` edits files directly. The identical
  `mcp_focus` tool remains exposed by the operational `mcp-debug` server. Its ssh
  target was also wrong post-OPS-0725 (dell = pull-only mirror — writes stomped by
  mirror sync). Removed from `mcp_config.json`; SSOT marked retired.

## Side fix

`ssot.mcp.yml` gained a `hosts:` section — `validate_per_host_keys` was already
failing on `google-home-lan`'s pre-existing `per_host: mn01` key, so
`scripts/generate-mcp-config.py` could not run at all. Verified the generator now
emits the intended state (18 servers; docs/workflows/mcp-focus skipped;
notebooklm → mn01 ssh wrapper).

## Changed in this worktree (committed, not pushed)

- `docs/ssot/infrastructure/ssot.mcp.yml` — statuses + notes + hosts section
- `docs/ssot/infrastructure/ssot.mcp-wrappers.yml` — retire/repoint entries
- `docs/ssot/infrastructure/ssot.health.home.mcp.yml` — dropped workflows-mcp check
- `docs/ssot/infrastructure/ssot.automation.yml` — workflow_automation retired
- `docs/ssot/infrastructure/ssot.values.yml` — notebooklm.mcp_host=mn01
- `docs/ssot/ssot.registry.infrastructure.yml` — workflows-mcp.service retired
- `scripts/mcp-scripts/mcp-notebooklm-ssh.sh`, `mcp-notebooklm.sh` — new (ssh→mn01)
- `docs/ssot/jobs/infrastructure/2026-10-26-dead-mcp-triage.yml` — decision record

## Changed on hosts (not in git)

- dell: `notebooklm-mcp.service` + `notebooklm-rest.service` stopped, masked,
  reset-failed; `~/.local/bin/nlm` + `mcp-notebooklm.sh` repointed (`.bak` kept);
  `mcp_config.json` stripped of docs/workflows/mcp-focus (`.bak-20261026` kept).
- omen: `nlm` + `mcp-notebooklm-ssh.sh` repointed (`.bak` kept); same
  `mcp_config.json` strip; dead `workflows-mcp.service` unit file deleted.

## How to verify

- `ssh tony-omen '/home/tony/.local/bin/nlm notebook list'` → notebook list JSON
- `ssh tony-dell 'systemctl --user is-enabled notebooklm-mcp.service notebooklm-rest.service'` → `masked`
- `python3 -c 'import json;print(sorted(json.load(open("/home/tony/.config/devin/mcp_config.json"))["mcpServers"]))'` on omen/dell → no docs/workflows/mcp-focus
- `python3 scripts/generate-mcp-config.py --host tony-omen --output /tmp/x.json` → succeeds
