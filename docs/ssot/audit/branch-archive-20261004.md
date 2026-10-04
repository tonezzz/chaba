# Branch archive manifest — 2026-10-04

Disposition from `worktree-sprawl` board decision (Tony: tag + archive the rest
after top-5 review). Every branch below is preserved as tag `archive/<name>`
pointing at the listed tip commit; remote branches deleted 2026-10-04.

## Top-5 review verdicts

| branch | tip | verdict |
|---|---|---|
| live/tony-dell-snapshot-20260928 | d92907d6 | Already salvaged via e27c9075 (VMS noVNC, cast-cam, michael-dev quadlet). Archive. |
| test/ultralytics-yolo-ha | 6d20a16d | YOLO work landed (yolo-api-proxy, cam-wall yolo layer). Archive. |
| feature/ai-hub-extension | fb58e4d8 | Sep-17 fixes verified present on master. Archive. |
| rk900-dial | f9cdbade | Wind-dial work superseded by mn-weather lineage (dev_rk900→dev_ rename). Archive. |
| feat/tpl-design | ba8c1d39 | Salvaged promote-michael.sh + promote-tony.sh → 6c963fc0. Archive. |

## Archived branches (all tagged archive/<name>)

- bedroom-remote-registry — 4dd7e534 — 2026-09-15 — esphome build-output ignore
- chaba.h3 — dcc114de — 2026-09-03 — auto mcp-savings refresh
- devin/1787269415-devin-vm-mcp-debug-host — 6b085b56 — 2026-08-21 — df/lsblk parse fix
- devin/focus-consolidation-20260820 — 7da7ea54 — 2026-08-20 — focus merge checkpoint
- devin/gemini-live-20260820 — 14c04ba9 — 2026-08-21 — slideshow queue fix
- devin/tony-dell-rview-gemini — 14ba86b1 — 2026-08-22 — master merge checkpoint
- devin/tony-dell-rview-gemini-h3 — 5b5051b0 — 2026-08-22 — Passenger socket PORT fix
- devin/update-skills-1787238591 — ba6088b2 — 2026-08-20 — rview-smoke skill
- devin/update-skills-1787240597 — 283a16da — 2026-08-20 — rview+focus smoke-test skills
- experiment/meshtastic-th-node-collector — 5d4b82df — 2026-08-26 — async msh/TH collector
- experiment/tony-dell-task-runner — a718a794 — 2026-09-04 — ARP inventory subtasks
- feat/tpl-design — ba8c1d39 — 2026-09-09 — promote scripts (salvaged)
- feature/ai-hub-extension — fb58e4d8 — 2026-09-17 — ai-hub relay fixes (on master)
- feature/esp32 — 2c28360a — 2026-08-25 — esp32 json parse fix
- ha — f6a78512 — 2026-09-02 — snapshot sensor scoping fix
- live/tony-dell-snapshot-20260928 — d92907d6 — 2026-09-28 — live snapshot (salvaged)
- research/thb-base-settlement — cbd879df — 2026-08-27 — THB tuning grid
- rk900-dial — f9cdbade — 2026-09-15 — michael-live removal (superseded)
- test/ultralytics-yolo-ha — 6d20a16d — 2026-09-24 — cast-cam kill switch
- topic/tailscale — 47668424 — 2026-08-23 — yomi-api compose env sync
- yomi — 42410f76 — 2026-09-02 — ha/tony-ha/michael merge checkpoint

All deltas were verified against master by file-content comparison; apparent
branch-vs-master diffs were inflated by the master history rewrite and do not
represent unmerged work beyond the salvage noted above.
