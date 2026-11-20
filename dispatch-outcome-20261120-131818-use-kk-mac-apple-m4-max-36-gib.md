# dispatch outcome — kk-mac-local-llm-lane spec pass (2026-11-20)

## What changed

- **`scripts/devnest/kk_mac_admission.py`** — new `quiet_hours_active()`
  helper: do-not-run window `HH:MM-HH:MM` in kk-mac local time (ICT +7,
  same convention as kanban-dispatch), wraps midnight, returns None on
  malformed input so callers can fail closed.
- **`scripts/devnest/kk_mac_lane_worker.py`** — `gate()` now enforces
  `DEVNEST_KK_MAC_QUIET_HOURS` (opt-in env; unset = unchanged) before
  any probe; malformed configured window denies with
  `quiet_hours_malformed`.
- **Tests** — +7 in `tests/devnest/test_kk_mac_admission.py` /
  `test_kk_mac_lane_worker.py`. 35/35 in both files pass.
- **`docs/reports/kk-mac-llm-bench-2026-11-20.md`** — full report:
  runtime check, bench table, memory-guard evidence, personal-file
  audit, gates inventory, one-shot rollback runbook, Flash Lite/Devin
  comparison.
- **`docs/ssot/jobs/devnest/2026-11-20-kk-mac-llm-lane-bench.yml`** —
  job record.
- **`docs/kb/kkmac-ollama-lane.md`** — model-sizing evidence,
  quiet-hours knob, rollback procedure.
- **`docs/ssot/infrastructure/ssot.devnest-lanes.yml`** — kk_mac_local
  entry records the guard verification, quiet-hours gate, and the
  20B+ sizing verdict.
- **`evals/kk-mac-lane/bench-20261120/`** — prompts, expect blocks,
  `run-bench.sh`, six `*.result.json` executor-contract records.

## Result

Spec items, in order:

1. **Runtime** — Ollama Metal **0.40.8** already installed/healthy on
   kk-mac (login-bound, loopback `:11434`); no install needed. Cached:
   qwen3:8b, qwen2.5vl:7b, llama3.2:3b, gpt-oss:20b, qwen3:30b-a3b,
   qwen2.5:32b, bge-m3. **No 14B pulled** — spec's middle rung is empty
   (needs pull approval; did not download).
2. **Read-only smoke + size bench** — ran through the production
   executor contract on the trusted tony-dell→`kkkakk@kk-mac` hop
   (idc02 has no direct grant). Admission was eligible at run time
   (heartbeat 119s, load 3.37, disk 55GB, AC, 40C, 82-84% mem free):
   - `qwen3:8b`: **2/2 pass** — 60.3 tok/s warm, 0.81s load, verified
     summary + JSON extract (route=deterministic). Lane default
     confirmed.
   - `gpt-oss:20b`: **fallback both calls** — its ~14GB load alone
     pushed free memory to 48-49%, tripping the 50% abort floor
     (and 60% pre-load floor on retry).
   - `qwen3:30b-a3b`: cold **pass** (8.6s load, **92.4 tok/s**, MoE
     ~3B active) then warm **fallback** — overlap drove free to 20%.
     Also ignores `think:false` (CoT preamble, ~5x token burn).
   - **Verdict: 20B+ footprints are not lane-safe on 36GiB while owner
     apps are resident** — exactly the resource evidence the spec asked
     for before loading 20B+.
   - **MEM-1043 memory guard verified end-to-end**: pre-load block,
     two during-run abort catches, all fail-closed, node recovered to
     74% free with `/api/ps` empty. This closes the 2026-11-06
     "no rerun until guard verified" hold.
   - Metrics: load/eval tokens/tok/s recorded per call; temp 40C
     throughout; **energy n/a** (powermetrics needs root on macOS).
3. **No personal-file access — verified**: on-host surface was loopback
   curl + read-only system probes only (`memory_pressure`, `vm_stat`,
   `sysctl`, `smctemp`, `df`, `pmset`, `ps`, `launchctl list`); the
   executor is a fixed ssh+curl contract with no shell/FS bridge;
   nothing written on kk-mac.
4. **Routing bound** — unchanged: summary / operator_brief /
   structured_extract / safe_route only (credentials, destructive,
   multi-step and code work stay off the lane by class bound).
   Codemod/code classes still need a verifier contract — noted in the
   report as future work, not silently widened.
5. **Gates before launchd persistence** — load/heartbeat/temp/busy
   gates + memory guard live; **quiet-hours gate shipped this session**
   (opt-in env on the worker; suggested `23:00-07:00` at next
   owner-approved plist update); **one-shot rollback documented**
   (drain file, `launchctl bootout` + plist rm, shim `.deny`, tunnel
   stop) — all decline paths fail closed to the next lane.
6. **Comparison vs Flash Lite + Devin** — in the report: kk-mac local
   already beats Flash Lite on the card-judgment corpus (qwen2.5:32b
   0.857, llama3.2:3b 0.827 vs flash-lite ~0.49-0.52) at **$0** and
   comparable bounded-call latency; cost is availability gating,
   absorbed by same-claim fallback. Devin remains the fallback/heavy
   lane — kk-mac buys it down only for the four bounded classes.

## How to verify

```bash
python3 -m pytest tests/devnest/test_kk_mac_admission.py \
  tests/devnest/test_kk_mac_lane_worker.py -x -q   # 35 pass
cat docs/reports/kk-mac-llm-bench-2026-11-20.md
ls evals/kk-mac-lane/bench-20261120/               # contract records
python3 scripts/devnest/kk_mac_admission.py        # live gate
```

Pre-existing unrelated failure: `test_lane_gate.py::
test_s1_requires_opencode_lanes_env` fails on a clean stash too.

## Caveats

- The bench ran from tony-dell (trusted ssh path); idc02 cannot ssh
  to kk-mac — the lane's fleet runners need that hop or a runner key.
- Bench ran while owner GUI apps were open — deliberately the
  realistic condition; numbers may differ on an idle box.
- Quiet-hours env is code-live but not yet set in the installed plist
  on kk-mac — flipping it is an owner-window change, recorded in kb.
- `gpt-oss:20b`/`qwen3:30b-a3b` were pulled at some point by the owner
  side — this session pulled nothing.

## Board

Two comments posted (start + final). No requests raised — no decisions
needed Tony. No pushes, no commits to default branch.

lessons:
- idc02 cannot ssh kk-mac directly (publickey denied for tony@ and
  kkkakk@); the working path is `ssh tony-dell` then
  `ssh kkkakk@kk-mac` — run the executor contract on dell's exec
  checkout (it was in sync, md5-verified).
- On kk-mac, zsh interprets `echo ===X===` as `=command` expansion —
  use `---` markers or quote them in remote command bundles.
- Ollama keep-alive means the previous model stays resident during
  the next model's load — transient double-footprint is what pushed
  free memory to 20%; unload (keep_alive:0) alone didn't prevent it,
  so sequential size ladders need a settle wait + /api/ps recheck.
- `reports/*` is gitignored — durable reports for merge belong in
  `docs/reports/` (or force-add); evals/ artifacts are tracked fine.
- qwen3:30b-a3b and gpt-oss:20b ignore Ollama `think:false` — they
  burn tokens on visible reasoning preamble; count that in lane cost.
