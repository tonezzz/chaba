# /opencode-command — the narrow OpenCode command publisher

**Status:** implemented (card `ada-opencode-command-publisher-20261108`,
ADA-1224; scope answer `narrow` on request
`which-publisher-scope-should-i-implement-d42d5b`). Code + tests on the
dispatch branch; activation needs the board-api service restart on idc03
after merge — the endpoint is inert until the service reloads
`board-api.py`.

## What it is

One shared, audited door for versioning and deploying the OpenCode-Ada
command files — the files that live in the ada-code workspace on idc02
(`~/.local/share/ada-code/workspace/.opencode/commands/*.md`) and were
previously edited live with no history (the `/ada sweep` native-menu
block was silently lost in the ADA0186 live edit, 2026-11-19).

- Canonical source: `stacks/idc02/ada-code/commands/ada.md` in chaba.
- Deploy target: idc02 workspace `.opencode/commands/ada.md`.
- One door: `POST /opencode-command` on board-api (under WP_LOCK —
  remote ops serialize; card writes never stall).
- Shared by Devin (`scripts/board/opencode-command.py` CLI) and Ada
  (ada-control MCP wrapper — see "Ada side" below; it is a follow-up in
  the ada-voice repo where `ada_mcp.py` is canonical).

## Safety shape

- **No arbitrary paths.** Callers pass `name` + `op`; the
  `opencode_command.COMMANDS` allowlist maps `ada` → fixed repo path,
  deploy host, deploy path, size cap, required markers. Adding a file
  is a code change, not a parameter.
- **No arbitrary shell/git.** Sync uses fixed-argv ssh
  (`cat > tmp && mv -f tmp dst` + `sha256sum`-equivalent reads); the
  commit goes through board-api's `_queue_commit` → commit worker →
  kanban-commit safe-pull+push — the established writer pipeline.
- **Confirm + sha gates.** `publish` and `sync` need `confirm:true`.
  `publish` also needs `expect_sha` = sha256(content) — the reviewed
  bytes are the committed bytes. `sync` accepts `expect_sha` =
  canonical sha as a TOCTOU guard.
- **Validation.** `publish` rejects content that fails structure
  checks: frontmatter, size cap, UTF-8, and `required_markers` —
  currently `"/ada sweep"`, `"Sweep Verdicts"`, `` "`question` tool" ``
  so the sweep native-menu requirement cannot drop silently again.

## Ops

| op | body extras | does |
|---|---|---|
| `preview` | — | canonical vs deployed sha/bytes + unified diff (≤200 lines) |
| `validate` | `content?` (default: canonical) | structure + marker checks → `{valid, errors[]}` |
| `publish` | `content, confirm:true, expect_sha` | write canonical atomically, queue commit → safe-push by writer pipeline |
| `sync` | `confirm:true, expect_sha?` | atomic copy of committed canonical → deploy path (local if host matches, fixed-argv ssh otherwise), sha-verified |
| `verify` | — | `{match, canonical_sha, deployed_sha}` |

Every response is a compact receipt: `{ok, op, name, command:{…fixed
paths…}, message, actor, …}`.

## Devin usage

```bash
scripts/board/opencode-command.py preview
scripts/board/opencode-command.py validate --file new-ada.md
scripts/board/opencode-command.py publish --file new-ada.md --confirm \
    [--expect-sha <sha256>]        # auto-computed from --file if omitted
scripts/board/opencode-command.py sync --confirm [--expect-sha <canonical>]
scripts/board/opencode-command.py verify
```

`--via local` runs the same ops without HTTP (host-side runs / tests —
no commit hook, no board audit trail).

## Ada side (follow-up — ada-voice repo)

`ada_mcp.py` is canonical in `tonezzz/ada-voice` (`opencode/ada_mcp.py`,
edit point tony-dell, ff-synced to `~/CascadeProjects/ada-bridge` on
idc02 by `ada-ocb-bridge-sync.timer` — that is the file ada-code's
opencode.json loads). Add one tool, same two-call confirm pattern as
`ada_card_action`:

```python
@mcp.tool()
def ada_command_publish(operation: str, name: str = "ada",
                        content: str = "", expect_sha: str = "",
                        confirmed: bool = False) -> str:
    """Preview/validate/publish/sync/verify the allowlisted ada-code
    command file via board-api /opencode-command — narrow door, no
    arbitrary paths or shell. publish/sync are mutations: first call
    returns a preview, retry identical with confirmed=true."""
    if operation not in ("preview", "validate", "publish", "sync",
                         "verify"):
        return json.dumps({"ok": False, "operation": "command_publish",
                           "error": "bad op", "mutations": []})
    body = {"op": operation, "name": name, "from": "ada"}
    if content:
        body["content"] = content
    if expect_sha:
        body["expect_sha"] = expect_sha
    if operation in ("publish", "sync"):
        if not confirmed:
            try:
                prev = _post_json("/opencode-command",
                                  {**body, "op": "preview"},
                                  timeout=30)
            except Exception as exc:
                return json.dumps({"ok": False, "error": str(exc),
                                   "mutations": []})
            return json.dumps({"ok": False,
                               "operation": "command_publish",
                               "preview": prev,
                               "warning": "Mutation — retry identical "
                                          "with confirmed=true.",
                               "mutations": []})
        body["confirm"] = True
    try:
        res = _post_json("/opencode-command", body, timeout=90)
        return json.dumps({"ok": True, "operation": "command_publish",
                           "result": res,
                           "mutations": [operation]
                           if operation in ("publish", "sync") else []})
    except Exception as exc:
        return json.dumps({"ok": False, "operation": "command_publish",
                           "error": str(exc), "mutations": []})
```

Once the tool lands, the canonical `ada.md` can gain a
`/ada publish-command` section — add it via this same publisher (it is
the first real use of the door).

## Deploy/activation checklist

1. Merge the dispatch branch (served-checkout promotion path).
2. `systemctl --user restart chaba-board-api` on idc03 — the endpoint
   only exists after the service reloads the module.
3. Verify idc03 → idc02 BatchMode ssh for the board-api user
   (`ssh -o BatchMode=yes idc02 sha256sum <deploy_path>`); sync reports
   UpstreamError honestly if the fleet key path is missing.
4. First run: `preview` shows canonical (menu-restored, 10,790B) vs
   deployed (pre-menu, 10,007B) drift → `sync --confirm` → `verify`
   returns `match:true`.
5. ada-voice follow-up card for the MCP wrapper, then `/ada
   publish-command` section in canonical ada.md.

## Measurement

`docs/reports/opencode-command-bench-2026-11-20.{md,json}` —
`scripts/board/opencode_command_bench.py` runs both lanes on identical
real fixtures. Measured: publish-update 8→5 calls, 11.9KB→2.3KB
ingested bytes (~74% token-est ↓); drift-repair 6→3 calls, ~76% ↓;
evidence equal. The publish request carries the candidate once
(~11KB) — authored output, unchanged from manual.
