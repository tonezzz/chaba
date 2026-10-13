# dispatch outcome — build scripts/micro-bench host coverage (20261013-123825)

## Context

Card `micro-ai-input-polish` spec = this dispatch task. Prior dispatches had
already landed the harness (`scripts/micro-bench/` — 44-fixture manifest,
bench.py, report.py, lib.py, providers.py) and benched idc03/gemini variants.
The remaining spec gap was **variants on the three named hosts**: llama-router
on omen, macbook Vulkan llama.cpp, idc02.

## What changed (commit 746b48b2 on this dispatch branch)

- `scripts/micro-bench/providers.py` — new `ssh_openai` provider: an
  OpenAI-shaped `/chat/completions` call piped over an ssh prefix to a remote
  loopback server (`ssh: idc02`, or `ssh: tony-dell ssh macbook` for the dell
  hop — mn01 holds no macbook key). Real usage tokens survive, no tailnet
  listener opened; 3x retry on transient sshd resets (macbook laptop dropped
  connections mid-run). Also added `max_tokens: 256` to openai_compat +
  ssh_openai calls — uncapped phi3 rambles were burning the 120s timeout.
- `scripts/micro-bench/variants.yml` — three new variants, all paired against
  `direct-llama32` (llama3.2:3b on idc03 downstream):
  `polish-omen-phi3-llama32`, `polish-idc02-llama32-llama32`,
  `polish-macbook-vulkan-llama32-llama32` (all with lang_preserve gate).
- `scripts/micro-bench/README.md` — provider docs + bench-host provisioning
  notes (how to start the remote units).
- `docs/ssot/infrastructure/ssot.gpu.yml` — corrected stale note: the "llama
  router on :8001" is gone; that port is sensor-reader. Omen's live lane is
  ollama :11434 (phi3-gguf).
- `docs/ssot/jobs/models/2026-10-13-micro-polish-host-coverage.yml` — job
  record with provisioning detail + measured numbers + verdict.

## Infra provisioned (outside worktree, on remote hosts)

- `idc02` and `tony-macbook`: `~/micro-bench/` with llama.cpp b11583
  (ubuntu-x64 / ubuntu-vulkan-x64) + Llama-3.2-3B-Instruct Q4_K_M gguf, and
  user unit `micro-bench-llama.service` serving loopback :8114.
  `loginctl enable-linger` was applied on macbook. **Both units are stopped
  now** — start per README before a bench run.

## Bench results (44 fixtures, this worktree's results/)

| variant | exact% | net tok | total ms | fab | verdict |
|---|---|---|---|---|---|
| direct-llama32 (baseline) | 0.278 | 275.77 | 5488 | 1 | — |
| polish-omen-phi3-llama32 | 0.167 | 657.10 | 22066 | 2 | REJECT |
| polish-idc02-llama32-llama32 | 0.306 | 464.09 | 8030 | 1 | SCOPE (marginal +1 noisy) |
| polish-macbook-vulkan-llama32-llama32 | 0.278 | 463.34 | 8669 | 1 | REJECT |

Report: `reports/micro-polish/LATEST.md` + `trend.md` (reports/ is
gitignored — regenerate with `python3 scripts/micro-bench/report.py`).
Board comment posted to `micro-ai-input-polish`.

**Reading:** 3B-class prompted polishers don't pay their token+latency tax at
the llama3.2:3b insertion point — host placement changes nothing (idc02 and
macbook run the same weights to near-identical numbers; phi3-gguf doesn't
normalize at all). Consistent with earlier rounds: only a strong polisher
(gemini-3.5-flash-lite → gemini downstream) ever hit SCOPE.

## Verify

```
cd scripts/micro-bench
python3 bench.py --variant dry-run-dummy --dry-run   # schema smoke
python3 report.py                                   # re-render LATEST.md
# live re-run (starts remote servers first, per README):
ssh idc02 systemctl --user start micro-bench-llama
python3 bench.py --variant polish-idc02-llama32-llama32
```

Known flake: macbook sshd resets under rapid sequential ssh (laptop) — the
provider retries 3x; 6/44 fixtures still errored in the final run.
