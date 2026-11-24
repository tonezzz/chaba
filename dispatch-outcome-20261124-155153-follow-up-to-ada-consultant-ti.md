# dispatch outcome — consultant-brain-confirmation-bench

## What changed

Committed on `dispatch/20261124-155153-follow-up-to-ada-consultant-ti` (7235024169):

- `scripts/bench/card-judgment/corpus.jsonl` + `corpus-v4.jsonl` — observe-006
  (stale-report-regen-lane) relabeled `observe`→`defer` with `audit_note`
  provenance. This is the corrected corpus from the 2026-11-19 audit; the
  audit commit `2ad449c283` lives only on unmerged branch
  `dispatch/20261119-130719-tiered-judgment-instead-of-ada` (merge-sweep lost
  the worktree), so the relabel never reached master. Verified the ported
  files are byte-identical to that commit's versions.
- `scripts/bench/card-judgment/score.py` — ported `--max-tokens` flag
  (default 640 → pass `--max-tokens 2048` for thinking models), same diff
  as the audit commit.
- `docs/ssot/jobs/bench/2026-11-24-consultant-confirmation-bench.yml` —
  job trail: what was ported, the blocker evidence, and the exact resume
  recipe (x3 score.py commands + certification gate + activation pointer).

## Result: BLOCKED on compute — needs-input filed

The confirmation series was **not run**. The card's lane is kk-mac ollama:

- kk-mac is asleep/off tailnet (last seen ~1h; heartbeat stale 6086s;
  `kkmac-admission-shim` on idc03 returns `admission_denied
  heartbeat_stale+load_high`). No remote wake path is documented.
- Fallback tested: tony-omen ollama serves qwen3:8b (same Q4_K_M 5.2GB tag)
  but the host is saturated — 12 cores at load ~55, GPU 96%, constant
  idc03 `/api/embed` flood; a trivial chat request queued >12 min without
  the model loading. Impractical for 94 cases × 3 runs.
- qwen2.5:32b exists only on kk-mac → the optional 32b run is blocked too.

`$TASK_DIR/needs-input.txt` asks Tony to wake kk-mac or approve a degraded
omen run. Card comms posted (progress + blocked status).

## How to verify / resume

- `git show 7235024169 --stat`; `git diff 2ad449c283 HEAD --
  scripts/bench/card-judgment/corpus.jsonl` should be empty apart from
  unrelated drift (audit commit's corpus == corrected corpus).
- Once kk-mac is awake (shim `curl 127.0.0.1:11447/health` →
  `eligible:true`), run the recipe in the job yml: 3× score.py with
  `--entity ada --model qwen3:8b --base-url http://100.108.217.17:11434/v1
  --enforce --briefs briefs.json --temperature 0.3 --max-tokens 2048`.
- Certify only if all 3 PASS **and** no defer-gold→act/correct in any
  confusion matrix; then follow the activation order in
  `docs/ssot/jobs/bench/2026-11-09-consultant-brain-bench.yml` (on the same
  unmerged 2026-11-19 branch — it also needs porting/merging).

lessons:
- The 2026-11-19 consultant-lane work (corpus relabel, score.py flag, bench yml, consultant_worker, litellm alias) is stranded on unmerged branch `dispatch/20261119-130719-tiered-judgment-instead-of-ada` — anything building on it must port or merge that branch first.
- kk-mac has no remote wake; when it sleeps the whole local-LLM lane (shim :11447, litellm `ollama-*-kkmac` aliases) hard-fails with `heartbeat_stale` — check `curl idc03:11447/health` (via ssh, it's loopback) before scheduling kk-mac benches.
- tony-omen ollama can be saturated by a ~1/s `/api/embed` flood from idc03 (all 400ing at 8s) — a model that never appears in `/api/ps` after 10+min means the host is not a viable bench target regardless of free VRAM.
- score.py `--entity ada` only selects the ADA_SYSTEM prompt; `--base-url` is independent, so any OpenAI-compatible ollama endpoint (e.g. omen :11434/v1) can substitute for kk-mac when the weights match.
