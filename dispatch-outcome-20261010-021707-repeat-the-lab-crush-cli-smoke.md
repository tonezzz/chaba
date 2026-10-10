# Dispatch outcome: repeat-the-lab-crush-cli-smoke (crush-provider-bench)

## What was done

Re-ran the lab-crush-cli smoke suite (T1 fizzbuzz+pytest 4/4, T2 surgical edit 5/5,
T3 stdio MCP connect+invoke) per provider lane on tony-dell, using per-lane
scratch dirs `/tmp/crush-bench-mn01/lanes/<lane>` with project-local `.crush.json`
(per docs/kb/crush-multi-agent.md). Each run wall-timed; results verified
independently (pytest re-run, marker-token grep, tool-call audit via crush.db).

## Results (full data: docs/ssot/jobs/bench/2026-10-10-crush-provider-bench.yml)

| Lane | Model | T1 | T2 | T3 | Verdict |
|---|---|---|---|---|---|
| gemini | gemini-3.1-flash-lite | PASS 135s | PASS 89s | PASS 58s | primary lane works, quota-tight |
| or-paid | claude-sonnet-4.6 | PASS 103s | PASS 90s | PASS* 180s | best quality; *T3 via bash JSON-RPC after transient MCP init stall |
| ollama | llama3.2:3b (idc03) | FAIL 248s | FAIL 290s | FAIL 89s | no tool calls — code-as-text |
| ollama | qwen2.5:1.5b (omen) | FAIL 26s | FAIL 10s | FAIL 7s | fast, doesn't execute |
| ollama | qwen3:4b (omen, pulled) | FAIL 122s | FAIL 900s | FAIL 900s | stream stalls / timeouts |
| anthropic | — | — | — | — | no key exists; board request open |

## Findings worth keeping

- `~/.config/secrets/gemini-api-key.env` is a DEAD AQ.* token (401, known from
  ada-scenario-casting-hang). Working GEMINI key is in `ada-pi-pwa.env`.
- crush `type: google` ignores `models.large` and `provider.models` — it always
  picks its catalog default (gemini-3.1-pro-preview-customtools, zero free-tier
  quota on our key). Fix: `-m "gemini/<model>"` flag per `crush run`.
- `openai-compat` → Google `/v1beta/openai/` breaks turn 2: crush drops
  `extra_content.google.thought_signature` → HTTP 400. All gemini-3.x emit
  signatures; use native google provider + `-m`.
- Free-tier gemini quota: 20 req/day on gemini-3-flash-preview (died mid-bench);
  gemini-3.1-flash-lite has headroom and passed everything.
- crush MCP init is timing-flaky — one run continued without MCP tools
  ("initialization still pending after wait budget"); claude-sonnet worked
  around it by driving the MCP server via direct bash JSON-RPC.
- Offline lane is not viable today: idc03 is CPU-only; omen GTX 1650 4G is
  ~60% committed; ≤3B models can't drive the agent loop, qwen3:4b is too slow.
- `qwen3:4b` was pulled to tony-omen ollama during this bench (new model,
  ~2.6GB — left installed).

## Changed files (this worktree)

- `docs/ssot/jobs/bench/2026-10-10-crush-provider-bench.yml` — bench doc
- `docs/ssot/jobs/bench/2026-10-10-crush-provider-bench/` — harness +
  per-lane configs (run_lane.sh, lab_mcp.py, *.crush.json)

## Verify

- `cat docs/ssot/jobs/bench/2026-10-10-crush-provider-bench.yml` — full table
- Transcripts/timing on tony-dell: `/tmp/crush-bench-mn01/lanes/*/task*.{out,ms,rc}`
  (ephemeral /tmp — gone on reboot)
- Board card `crush-provider-bench` has progress + outcome comments and the
  open Anthropic-key request (`anthropic-lane-no-anthropic-api-key-foun-ec782a`).

## Open items

- Anthropic lane awaits Tony's key decision (board request raised). OR-paid
  claude-sonnet-4.6 already covers the model class — direct API adds little.
- Dead gemini key should be replaced (fresh AI Studio key → gemini-api-key.env)
  — same ask as ada-scenario-casting-hang.
