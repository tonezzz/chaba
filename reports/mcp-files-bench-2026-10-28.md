# mcp_files_* vs raw shell — 30-task benchmark

- date: 2026-10-28
- card: mcp-structured-files-tool (OPS-0961)
- method: both lanes run locally on one deterministic fixture; tokens ≈ chars/4 + 60-char call envelope; latency = median of reps; recall/fidelity vs independent oracle
- fixture: systemd x30, logs x15, nodered x7, evals-results x6, repo x121, inbox x6 (fifo+symlinks incl 1 escape), wide x200, empty

## Headline

| metric | mcp_files_* | raw shell | delta |
|---|---|---|---|
| prompt tokens (30 tasks) | 1156.8 | 991.2 | -+165.6 (+16.7%) |
| tool tokens (30 tasks) | 18981.5 | 7392.0 | +11589.5 (+156.8%) |
| latency median ms | 41.7 | 3.7 | +38.0 |
| parse success | 1.0 | 1.0 | +0.000 |
| error rate | 0.033 | 0.033 | +0.000 |
| interventions (total) | 0 | 0 | +0 |
| information recall | 1.0 | 0.987 | +0.013 |
| field fidelity | 1.0 | 0.666 | +0.334 |
| tool tokens, format=rows | 12014.5 | 7392.0 | +4622.5 (+62.5%) |

**Total tokens (objects): 20138.3 vs raw 8383.2 → -11755.1 (-140.2%). With format=rows: 13171.3 (+62.5% vs raw tool tokens)**

## Per-task

| id | group | task | tool-tok s/r | lat s/r ms | recall s/r | fidelity s/r |
|---|---|---|---|---|---|---|
| ha01 | host-assessment | List the user's systemd unit dir with kinds and sizes | 1174/494 | 47/6 | 1.00/1.00 | 1.00/0.83 |
| ha02 | host-assessment | Find all .service unit files | 967/420 | 40/4 | 1.00/1.00 | 1.00/0.33 |
| ha03 | host-assessment | 10 largest files under logs with sizes | 414/152 | 38/4 | 1.00/1.00 | 1.00/0.50 |
| ha04 | host-assessment | 5 newest files under logs | 258/64 | 45/7 | 1.00/0.60 | 1.00/0.50 |
| ha05 | host-assessment | Tree of the units dir, 2 levels | 1174/550 | 40/4 | 1.00/1.00 | 1.00/1.00 |
| ha06 | host-assessment | Stat app-03.log (size, mode, mtime) | 132/22 | 47/3 | 1.00/1.00 | 1.00/1.00 |
| ha07 | host-assessment | Find all .timer units | 311/102 | 39/4 | 1.00/1.00 | 1.00/0.33 |
| ha08 | host-assessment | List devnest assessment artifacts with metadata | 336/127 | 45/4 | 1.00/1.00 | 1.00/0.83 |
| ha09 | host-assessment | All .log files in logs dir | 568/213 | 46/6 | 1.00/1.00 | 1.00/0.33 |
| ha10 | host-assessment | List repo top level with kinds | 216/74 | 40/6 | 1.00/1.00 | 1.00/0.83 |
| nr01 | nodered-devnest | Find flows*.json under the Node-RED dir | 168/31 | 37/4 | 1.00/1.00 | 1.00/0.33 |
| nr02 | nodered-devnest | Tree of Node-RED workspace to depth 3 | 398/148 | 48/5 | 1.00/1.00 | 1.00/1.00 |
| nr03 | nodered-devnest | List only devnest-host-*.json artifacts | 340/180 | 41/5 | 1.00/1.00 | 1.00/0.83 |
| nr04 | nodered-devnest | Find all .json files in the Node-RED dir | 238/68 | 36/6 | 1.00/1.00 | 1.00/0.33 |
| nr05 | nodered-devnest | List node_modules contents | 135/36 | 37/6 | 1.00/1.00 | 1.00/0.83 |
| nr06 | nodered-devnest | Which directories exist at repo top level | 186/51 | 42/3 | 1.00/1.00 | 1.00/0.33 |
| g01 | general | Find .py files, at most 2 levels deep | 2063/965 | 40/3 | 1.00/1.00 | 1.00/0.33 |
| g02 | general | Find all .yml anywhere under repo | 2546/1290 | 49/4 | 1.00/1.00 | 1.00/0.33 |
| g03 | general | Tree of repo, 2 levels | 2208/966 | 43/3 | 1.00/1.00 | 1.00/1.00 |
| g04 | general | Only the first level of repo | 216/56 | 37/3 | 1.00/1.00 | 1.00/1.00 |
| g05 | general | Full inventory of inbox incl odd names and kinds | 384/111 | 47/3 | 1.00/1.00 | 1.00/1.00 |
| g06 | general | List first 50 of a 200-entry dir | 1689/162 | 70/5 | 1.00/1.00 | 1.00/0.33 |
| g07 | general | Find test files under repo/tests | 747/315 | 59/3 | 1.00/1.00 | 1.00/0.33 |
| g08 | general | All directories under repo | 314/114 | 42/4 | 1.00/1.00 | 1.00/0.33 |
| g09 | general | List an empty directory | 100/24 | 45/3 | 1.00/1.00 | 1.00/1.00 |
| g10 | general | Stat a path that does not exist (expect clean error) | 38/24 | 39/2 | 1.00/1.00 | 1.00/1.00 |
| g11 | general | List inbox incl symlinks with targets | 314/107 | 40/3 | 1.00/1.00 | 1.00/0.83 |
| g12 | general | Recursive inbox listing incl fifo/other kinds, depth 3 | 384/111 | 37/3 | 1.00/1.00 | 1.00/1.00 |
| g13 | general | Find ssot yamls under apps subdir | 834/390 | 44/4 | 1.00/1.00 | 1.00/0.33 |
| g14 | general | Stat the scripts directory itself | 130/21 | 41/3 | 1.00/1.00 | 1.00/1.00 |

## Notes

- Raw-lane commands are the best-practice shell an agent would plausibly emit (ls -la, find -name/-printf, du, stat) — no strawmen.
- Plain `find -name` returns paths only, so field fidelity collapses even though recall stays 1.0; `ls -la` additionally loses epoch mtime and relative_path on anything non-trivial — in a real session those gaps trigger follow-up calls the harness counts as interventions only when a second command was actually needed.
- Structured latency includes the shipped-agent python startup (~40 ms); over SSH both lanes add the same transport constant, so relative deltas carry over.
- `format:"rows"` is the opt-in compact representation: identical fields positionally with a `fields` header — it closes most of the JSON-key overhead on bulk listings while keeping the schema.
- `mcp_raw` stays gated behind raw_commands.allowed_prefixes; these tools replace its filesystem-listing use, not its existence.
