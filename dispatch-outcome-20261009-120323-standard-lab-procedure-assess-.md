# Lab: crush CLI assessment (card lab-crush-cli, runner idc02 → tony-dell)

## Result: adopt-as-alt-lane. crush v0.98.0 left installed at `~/.local/bin/crush` on tony-dell.

## What was done

1. **Install** — crush v0.98.0 (90MB binary) was already present at `~/.local/bin/crush` on tony-dell
   (timestamped 12:06, staged before this session). `go version` → go1.26.0, so `go install` was the
   unused fallback. Verified `crush --version` runs.
2. **Provider** — no OpenRouter key existed at first check; raised a board request per spec.
   `~/.config/secrets/openrouter.env` then appeared (12:06), so the request became moot.
   Wrote `~/.config/crush/crush.json`: `providers.openrouter` (type `openrouter`,
   `api_key: "$OPENROUTER_API_KEY"` — env-expanded, no key in file), models
   large=`qwen/qwen3-coder`, small=`google/gemini-2.5-flash-lite`, plus an `mcp` stanza and
   `permissions.allowed_tools`. Schema verified against `https://charm.land/crush.json`.
3. **Smoke tasks** (scratch `/tmp/crush-lab` on tony-dell, `crush run --cwd`):
   - Task 1 (write fizzbuzz + pytest, run it): **passed in 1m7s** — files created, `python` 127
     self-corrected to `python3`, two `edit` misses recovered via `write`, pytest 4/4 green
     (verified independently).
   - Task 2 (edit existing file): **passed in 1m7s** — surgical `edit` calls both landed,
     argparse `--limit` added, test added, pytest 5/5 green, model self-verified CLI output.
   - Scope: every write stayed under `/tmp/crush-lab`; nothing touched outside.
4. **MCP check** — wrote a minimal read-only stdio MCP (`lab_mcp.py`: `lab_list`/`lab_read` scoped
   to scratch). Config parsed; log shows `MCP client initialized name=lab-ro ... error=null` (25ms),
   and the agent actually invoked `mcp_lab-ro_lab_list` and returned real dir contents.
   Note: MCP tools are main-agent only ("No MCPs allowed" for Task subagents).
5. **Verdict** — crush beats devin-dispatch on: model flexibility (any OpenRouter model, cheap tiers),
   interactive TUI, MCP ecosystem (stdio/sse/http), skills/context files, session resume, zero-infra
   one-shot prompts (`crush run`). Dispatch beats crush on: unattended kanban runs — worktree
   isolation, TASK_RAILS, board comms/requests, merge gates, needs-input flow. Crush has none of
   that; `crush run` is a prompt→output pipe with permission prompts unless `allowed_tools` is set.
   **Recommendation: adopt-as-alt-lane** — keep it for interactive/model-flexible/MCP work and as a
   cheap one-shot lane; dispatch remains the CI lane.

## Friction / notes

- `crush run` has **no `--yolo`** flag (help lists it only for interactive `crush`); unattended runs
  rely on `permissions.allowed_tools` in config.
- `python` is absent on tony-dell (only `python3`) — cost crush one wasted tool call per run.
- qwen3-coder edit misses in run 1 (recovered via rewrite); clean edits in run 2. Model is a dial.
- Forensics: `/tmp/crush-lab/.crush/crush.db` (sqlite `messages.parts`) + `.crush/logs/crush.log`.

## How to verify

- `ssh tony-dell '~/.local/bin/crush --version'` → v0.98.0
- `ssh tony-dell 'cat ~/.config/crush/crush.json'` → providers.openrouter, mcp lab-ro, allowed_tools
- `ssh tony-dell 'cd /tmp/crush-lab && python3 -m pytest -q'` → 5 passed
- Job trail: `docs/ssot/jobs/experiments/2026-10-09-crush-cli-lab-assessment.yml`
