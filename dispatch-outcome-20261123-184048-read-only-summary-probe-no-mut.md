# Dispatch outcome — kk-mac-live-jev-probe3 (read-only summary probe)

## What was done

Ran the card's supervised read-only summary probe through the merged
`kk_mac_local` executor contract (`scripts/devnest/kk_mac_executor.py run`)
on tony-dell — the same invocation runner-agent uses
(`--card --task-id --task-class --worktree --taskdir --artifact
--prompt-file --expect-file`). No mutation, no shell on the node beyond
the contract's own read-only probes, no credentials, no publish.

## Result

- **verdict: pass** — admission eligible (heartbeat 114s fresh,
  ollama_ok, disk 52G, load 2.11, node not busy), memory guard clean
  (pre/during/post = 77% free), verifier checks all true
  (`response_nonempty`, `response_bounded`).
- **Model:** qwen3:8b via ssh → kk-mac Ollama `/api/generate`
  (eval_count=38, eval 0.63s, load 4.3s).
- **Response:** "KK-Mac qwen3:8b is in a local bounded read-only state.
  Heartbeat and Ollama health are normal. No mutations detected."

## Artifacts (verified present)

- `evals/kk-mac-lane/out/kk-mac-live-jev-probe3.json` — full result
  record in this worktree (the card's declared `action.artifact`;
  path is gitignored by design — `evals/*/out/`).
- `$TASK_DIR/kk_mac_result.json` + `$TASK_DIR/verdict.json`
  (verdict=pass, checks, reasons=[]) — durable evidence the close-out
  gate reads.
- `$TASK_DIR/kk_mac.log` — raw executor stdout.

## Prior-failure fix

Previous attempts died in <1s with no exit record (opencode free_lane
spawn produced no commits) or, on 2026-10-30, the SSH transport timed
out. This run invoked the executor contract directly in-session: first
attempt hit the MEM-1043 memory guard — qwen2.5:32b (the contract's
post-2026-11-13 default) loaded on the 36 GB Mac and drove free memory
to 11% (<50% abort floor). Retried with `qwen3:8b` — the model the card
prompt declares and runner-agent's `KK_MAC_MODEL` default — which
passed cleanly.

## How to verify

```
python3 -c "import json; d=json.load(open('evals/kk-mac-lane/out/kk-mac-live-jev-probe3.json')); print(d['verdict'], d['model'])"
cat $TASK_DIR/verdict.json
```

lessons:
- kk_mac executor DEFAULT_MODEL is now qwen2.5:32b, but on the 36 GB KK-Mac a 32b load trips the MEM-1043 guard (free 82%→11%); pass --model qwen3:8b for summary-class tasks unless the card pins otherwise.
- KK-Mac free memory oscillates (80%↔30%) as external consumers load/unload models — a first-attempt memory_pressure_abort is retryable once the resident model unloads (~Ollama keep_alive, watch free_pct return >60%).
- Prior "no exit record" failures were the lane never running the contract at all; invoking kk_mac_executor.py run directly in-session with runner-agent's arg pattern produces a clean verdict + artifact.
- evals/*/out/ is gitignored — the kk_mac artifact is durable via the worktree file + taskdir copies, not a commit.
