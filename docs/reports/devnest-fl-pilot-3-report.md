# DevNest Pilot 3 Report: Lane and Pilot Status

## Lane Status

| Lane ID | Status |
| :--- | :--- |
| deterministic | live |
| codemod | live |
| jev-routing | live (keyword classifier); jevos fallback live; real Jev API needs key |
| local-gpu-packs | live |
| free-opencode | gated — supervised pilot only; OPS-0846 proven 2026-10-26 (Dell closeout probe landed dispatch worktree + branch + flash-lite + push + baseline-aware gate + auto-merge). OPENCODE_LANES=1 per supervised push-capable runner; pilot cards devnest-fl-pilot-* (job doc docs/ssot/jobs/devnest/2026-10-26-free-lane-savings-pilot.yml) |
| paid_frontier | live |
| devin | live (the baseline every cheaper lane buys down) |

*(Note: free_lane executor used for this pilot)*

## Pilot Status

- **devnest-fl-pilot-doc**: backlog
- **devnest-fl-pilot-code**: backlog
- **devnest-fl-pilot-report**: backlog
