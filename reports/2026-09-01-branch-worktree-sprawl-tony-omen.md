# Branch/Worktree Sprawl Report (tony-omen)

- **Generated:** 2026-09-01T19:38:15.467719
- **Host:** tony-omen
- **Base directory:** /home/tony/CascadeProjects
- **Repos scanned:** 1

## Summary

| Repo | Local branches | Remote branches | Worktrees | HEAD |
|------|----------------|-----------------|-----------|------|
| chaba | 19 | 46 | 8 | 19d8da5 feat: add --process-ready bridge to dispatch Ready (Safe) foci to a target host (2026-09-01 17:17:37 +0700) |

## Local branches

### chaba

- + chaba-mcp-experiments            965a9e5 (/home/tony/CascadeProjects/chaba-mcp-experiments) Restore missing MCP server sources from branch history
-   chaba-omen                       241b0a8 [origin/chaba-omen] feat: add Helm health checks in Compose and Caddy
- + chaba.h3                         57f05e4 (/home/tony/CascadeProjects/chaba-h3) [origin/chaba.h3] focus(worktrees): sync mcp-kbman with master
- + experiment/tony-dell-task-runner 18385de (/home/tony/CascadeProjects/chaba-tony-dell-local) [origin/experiment/tony-dell-task-runner] feat: extend branch/worktree inventory to remote hosts and add Phase 1b job
-   explore/visualization-dotwave    11f45b1 [origin/explore/visualization-dotwave] chore: validate and commit pending SSOT, focus-inbox, and dot-wave app
-   feature/home-assistant-mcp       0dbe344 [origin/feature/home-assistant-mcp] docs: use sensor-reader /health endpoint for health checks
-   ha                               bcf2c7d docs: add shared Home Assistant platform SSOT
- * master                           19d8da5 [origin/master: ahead 1, behind 3] feat: add --process-ready bridge to dispatch Ready (Safe) foci to a target host
- + mcp-kbman                        78385b7 (/home/tony/CascadeProjects/chaba-kbman) merge: sync kbman with master
-   michael                          0e36b4a [origin/michael: ahead 30] fix: force 3 decimals in cell voltage markdown using format
- + michael-ha                       1018ea6 (/home/tony/CascadeProjects/chaba-michael) feat: add michael-ha deploy script and SSOT for Tailscale dev workflow
-   michael-live                     9689984 test: sunsynk 3-pack with decimal_places 3
- + raceman                          3b1140c (/home/tony/CascadeProjects/chaba-raceman) [origin/raceman] merge: sync raceman with master (keep .docs-mcp deleted)
-   research/gold-silver-causality   7811b3d [origin/research/gold-silver-causality] ssot: add Gold/THB/USD research conclusion milestone
-   research/thb-base-settlement     ff560e4 [origin/research/thb-base-settlement: ahead 52, behind 51] app: tuning grid and stress tables for THB tool sweep
-   tony-ha                          5baf53a docs: refine tony-ha instance SSOT
-   tony-live                        9bd3fdd [origin/tony-live] feat: add tony-live app on tony-live branch
-   topic/tailscale                  4766842 chore: sync yomi-api compose env with live service
- + yomi                             44f9cfe (/home/tony/CascadeProjects/chaba-yomi) [origin/yomi] focus(dev-system): update assessment after deleting topic/tony-dell-audit

## Remote branches

### chaba

- chaba/HEAD                                      -> chaba/explore/visualization-dotwave
-   chaba/chaba-mcp-experiments                     965a9e5 Restore missing MCP server sources from branch history
-   chaba/chaba-omen                                241b0a8 feat: add Helm health checks in Compose and Caddy
-   chaba/chaba.h3                                  57f05e4 focus(worktrees): sync mcp-kbman with master
-   chaba/explore/visualization-dotwave             2953e64 feat: version mcp-scripts, add duplicate-key validation, and clean ssot.mcp.yml
-   chaba/feature/home-assistant-mcp                0dbe344 docs: use sensor-reader /health endpoint for health checks
-   chaba/ha                                        9a0f8b4 docs: add Home Assistant branch model SSOT
-   chaba/master                                    2953e64 feat: version mcp-scripts, add duplicate-key validation, and clean ssot.mcp.yml
-   chaba/mcp-kbman                                 78385b7 merge: sync kbman with master
-   chaba/michael                                   0e36b4a fix: force 3 decimals in cell voltage markdown using format
-   chaba/michael-live                              0b7800b feat: scaffold michael-live app with modular family layer and SSOT
-   chaba/raceman                                   3b1140c merge: sync raceman with master (keep .docs-mcp deleted)
-   chaba/research/gold-silver-causality            7811b3d ssot: add Gold/THB/USD research conclusion milestone
-   chaba/research/thb-base-settlement              ff560e4 app: tuning grid and stress tables for THB tool sweep
-   chaba/tony-ha                                   2758332 docs: add tony-ha instance SSOT
-   chaba/topic/tailscale                           4766842 chore: sync yomi-api compose env with live service
-   chaba/yomi                                      44f9cfe focus(dev-system): update assessment after deleting topic/tony-dell-audit
-   origin/HEAD                                     -> origin/master
-   origin/chaba-mcp-experiments                    b6bf45d merge: sync chaba-mcp-experiments with master (remove playlived.service)
-   origin/chaba-omen                               241b0a8 feat: add Helm health checks in Compose and Caddy
-   origin/chaba.h3                                 57f05e4 focus(worktrees): sync mcp-kbman with master
-   origin/devin/1787269415-devin-vm-mcp-debug-host 6b085b5 Fix df column swap and lsblk empty-field parsing
-   origin/devin/focus-consolidation-20260820       7da7ea5 Merge branch 'master' into devin/focus-consolidation-20260820; keep yomi-llm-rate-limits active and park Consolidate focus system architecture
-   origin/devin/gemini-live-20260820               14c04ba fix: stop slideshow when queue is exhausted
-   origin/devin/tony-dell-rview-gemini             14ba86b Merge remote-tracking branch 'origin/master' into devin/tony-dell-rview-gemini
-   origin/devin/tony-dell-rview-gemini-h3          5b5051b fix(chaba.h3): support Phusion Passenger Unix socket PORT for Plesk Node.js
-   origin/devin/update-skills-1787238591           ba6088b Add rview-smoke testing skill
-   origin/devin/update-skills-1787240597           283a16d Add smoke-test skills for rview and focus systems
-   origin/experiment/meshtastic-th-node-collector  5d4b82d experiment: make msh/TH collector async and document public broker
-   origin/experiment/tony-dell-task-runner         18385de feat: extend branch/worktree inventory to remote hosts and add Phase 1b job
-   origin/explore/visualization-dotwave            11f45b1 chore: validate and commit pending SSOT, focus-inbox, and dot-wave app
-   origin/feature/esp32                            2c28360 fix(esp32): use capture_response and json::parse_json
-   origin/feature/home-assistant-mcp               0dbe344 docs: use sensor-reader /health endpoint for health checks
-   origin/ha                                       bcf2c7d docs: add shared Home Assistant platform SSOT
-   origin/master                                   e7e3827 Fix variable expansion in google-chrome-launcher.sh and patch-playwright.sh. Generated with [Devin](https://devin.ai). Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
-   origin/mcp-kbman                                78385b7 merge: sync kbman with master
-   origin/michael                                  7d084cd chore: back up tony-dell systemd units
-   origin/michael-ha                               073689d docs: refine michael-ha instance SSOT
-   origin/michael-live                             9689984 test: sunsynk 3-pack with decimal_places 3
-   origin/raceman                                  3b1140c merge: sync raceman with master (keep .docs-mcp deleted)
-   origin/research/gold-silver-causality           7811b3d ssot: add Gold/THB/USD research conclusion milestone
-   origin/research/thb-base-settlement             cbd879d app: tuning grid and stress tables for THB tool sweep
-   origin/tony-ha                                  5baf53a docs: refine tony-ha instance SSOT
-   origin/tony-live                                9bd3fdd feat: add tony-live app on tony-live branch
-   origin/topic/tailscale                          4766842 chore: sync yomi-api compose env with live service
-   origin/yomi                                     44f9cfe focus(dev-system): update assessment after deleting topic/tony-dell-audit

## Worktrees

### chaba

- /home/tony/CascadeProjects/chaba                 19d8da5 [master]
- /home/tony/CascadeProjects/chaba-h3              57f05e4 [chaba.h3]
- /home/tony/CascadeProjects/chaba-kbman           78385b7 [mcp-kbman]
- /home/tony/CascadeProjects/chaba-mcp-experiments 965a9e5 [chaba-mcp-experiments]
- /home/tony/CascadeProjects/chaba-michael         1018ea6 [michael-ha]
- /home/tony/CascadeProjects/chaba-raceman         3b1140c [raceman]
- /home/tony/CascadeProjects/chaba-tony-dell-local 18385de [experiment/tony-dell-task-runner]
- /home/tony/CascadeProjects/chaba-yomi            44f9cfe [yomi]

