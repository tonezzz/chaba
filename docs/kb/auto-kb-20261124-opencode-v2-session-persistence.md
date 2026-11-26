---
category: operations
status: verified
created: 2026-11-24
source: auto-kb
---

# Standalone OpenCode v2 session persistence and resume

## What it is

Standalone OpenCode v2 (the CLI used by the ada-ocb dispatch lane) persists
sessions in `~/.local/share/opencode/opencode.db`, in the `session_v2` table.
This is a different table from `credential` (which holds `opencode auth`
credentials, e.g. the `claude-agent` external credential described in
`openchamber-claude-agent-provider.md`). Do not infer session state from the
credential table.

A persisted session is resumable via `opencode --session <session-id>`, or
through the prompt API carrying the same session id. A resumed turn needs the
provider key in the environment (`LITELLM_KEY` / the lane's key variable) —
without it the provider cannot serve the follow-up even though the session
record still exists.

## Verified how

Read-only spike on tony-omen while scoping ADA-0024 (2026-11-24):

- `session_v2` rows exist and survive process exit in
  `~/.local/share/opencode/opencode.db`.
- A session id captured from a completed run resolves to a resumable session
  (verified by querying the table and matching the id the runner reported).
- Resume requires the LiteLLM key to be present; the session record alone is
  not sufficient to make a new turn.

No board writes, provider calls, or service restarts were part of the spike.

## Why it matters for job lifecycle

A runner can capture the opencode `sessionID` in a job envelope and reuse it
for a needs-input → answer follow-up, so the answer resumes the *same*
context rather than opening a fresh session. This is the mechanism behind
ADA-0024 full-parity (needs-input detection, `job/<id>` MDDB ledger, answer
resume). Without it, a voice answer would re-derive context from scratch.

## Scope caveat

This applies to the **standalone** opencode store. The containerised Jack
worker uses a disposable home at `~/.local/share/jack-ide/opencode-home`
(see `jack-opencode-provider-and-ada-config.md`) — do not conflate the two
when tracing a session id or debugging provider drift.

## Refresh / verification recipe

```bash
# read-only: confirm a session id is persisted
sqlite3 ~/.local/share/opencode/opencode.db \
  "select id, title from session_v2 order by rowid desc limit 5;"

# resume the same context (needs the provider key)
LITELLM_KEY=... opencode --session <session-id>
```

## Related

- ADA-0024 (`ada-ocb-dispatch-parity`) — job-lifecycle parity using this path
- `docs/kb/openchamber-claude-agent-provider.md` — `credential` table (auth, not sessions)
- `docs/kb/jack-opencode-provider-and-ada-config.md` — containerised worker home
