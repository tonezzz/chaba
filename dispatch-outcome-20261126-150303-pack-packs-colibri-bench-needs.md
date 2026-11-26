# dispatch-outcome — pack packs/colibri-bench

Card: colibri-bench-qwen3-6-35b-on-omen-vs-gpt-8ea5a0 (BEN-0814)

## What changed

- `scripts/bench-edu-manage.py` — new `local-colibri` lane:
  `--lanes local-colibri --openai-base http://127.0.0.1:8000/v1 --model qwen3.6-35b`
  (plus `--openai-key`, `--openai-timeout` default 600). Same AgentLane
  surface as hermes/clawbot, so results are directly comparable.
- `scripts/colab/packs/colibri-bench/pack.yml` — realigned to the card spec:
  needs gpu_gb 3 / ram_gb 20 / disk_gb 35, venv true, timeout_s 10800;
  prep clones JustVugg/colibri, runs `start-here.sh --yes --no-start
  --no-browser --model qwen36-35b --backend cuda --dir ~/colibri-models`
  with a cpu fallback, then `coli serve --model <dir> --model-id
  qwen3.6-35b`; run drives the vendored bench at :8000/v1 and writes
  `out/colibri-bench-*.json/.md`; on agent-lane failure a curl
  mini-bench (3 probes, latency + tok/s) still lands artifacts.
- `scripts/colab/packs/colibri-bench/inputs/chaba/` — vendored
  bench-edu-manage.py + bench-edu-corpus.json + ada/{gemini_rest,
  lesson-miner}.py (hash-bound; no chaba clone at run time).
- `docs/ssot/jobs/bench/2026-11-26-colibri-bench-pack.yml` — job record.

## Bugs fixed vs the previous pack

1. Wrong catalog id: `--model qwen3.6-colibri` is the qwen36 family's
   *served* id, not a setup_catalog id — `coli setup` would have failed.
   Correct: `qwen36-35b`.
2. colibri's /v1 404s any request whose `model` != served model-id —
   pack now pins `--model-id qwen3.6-35b` and the bench asks for it.
3. Model was staged inside `$PACK_DIR` — nest-worker pushes the whole
   workdir back to Drive post-run = 23GB upload. Moved to `~/colibri-models`.
4. `cmd | tail || fallback` returns tail's rc under dash — the cpu
   fallback could never fire. POSIX `||` chain now.
5. Agent-lane failure previously lost all evidence (pack `failed`, no
   artifacts pushed). Mini-bench fallback now lands probe data.

## Lane steering decision

Spec allowed "gpu_gb 0 (CPU) or 3"; kept **3** — needs is a capability
floor, so 0 would let every CPU-only fleet host claim the pack and burn
a 3h slot on a ~5 tok/s CPU run (already measured). 3 admits omen's
1650 and Colab T4s only; prep's cpu backend fallback still covers omen
when the 1650 lacks the CUDA toolkit.

## Result / verify

- `yaml.safe_load` + `compile(run)` ok; prep passes `bash -n` and `dash -n`.
- `nest-pack-submit.py scripts/colab/packs/colibri-bench --dry-run` →
  "pack colibri-bench: valid".
- Vendored bench e2e vs a stub /v1 server: lane posts, tool calls run,
  `out` json+md written.
- Committed on `dispatch/20261126-150303-pack-packs-colibri-bench-needs`
  as a757e31a87c. NOT staged to Drive (staging = `nest-pack-submit.py
  scripts/colab/packs/colibri-bench` from a gdrive-rclone host such as
  con01/tony-dell — then omen's nest-worker claims it within its poll
  cycle). Known hold still stands: omen /data was ~38G free; pack needs
  disk_gb 35 on `/`, recheck free space before staging.

lessons:
- colibri `coli setup --model` takes a setup_catalog id (qwen36-35b); `qwen3.6-colibri` is the family's served --model-id default — different namespaces, easy to swap.
- colibri /v1 404s when request `model` != served `--model-id`; pin both sides in pack prep+run.
- nest-worker pushes the entire pack workdir back to Drive after run — never stage multi-GB models under $PACK_DIR; use $HOME.
- pack prep runs under /bin/sh (dash): `cmd | tail || fallback` silently swallows the real rc — log to a file and chain `||` blocks instead.
- vendoring the bench tree under inputs/ beats a chaba clone: the pack is hash-bound and can't drift on master-merge timing.
