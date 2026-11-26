# Dispatch outcome — tony-ha cold standby config sync + promote runbook

Card: `tony-ha-cold-standby-config-sync-promote-d12293` (HOM-0855)
Branch: `dispatch/20261124-162119-goal-is-to-create-a-cold-stand` — commit `326da61348` (5 files, +692). Not pushed, not deployed — done-condition was a committed runbook.

## What changed

- **`docs/runbooks/tony-ha-cold-standby.md`** (new, status: `partial`) — the runbook. Verified-topology table, standby-host choice matrix, Part 1 periodic sync install (pull model, exact systemd user units, ssot.jobs.yml + ssot.audit.hosts.yml declaration blocks), Part 2 promote procedure (gate check → timer off → final sync → image digest pin → quadlet install → tailscale serve → consumer repoints → surface verification), rollback/fail-back with the never-two-live-tony-ha split-brain rule, post-promotion SSOT bookkeeping, and explicit out-of-scope notes (ada-ha/michael-ha/kk-ha/go2rtc).
- **`scripts/home-assistant/ha-standby-sync.sh`** (new, executable) — the sync the runbook installs. Runs on the standby, pulls `tony-omen:/home/tony/.config/home-assistant/` via rsync `--delete` into the same canonical path (zero-copy promote). Excludes live `home-assistant_v2.db*`, logs, `deps/`, `tts/`, pycache. `--db` takes a consistent SQLite online-backup snapshot executed on the source over ssh. Guards: refuses on the source host, while a tony-ha/ada-ha unit/container is active locally, and into a non-empty unmarked dest without `--force`. Writes `~/.local/share/ha-standby-sync/last-sync.txt` manifest incl. image ref+id+repo digest.
- **`docs/ssot/ssot.runbooks.yml`** — tier-1 registry entry `tony-ha-cold-standby`.
- **`docs/ssot/infrastructure/ssot.home-assistant.instances.yml`** — `cold_standby:` block on the tony-ha entry (documented-not-armed, candidates, pending prod-placement decision).
- **`docs/ssot/jobs/home-assistant/2026-11-24-tony-ha-cold-standby-runbook.yml`** (new) — decision trail: sync direction, mirror target, DB policy, host recommendation, image pinning rationale, scope boundary, found drift, follow-ups.

## Key findings baked into the runbook

- The fleet already decided the shape: ssot.jobs.yml notes `ha-config-backup` is "host-bound until moved to an idc02 remote pull" — the runbook implements that pull on whichever standby host is chosen.
- **Image pinning is the trap**: the quadlet uses floating `:stable` but `patches/*` bind-mounts are HA-version-pinned (frontend JS filenames like `52451.*`). Promote must pin `Image=` by digest; the sync manifest now records ref+id+digest every run so a promote never depends on reaching omen.
- **mn01 is the recommended standby** (verified on home LAN 2026-10-26, reaches LAN devices; already runs `ada-standby-sync.timer`); idc02 is the documented degraded no-LAN alternative. Final pick pending card `tony-ha-prod-placement-26f033`.
- Secrets need no extra step — lane secrets live host-independently on idc03; `secrets.yaml`/`household.yml` ride inside the config tree.
- Consumer repoint list is enumerated: idc02 tailnet-front `:8123` + public edge `tony-ha.surf-thailand.com`, `stacks/web/Caddyfile` `/apps/ha/tony-ha*` redirect, idc03 `ada-ha-tony` `HOME_ASSISTANT_URL`, ha_mcp_tools `:9584` endpoint, live dashboards, go2rtc/ha-live host-coupled refs.
- **Found drift (not fixed, recorded in job doc):** `ssot.home-assistant.tony.yml` still claims `host: tony_dell` — predates the 10-19/20 evacuation; instances.yml is correct.

## How to verify

- `bash -n scripts/home-assistant/ha-standby-sync.sh` and `--dry-run` print the exact rsync command.
- `python3 -c "import yaml; yaml.safe_load(...)"` on the three touched/added YAML files — all parse; pre-commit SSOT validation + optimize gate passed on commit.
- Runbook registry: `docs/ssot/ssot.runbooks.yml` → `tony-ha-cold-standby`.
- Remaining live verification (documented as `status: partial`): install Part 1 on the chosen standby (~15 min), then one promote drill.

lessons:
- The tony-ha quadlet's floating `:stable` tag is a trap — `patches/*` bind-mounts are HA-version-pinned, so any HA move must pin `Image=` by repo digest; capture it in the sync manifest because omen may be unreachable at promote time.
- Cold-standby sync belongs on the standby host (pull over ssh), not on omen (push) — the flaky host shouldn't hold the sync driver; an outage then just means "nothing new to pull".
- `~/.config/home-assistant` on a standby host IS the tony-ha config path (ada-ha/michael-dev/kk-ha each use distinct dirs) — mirroring to the canonical path makes promotion a service-start, not a copy.
- rsync `--delete` will eat marker/manifest files inside the mirrored tree — keep sync state in `~/.local/share/ha-standby-sync/` outside it.
- `docs/ssot/infrastructure/ssot.home-assistant.tony.yml` is stale (still says host tony_dell post-evacuation) — instances.yml is the live truth; flagged in the job doc for a hygiene pass.
