# Dispatch outcome — kk-mac-live-memory-guard (2026-11-24)

## What changed

The card's monitor existed on master but was **detection-only** — the
2026-11-23 lane soak proved it too late (`memory_pressure_abort` verdicts
at 13–14% free with the model still resident). This session added the
missing active-stop and conditional-unload layers; commits `e6481199a7a`
(code+tests) and `d5a513f10e4` (jobs trail) on
`dispatch/20261124-210151-before-another-kk-mac-local-in` (not pushed).

- `scripts/devnest/kk_mac_llm.py` — new `generate_guarded()`: streamed
  `/api/generate` (local urllib for `--host local`, remote `ssh`+curl
  `Popen` otherwise) that polls memory **in-band** every ~1s local /
  ~2s remote — the queue timeout is the poll tick, so Ollama's silent
  model-load window is covered. A <50% free, `kern.memorystatus_level`
  critical, or 3-consecutive-unmeasurable breach closes the HTTP
  response / kills ssh → Ollama drops the generation. After the call,
  `keep_alive=0` unload fires **only** when `/api/ps` proved the model
  absent beforehand — owner-resident or unknown-residency models are
  never touched. `run_task` defaults to this path
  (`memory_guard=False` keeps raw `call_remote` for the bench harness).
- `scripts/devnest/kk_mac_memory.py` — `sample()` now also returns
  `memstatus_pct` (combined probe, one round-trip); `evaluate()` emits
  `memory_pressure_critical` on it in all phases; new
  `resident_models()`/`unload_model()`/`_ollama_request()` for both
  transports.
- `scripts/devnest/kk_mac_executor.py` — persists `memory.guard`
  evidence (resident_before, loaded_by_task, min_free_pct,
  abort_reason, unloaded) into `kk_mac_result.json` + artifact; guard
  abort reasons surface in fallback `reasons`.
- Tests: new `tests/devnest/test_kk_mac_guarded.py` (threshold crossing
  mid-stream, silent-load abort, critical-pressure abort, unmeasurable
  streak, unload-only-task-loaded, owner-resident/unknown-residency
  preservation, run_task wiring) + memstatus cases in
  `test_kk_mac_memory.py` + executor evidence tests. **382 devnest +
  146 board tests green.**

## Result / verification status

- Spec items: monitor covers load+generation ✅, 60% pre-load floor ✅
  (executor + guard + worker gate, fail-closed), stop <50%/pressure ✅
  (active abort now, not just verdict), conditional unload ✅,
  pre/during/post snapshots ✅ (`memory.pre/during/post/guard`),
  threshold tests ✅, `KK_MAC_LANES=0` verified still default-off ✅.
- Live probes while kk-mac was awake: ssh `memory_pressure -Q`,
  `sysctl kern.memorystatus_level`, `/api/ps` all worked; free% swung
  75%→13–16% with owner-resident `qwen3:30b-a3b` (20.3 GB) — exactly the
  scenario the guard exists for. kk-mac slept mid-session (ssh timeout);
  fail-closed verified live (`memory_sample_failed` → pre-load abort).
- **Still owed:** one end-to-end live run on an awake kk-mac with >60%
  free to confirm `memory.guard` evidence lands in a real
  `kk_mac_result.json`. Until then KK_MAC_LANES stays 0 (already is).

## How to verify

```
python3 -m pytest tests/devnest/test_kk_mac_guarded.py \
    tests/devnest/test_kk_mac_memory.py \
    tests/devnest/test_kk_mac_llm.py \
    tests/devnest/test_kk_mac_executor.py -q
# live (needs kk-mac awake):
python3 -c "import sys; sys.path.insert(0,'scripts/devnest'); \
  import kk_mac_memory as km, json; \
  print(json.dumps(km.sample('kk-mac'), default=str))"
```

Trail: `docs/ssot/jobs/devnest/2026-11-24-kk-mac-memory-guard-active-stop.yml`.
Card comms posted. Branch not pushed per dispatch rules.

lessons:
- kk-mac sleeps mid-session (tailscale "last seen" minutes) — live verification needs an awake window; fail-closed paths are verifiable even while it's down.
- urllib streaming + queue-timeout polling covers Ollama's silent model-load window; abort = resp.close() locally, proc.kill() over ssh.
- Never set keep_alive on the generate request itself — it would extend an owner-resident model's residency; unload only via /api/ps-proven loaded_by_task + explicit keep_alive=0.
- kern.memorystatus_level tracks free% ~1:1 on this Mac and is the cheap "or on pressure" signal — fold it into the same ssh round-trip as memory_pressure -Q.
