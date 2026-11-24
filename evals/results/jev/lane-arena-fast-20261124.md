# lane-arena — matched held-out decision benchmark

corpus v2, 50 cases, 2026-11-24T19:23:57+0700

| arm | lane | acc | n | confirm | tool | pipe | stag | p50 ms | err |
|---|---|---|---|---|---|---|---|---|---|
| omen-8780 | omen | 0.48 | 50 | 0.676 | 0.062 | 0.676 | 0.676 | 118.0 | 0 |
| kkmac-qwen38b | kk_mac_local | 0.8 | 50 | 0.706 | 1.0 | 0.706 | 0.706 | 21677.5 | 0 |
| oc-free-flashlite | openrouter | SKIP | — | — | — | — | — | — | ping failed: HTTPError: HTTP Error 403: Forbidden |
| or-free-nemotron | openrouter | SKIP | — | — | — | — | — | — | ping failed: HTTPError: HTTP Error 429: Too Many Requests |
| or-paid-deepseek | openrouter | 0.86 | 50 | 0.794 | 1.0 | 0.794 | 0.794 | 1150.0 | 0 |

## per-family accuracy

| family | omen-8780 | kkmac-qwen38b | or-paid-deepseek |
|---|---|---|---|
| confirm | 12/12=1.0 | 10/12=0.83 | 9/12=0.75 |
| pipe | 6/10=0.6 | 4/10=0.4 | 6/10=0.6 |
| stag | 5/12=0.42 | 10/12=0.83 | 12/12=1.0 |
| tool | 1/16=0.06 | 16/16=1.0 | 16/16=1.0 |

noul ECE / choice ECE and per-case records live in the JSON artifact.
