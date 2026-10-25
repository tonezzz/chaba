# dispatch-outcome — plan-and-sequence (ada-nest-real-job-plan)

## What was done

Planned and sequenced the 5 ada-nest real jobs into
`docs/ssot/jobs/nest/2026-10-25-ada-nest-real-job-seq.yml`. Every job
declares target_host, resource_gate, artifact, verifier, stop_condition,
plus a `sequence:` block (wave A parallel idc03+omen, wave B serialized,
job4 opportunistic on awake-T4 windows).

## Live state verified at plan time (19:13 UTC, from mn01)

- **omen /data = 174G free** — the card's "38G data free" was the root-fs
  figure (nvme0n1p6, 59G avail) or stale. The colibri-35B >=83G hold gate
  is ALREADY MET; job5 stays last only for RAM contention and is pinned
  to stage the model under /data (root's 59G would not fit).
- idc03 load 9.3 on 4 cores — jev-student :8778 ok, jevos :8017 ready;
  all idc03 CPU jobs declared nice'd + serialized.
- omen ollama already serves nomic-embed-text + bge-m3 — the embed pilot
  needs zero model pulls (~0G new disk, inside the <=5G budget).
- Colab T4 heartbeat ~16min stale (worker colab-…-41509 epoch 18) — not
  confirmed awake; job4 stays heartbeat-gated, queued behind
  gaussian-splat-edu-smoke-v2 / t4-gpu-baseline / t4-llm-direct-bench.
- `packs/img-gen-bench` already ran `done` on con01 CPU (~20 min/img) —
  the T4 arm is a NEW pack dir `img-gen-bench-t4` (cuda backend), since
  claim/done markers are per-dir.

## Sequence produced

1. job1 nest-efficiency report — idc03, first; needs a --max-sessions/
   deadline patch (the 08:16 hang was an unbounded queue-dir scan).
2. job2 JEV decision-arena 27->50 labeled — idc03, after job1;
   choice-heavy expansion, jevos choice-acc is the routing-gate input.
3. job3 omen embed pilot <=5G — parallel with job1; scorers outrank it.
4. job4 T4 Qwen-Image — only inside an already-awake runtime, behind the
   staged queue.
5. job5 omen colibri qwen3.6-35B — gate met; eligible after job3, with a
   pre-flight re-check of /data >=83G + mem >=4G.

## How to verify

- File: `docs/ssot/jobs/nest/2026-10-25-ada-nest-real-job-seq.yml`
  (validates as YAML; all 5 jobs carry the 5 required declarations).
- Board: two comms on card `ada-nest-real-job-plan` (progress + this
  summary, incl. the 38G->174G correction).
