# Navigator agent

Guides operators through deployments, surfacing relevant scripts, URLs, and health checks. Pair this agent
with tooling that can read the `agents/registry.json` and available `scripts/` so it can recommend actions.

Key resources:

- `memory/short_term.jsonl` — rolling transcripts for recent operator chats.
- `knowledge/` — reference docs (site-man README, deploy scripts, node-1 notes).
- `tools/` — future scripted helpers (e.g., start/stop containers, run health checks).

Update `config.json` to point at fresh knowledge or tooling as new workflows are added.
