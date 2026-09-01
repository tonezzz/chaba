# Branch/Worktree Sprawl Report

- **Generated:** 2026-09-01T17:19:23.828289
- **Host:** tony-dell
- **Base directory:** /home/tony/CascadeProjects
- **Repos scanned:** 3

## Summary

| Repo | Local branches | Remote branches | Worktrees | HEAD |
|------|----------------|-----------------|-----------|------|
| chaba-h3-tony-dell | 3 | 30 | 3 | 355a8624 auto: refresh mcp-savings.json from tony-dell (2026-09-01 17:12:03 +0700) |
| chaba-tony-dell | 3 | 30 | 3 | 65a2f8b0 triage: resolve port-conflicts and mcp-health-snapshot focus items (2026-09-01 16:10:12 +0700) |
| chaba-tony-dell-experiment | 3 | 30 | 3 | 521da2c6 feat: add tony-dell Phase 1 branch/worktree sprawl job and runner (2026-09-01 17:18:25 +0700) |

## Local branches

### chaba-h3-tony-dell

- * chaba.h3                         355a8624 [origin/chaba.h3: ahead 1015, behind 1338] auto: refresh mcp-savings.json from tony-dell
- + experiment/tony-dell-task-runner 521da2c6 (/home/tony/CascadeProjects/chaba-tony-dell-experiment) [origin/experiment/tony-dell-task-runner] feat: add tony-dell Phase 1 branch/worktree sprawl job and runner
- + master                           65a2f8b0 (/home/tony/CascadeProjects/chaba-tony-dell) [origin/master] triage: resolve port-conflicts and mcp-health-snapshot focus items

### chaba-tony-dell

- + chaba.h3                         355a8624 (/home/tony/CascadeProjects/chaba-h3-tony-dell) [origin/chaba.h3: ahead 1015, behind 1338] auto: refresh mcp-savings.json from tony-dell
- + experiment/tony-dell-task-runner 521da2c6 (/home/tony/CascadeProjects/chaba-tony-dell-experiment) [origin/experiment/tony-dell-task-runner] feat: add tony-dell Phase 1 branch/worktree sprawl job and runner
- * master                           65a2f8b0 [origin/master] triage: resolve port-conflicts and mcp-health-snapshot focus items

### chaba-tony-dell-experiment

- + chaba.h3                         355a8624 (/home/tony/CascadeProjects/chaba-h3-tony-dell) [origin/chaba.h3: ahead 1015, behind 1338] auto: refresh mcp-savings.json from tony-dell
- * experiment/tony-dell-task-runner 521da2c6 [origin/experiment/tony-dell-task-runner] feat: add tony-dell Phase 1 branch/worktree sprawl job and runner
- + master                           65a2f8b0 (/home/tony/CascadeProjects/chaba-tony-dell) [origin/master] triage: resolve port-conflicts and mcp-health-snapshot focus items

## Remote branches

### chaba-h3-tony-dell

- origin/HEAD                                     -> origin/master
-   origin/chaba-mcp-experiments                    b6bf45d8 merge: sync chaba-mcp-experiments with master (remove playlived.service)
-   origin/chaba-omen                               241b0a85 feat: add Helm health checks in Compose and Caddy
-   origin/chaba.h3                                 57f05e46 focus(worktrees): sync mcp-kbman with master
-   origin/devin/1787269415-devin-vm-mcp-debug-host 6b085b56 Fix df column swap and lsblk empty-field parsing
-   origin/devin/focus-consolidation-20260820       7da7ea54 Merge branch 'master' into devin/focus-consolidation-20260820; keep yomi-llm-rate-limits active and park Consolidate focus system architecture
-   origin/devin/gemini-live-20260820               14c04ba9 fix: stop slideshow when queue is exhausted
-   origin/devin/tony-dell-rview-gemini             14ba86b1 Merge remote-tracking branch 'origin/master' into devin/tony-dell-rview-gemini
-   origin/devin/tony-dell-rview-gemini-h3          5b5051b0 fix(chaba.h3): support Phusion Passenger Unix socket PORT for Plesk Node.js
-   origin/devin/update-skills-1787238591           ba6088b2 Add rview-smoke testing skill
-   origin/devin/update-skills-1787240597           283a16da Add smoke-test skills for rview and focus systems
-   origin/experiment/gold-thb-usd-causality        a36b523b docs: update dev-system.assessment for clean tree and CI smoke tests
-   origin/experiment/meshtastic-th-node-collector  5d4b82df experiment: make msh/TH collector async and document public broker
-   origin/experiment/tony-dell-task-runner         521da2c6 feat: add tony-dell Phase 1 branch/worktree sprawl job and runner
-   origin/explore/visualization-dotwave            11f45b11 chore: validate and commit pending SSOT, focus-inbox, and dot-wave app
-   origin/feature/esp32                            2c28360a fix(esp32): use capture_response and json::parse_json
-   origin/feature/home-assistant-mcp               0dbe3447 docs: use sensor-reader /health endpoint for health checks
-   origin/ha                                       bcf2c7dc docs: add shared Home Assistant platform SSOT
-   origin/master                                   65a2f8b0 triage: resolve port-conflicts and mcp-health-snapshot focus items
-   origin/mcp-kbman                                78385b7e merge: sync kbman with master
-   origin/michael                                  7d084cd6 chore: back up tony-dell systemd units
-   origin/michael-ha                               073689dd docs: refine michael-ha instance SSOT
-   origin/michael-live                             96899847 test: sunsynk 3-pack with decimal_places 3
-   origin/raceman                                  3b1140c5 merge: sync raceman with master (keep .docs-mcp deleted)
-   origin/research/gold-silver-causality           7811b3df ssot: add Gold/THB/USD research conclusion milestone
-   origin/research/thb-base-settlement             cbd879df app: tuning grid and stress tables for THB tool sweep
-   origin/tony-ha                                  5baf53a2 docs: refine tony-ha instance SSOT
-   origin/topic/tailscale                          47668424 chore: sync yomi-api compose env with live service
-   origin/topic/tony-dell-audit                    9c35f85d ops(mcp-debug): migrate SSE server to tony-dell and update SSOT
-   origin/yomi                                     44f9cfec focus(dev-system): update assessment after deleting topic/tony-dell-audit

### chaba-tony-dell

- origin/HEAD                                     -> origin/master
-   origin/chaba-mcp-experiments                    b6bf45d8 merge: sync chaba-mcp-experiments with master (remove playlived.service)
-   origin/chaba-omen                               241b0a85 feat: add Helm health checks in Compose and Caddy
-   origin/chaba.h3                                 57f05e46 focus(worktrees): sync mcp-kbman with master
-   origin/devin/1787269415-devin-vm-mcp-debug-host 6b085b56 Fix df column swap and lsblk empty-field parsing
-   origin/devin/focus-consolidation-20260820       7da7ea54 Merge branch 'master' into devin/focus-consolidation-20260820; keep yomi-llm-rate-limits active and park Consolidate focus system architecture
-   origin/devin/gemini-live-20260820               14c04ba9 fix: stop slideshow when queue is exhausted
-   origin/devin/tony-dell-rview-gemini             14ba86b1 Merge remote-tracking branch 'origin/master' into devin/tony-dell-rview-gemini
-   origin/devin/tony-dell-rview-gemini-h3          5b5051b0 fix(chaba.h3): support Phusion Passenger Unix socket PORT for Plesk Node.js
-   origin/devin/update-skills-1787238591           ba6088b2 Add rview-smoke testing skill
-   origin/devin/update-skills-1787240597           283a16da Add smoke-test skills for rview and focus systems
-   origin/experiment/gold-thb-usd-causality        a36b523b docs: update dev-system.assessment for clean tree and CI smoke tests
-   origin/experiment/meshtastic-th-node-collector  5d4b82df experiment: make msh/TH collector async and document public broker
-   origin/experiment/tony-dell-task-runner         521da2c6 feat: add tony-dell Phase 1 branch/worktree sprawl job and runner
-   origin/explore/visualization-dotwave            11f45b11 chore: validate and commit pending SSOT, focus-inbox, and dot-wave app
-   origin/feature/esp32                            2c28360a fix(esp32): use capture_response and json::parse_json
-   origin/feature/home-assistant-mcp               0dbe3447 docs: use sensor-reader /health endpoint for health checks
-   origin/ha                                       bcf2c7dc docs: add shared Home Assistant platform SSOT
-   origin/master                                   65a2f8b0 triage: resolve port-conflicts and mcp-health-snapshot focus items
-   origin/mcp-kbman                                78385b7e merge: sync kbman with master
-   origin/michael                                  7d084cd6 chore: back up tony-dell systemd units
-   origin/michael-ha                               073689dd docs: refine michael-ha instance SSOT
-   origin/michael-live                             96899847 test: sunsynk 3-pack with decimal_places 3
-   origin/raceman                                  3b1140c5 merge: sync raceman with master (keep .docs-mcp deleted)
-   origin/research/gold-silver-causality           7811b3df ssot: add Gold/THB/USD research conclusion milestone
-   origin/research/thb-base-settlement             cbd879df app: tuning grid and stress tables for THB tool sweep
-   origin/tony-ha                                  5baf53a2 docs: refine tony-ha instance SSOT
-   origin/topic/tailscale                          47668424 chore: sync yomi-api compose env with live service
-   origin/topic/tony-dell-audit                    9c35f85d ops(mcp-debug): migrate SSE server to tony-dell and update SSOT
-   origin/yomi                                     44f9cfec focus(dev-system): update assessment after deleting topic/tony-dell-audit

### chaba-tony-dell-experiment

- origin/HEAD                                     -> origin/master
-   origin/chaba-mcp-experiments                    b6bf45d8 merge: sync chaba-mcp-experiments with master (remove playlived.service)
-   origin/chaba-omen                               241b0a85 feat: add Helm health checks in Compose and Caddy
-   origin/chaba.h3                                 57f05e46 focus(worktrees): sync mcp-kbman with master
-   origin/devin/1787269415-devin-vm-mcp-debug-host 6b085b56 Fix df column swap and lsblk empty-field parsing
-   origin/devin/focus-consolidation-20260820       7da7ea54 Merge branch 'master' into devin/focus-consolidation-20260820; keep yomi-llm-rate-limits active and park Consolidate focus system architecture
-   origin/devin/gemini-live-20260820               14c04ba9 fix: stop slideshow when queue is exhausted
-   origin/devin/tony-dell-rview-gemini             14ba86b1 Merge remote-tracking branch 'origin/master' into devin/tony-dell-rview-gemini
-   origin/devin/tony-dell-rview-gemini-h3          5b5051b0 fix(chaba.h3): support Phusion Passenger Unix socket PORT for Plesk Node.js
-   origin/devin/update-skills-1787238591           ba6088b2 Add rview-smoke testing skill
-   origin/devin/update-skills-1787240597           283a16da Add smoke-test skills for rview and focus systems
-   origin/experiment/gold-thb-usd-causality        a36b523b docs: update dev-system.assessment for clean tree and CI smoke tests
-   origin/experiment/meshtastic-th-node-collector  5d4b82df experiment: make msh/TH collector async and document public broker
-   origin/experiment/tony-dell-task-runner         521da2c6 feat: add tony-dell Phase 1 branch/worktree sprawl job and runner
-   origin/explore/visualization-dotwave            11f45b11 chore: validate and commit pending SSOT, focus-inbox, and dot-wave app
-   origin/feature/esp32                            2c28360a fix(esp32): use capture_response and json::parse_json
-   origin/feature/home-assistant-mcp               0dbe3447 docs: use sensor-reader /health endpoint for health checks
-   origin/ha                                       bcf2c7dc docs: add shared Home Assistant platform SSOT
-   origin/master                                   65a2f8b0 triage: resolve port-conflicts and mcp-health-snapshot focus items
-   origin/mcp-kbman                                78385b7e merge: sync kbman with master
-   origin/michael                                  7d084cd6 chore: back up tony-dell systemd units
-   origin/michael-ha                               073689dd docs: refine michael-ha instance SSOT
-   origin/michael-live                             96899847 test: sunsynk 3-pack with decimal_places 3
-   origin/raceman                                  3b1140c5 merge: sync raceman with master (keep .docs-mcp deleted)
-   origin/research/gold-silver-causality           7811b3df ssot: add Gold/THB/USD research conclusion milestone
-   origin/research/thb-base-settlement             cbd879df app: tuning grid and stress tables for THB tool sweep
-   origin/tony-ha                                  5baf53a2 docs: refine tony-ha instance SSOT
-   origin/topic/tailscale                          47668424 chore: sync yomi-api compose env with live service
-   origin/topic/tony-dell-audit                    9c35f85d ops(mcp-debug): migrate SSE server to tony-dell and update SSOT
-   origin/yomi                                     44f9cfec focus(dev-system): update assessment after deleting topic/tony-dell-audit

## Worktrees

### chaba-h3-tony-dell

- /home/tony/CascadeProjects/chaba-tony-dell            65a2f8b0 [master]
- /home/tony/CascadeProjects/chaba-h3-tony-dell         355a8624 [chaba.h3]
- /home/tony/CascadeProjects/chaba-tony-dell-experiment 521da2c6 [experiment/tony-dell-task-runner]

### chaba-tony-dell

- /home/tony/CascadeProjects/chaba-tony-dell            65a2f8b0 [master]
- /home/tony/CascadeProjects/chaba-h3-tony-dell         355a8624 [chaba.h3]
- /home/tony/CascadeProjects/chaba-tony-dell-experiment 521da2c6 [experiment/tony-dell-task-runner]

### chaba-tony-dell-experiment

- /home/tony/CascadeProjects/chaba-tony-dell            65a2f8b0 [master]
- /home/tony/CascadeProjects/chaba-h3-tony-dell         355a8624 [chaba.h3]
- /home/tony/CascadeProjects/chaba-tony-dell-experiment 521da2c6 [experiment/tony-dell-task-runner]

