# board read-projection bench — manual baseline vs replacement

- date: 2026-10-31
- card: ops-manual-command-api-mcp-efficiency-audit (AUD-1033)
- fixture: synthetic seeded=1033 — live distribution (n=1136)
- reps per lane: 15 (median ms, loopback HTTP vs the real board-api handler)
- token estimate: response chars/4 + 60-char call envelope (mcp-files-bench convention)

| scenario | manual bytes | new bytes | Δbytes | manual calls | new calls | Δtok-est | median ms m→n | evidence equal |
|---|---|---|---|---|---|---|---|---|
| single-card-read | 3,476,940 | 3,432 | 99.9% | 2 | 1 | 99.89% | 55.4→24.6 | yes |
| board-index | 3,476,940 | 233,309 | 93.29% | 2 | 1 | 93.28% | 49.8→24.8 | yes |
| claim-poll | 3,476,940 | 41,480 | 98.81% | 1 | 1 | 98.8% | 53.4→24.0 | yes |
| status-check | 3,476,940 | 53,461 | 98.46% | 2 | 1 | 98.46% | 54.0→25.8 | yes |
| delta-sync | 3,476,940 | 8,030 | 99.77% | 2 | 1 | 99.76% | 53.3→24.0 | yes |

Notes: manual-lane token estimates assume the payload reaches the model context; when agents pre-filter client-side the wire bytes are unchanged but only call count differs. Evidence equality = the replacement returns exactly what the manual reduction produced over the same fixture.
