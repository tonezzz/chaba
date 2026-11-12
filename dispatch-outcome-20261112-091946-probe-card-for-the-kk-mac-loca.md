# Dispatch outcome — kk-mac-lane-live-probe (2026-11-12 09:19 +07)

## What happened

The card `kk-mac-lane-live-probe` declares `executor=kk_mac_local`,
`task_class=summary`, `artifact=reports/kk-mac-lane-probe.md`. Prior claims
fell back because the KK-Mac lane was ineligible at claim time
(`heartbeat_stale`, `load_unknown` on 2026-11-11 21:53) and the fallback
lanes then failed for unrelated reasons.

This session re-probed the lane first: `kk_mac_executor.py probe` returned
**eligible** (heartbeat 91s fresh, ollama_ok, disk 112G free, load1m 2.62,
cpu 40C, node not busy). The lane had recovered since the claim-time
decline.

I then ran the real contract inside this dispatch worktree:

    python3 scripts/devnest/kk_mac_executor.py run \
      --card kk-mac-lane-live-probe \
      --task-id 20261112-091946-probe-card-for-the-kk-mac-loca \
      --task-class summary \
      --worktree <this worktree> --taskdir $TASK_DIR \
      --artifact reports/kk-mac-lane-probe.md \
      --model qwen3:8b --prompt-file $TASK_DIR/kk_prompt.txt

## Result

- `verdict: pass`, `artifact_written: true` — the artifact file was
  written by the lane's own `_persist`, not by this session's editor.
- Artifact: `reports/kk-mac-lane-probe.md` (JSON result record; the
  model's markdown response is in `result.response`).
- Executor evidence: `executor=kk_mac_local`, model `qwen3:8b` via ollama
  on KKs-Mac-Studio (ssh `kk-mac` → `127.0.0.1:11434/api/generate`),
  `eval_count=1184`, `eval_duration≈19.6s`.
- Memory guard (MEM-1043): pre/during/post all 61% free — clean.
- Taskdir evidence: `kk_mac_result.json`, `verdict.json`, `kk_mac.log`,
  `kk_prompt.txt`.
- Card comms updated via board-api `/comment` recording that
  **kk_mac_local** (not a fallback lane) produced the artifact.

## Caveat

qwen3:8b's summary drifted to a traffic-lane metaphor (tolls, congestion)
rather than the DevNest executor-lane model. The contract verifier passed
because the card declares no `expect.facts`. Lane mechanics are proven;
for content-strict probes, add `expect.facts` to the card's action.

## DONE-CONDITION check

- card finishes ok → yes (this session exits clean; artifact is in the
  worktree for the merge gate).
- artifact written by the kk-mac lane → yes (`artifact_written=true`,
  written by `kk_mac_executor._persist`).
- card comms record which executor ran → yes (comment posted,
  kk_mac_local, with admission + usage detail).

## How to verify

- `reports/kk-mac-lane-probe.md` → `"executor": "kk_mac_local"`,
  `"verdict": "pass"`, `"artifact_written": true`.
- `$TASK_DIR/kk_mac_result.json` / `verdict.json` — same record +
  per-check results.
- Card comms tail on idc03 board-api — the EXECUTOR RECORD comment.
