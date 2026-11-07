# Task: MCP tool-safety matrix

Read `evals/shadow/task/inputs/mcp-config.json` (a frozen snapshot of an
MCP tool surface) and produce
`evals/shadow/task/artifacts/mcp-safety.json` — a matrix classifying every
declared tool for shadow-mode safety.

## Rules

- Read-only; the only file written is the artifact. No commits, no pushes.
- Every server and every tool listed in the input must appear in your output.
- Classify each tool as exactly one of: `read-only`, `write`, `delete`,
  `unknown`.
- Conservative rule: anything you cannot prove read-only is `unknown`,
  and `unknown` is NEVER shadow-safe. A server with
  `declared_mode: "unknown"` does not make its tools read-only.
- Name heuristics are acceptable evidence (get/search/list/collect ->
  read-only; write/set/delete/create/put/execute -> write or delete;
  ambiguous -> unknown) but err toward `unknown`.

## Required JSON fields

- `host`, `collected_at`
- `servers` — `[{name, server_class, tools: [{name, classification}]}]`
- `summary` — `{total_tools, read_only, write, delete, unknown}` (counts)
- `shadow_safe` — list of `server.tool` names allowed under the shadow
  policy in the input
- `read_only` — must be `true`
