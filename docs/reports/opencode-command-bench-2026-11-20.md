# opencode-command publisher bench — manual shell vs /opencode-command

- date: 2026-11-20
- card: ada-opencode-command-publisher-20261108 (ADA-1224)
- fixture: canonical `/home/tony/CascadeProjects/dispatch-wt-20261120-132007-canonicalize-the-opencode-ada-/stacks/idc02/ada-code/commands/ada.md` (10,790B, menu-restored) vs deployed `/home/tony/.local/share/ada-code/workspace/.opencode/commands/ada.md` (10,007B, pre-menu live copy) — the real files
- reps: 5 per lane per scenario, identical tmp fixture each rep
- token estimate: chars/4 + 60-char call envelope (mcp-files-bench / board_read_bench convention)

| scenario | manual calls | manual resp B | tool calls | tool resp B | Δbytes | Δcalls | Δtok-est | verified |
|---|---|---|---|---|---|---|---|---|
| publish-update | 8 | 11,904 | 5 | 2,335 (+22,337 req) | 80.38% | 3 | 74.42% | yes |
| drift-repair | 6 | 11,839 | 3 | 2,790 (+191 req) | 76.43% | 3 | 73.55% | yes |

Authoring the new command text (~10,790B) is identical in both lanes and excluded. `+req` is request-side JSON (publish carries the full candidate once — that is authored output, not ingested context).

Reading: the manual lane's dominant cost is `cat deployed` — the agent must ingest the whole command file to hand-diff and hand-verify. The tool's `preview` returns the bounded diff instead; `publish`/`sync`/`verify` receipts are ~0.5KB each and the sha gates make silent drift (the ADA0186 loss) a hard error rather than an unnoticed state.

## Per-call ledgers

### publish-update

| manual cmd | bytes |
|---|---|
| `cat deployed` | 10,007 |
| `sha256sum deployed` | 127 |
| `diff -u deployed candidate` | 1,447 |
| `cp candidate -> canonical` | 0 |
| `git add+commit` | 55 |
| `cp+mv deploy` | 0 |
| `sha256sum verify` | 127 |
| `sha256sum canonical` | 141 |

| tool op | req B | resp B |
|---|---|---|
| `preview` | 32 | 484 |
| `validate` | 11,024 | 379 |
| `publish` | 11,122 | 515 |
| `sync` | 128 | 447 |
| `verify` | 31 | 510 |

### drift-repair

| manual cmd | bytes |
|---|---|
| `cat deployed` | 10,007 |
| `sha256sum deployed` | 125 |
| `diff -u deployed candidate` | 1,443 |
| `cp+mv deploy` | 0 |
| `sha256sum verify` | 125 |
| `sha256sum canonical` | 139 |

| tool op | req B | resp B |
|---|---|---|
| `preview` | 32 | 1,837 |
| `sync` | 128 | 445 |
| `verify` | 31 | 508 |

