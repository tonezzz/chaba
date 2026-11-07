# board read-projection bench — manual baseline vs replacement

- date: 2026-10-31
- card: ops-manual-command-api-mcp-efficiency-audit (AUD-1033)
- fixture: real cards.json (/tmp/cards.json, 1136 cards)
- reps per lane: 15 (median ms, loopback HTTP vs the real board-api handler)
- token estimate: response chars/4 + 60-char call envelope (mcp-files-bench convention)

| scenario | manual bytes | new bytes | Δbytes | manual calls | new calls | Δtok-est | median ms m→n | evidence equal |
|---|---|---|---|---|---|---|---|---|
| single-card-read | 5,224,998 | 4,216 | 99.92% | 2 | 1 | 99.91% | 169.6→53.9 | yes |
| board-index | 5,224,998 | 219,635 | 95.8% | 2 | 1 | 95.79% | 172.1→51.0 | yes |
| claim-poll | 5,224,998 | 1,767 | 99.97% | 1 | 1 | 99.96% | 173.6→50.1 | yes |
| status-check | 5,224,998 | 66,102 | 98.73% | 2 | 1 | 98.73% | 173.7→48.8 | yes |
| delta-sync | 5,224,998 | 10,909 | 99.79% | 2 | 1 | 99.79% | 159.5→43.8 | yes |

Notes: manual-lane token estimates assume the payload reaches the model context; when agents pre-filter client-side the wire bytes are unchanged but only call count differs. Evidence equality = the replacement returns exactly what the manual reduction produced over the same fixture.
