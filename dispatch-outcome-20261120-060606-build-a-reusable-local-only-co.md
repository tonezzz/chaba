# dispatch-outcome — devnest-colab-t4-model-slot-adapter

## What changed

Rebuilt the Colab T4 model-slot as a reusable, self-contained pack set
(model-only arm — the option Tony answered 2026-10-29), vendored into the
repo so the packs are no longer Drive-only:

- `scripts/colab/packs/devnest-qwen3-8b-hf-prestage/` — vendored 0-diff
  from Drive; already DONE remotely (claimed by con01): pinned
  `Qwen/Qwen3-8B @ b968826d` snapshot, 12 files/16.4 GB, per-file sha256
  manifest + 12.9 GB `qwen3-8b-hf-cache.tar.zst`.
- `scripts/colab/packs/devnest-model-slot-30m/` — rebuilt and RESTAGED to
  `gdrive:ada-nest/packs/` (verified 0-diff). Fixes vs the staged prior
  attempt: prep actually extracts the tar to `/tmp/qwen3-8b-hf` (it only
  asserted the dir before — a guaranteed prep failure), fixtures moved
  inside the pack (`inputs/fixtures.json`; previously read from
  `queue/` outside the pack), `test -d /content` Colab-only guard,
  `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` run env, manifest repo+revision
  pin plus per-file size+sha256 re-verify before load, conditional pinned
  dep install (transformers 4.51.3 / bitsandbytes 0.45.5 / accelerate
  1.6.0) only when absent, `test -d /content` keeps fleet workers out.
- `scripts/colab/packs/devnest-model-slot-60m/` — repo only, NOT uploaded:
  uploading is the operator's explicit 60m-slot decision. `requires:
  devnest-model-slot-30m` plus the 30m pack's `preflight.json` gate token
  means the runner refuses it unless the first slot passed — the "60m
  only after a passing first slot" rule is enforced by the queue
  contract, not by convention. timeout_s 3600, soft cap 3300 s,
  `--repeat 3`.
- `scripts/devnest/shadow_eval.py` — new `t4slot` subcommand: `--check`
  lints the pack contract (name/needs/timeout cap/requires/artifact
  prefixes/pin consistency/fixtures self-containment/`--self-check` of
  the run script) and probes the remote prestage; `--fetch` ingests
  remote `out/{metrics,verdict,report}` + `preflight.json` into
  `evals/shadow/reports/`.
- `docs/ssot/jobs/devnest/2026-11-20-colab-t4-model-slot-pack.yml` —
  runbook/state record.

## Result

`t4slot --check` → pass (both pack lints + remote prestage pin/tar/done).
`t4slot --fetch` → works, verdict `not_run`. The 30m pack name-sorts
immediately before `img-gen-bench-t4` (the pending render pack whose
requires are all done), so the render's ~33 GB CPU/network prep is the
only thing overlapping the slot's GPU time; `kk-video-…-preview-v2`
remains held on its resume-authorized gate. Queue heartbeat is ~22 days
stale — no active runner; per spec the pack was staged but NOT launched
(launch is Tony's Colab action). No paid API, secrets, personal data,
production mutation, or model download inside the slot; the only remote
writes were the pack's own staging dir.

## How to verify

- `python3 scripts/devnest/shadow_eval.py t4slot --check` → verdict pass
- `python3 scripts/devnest/shadow_eval.py t4slot --fetch` → ingests
  remote artifacts after a queue run
- `rclone lsf gdrive:ada-nest/packs/devnest-model-slot-30m -R` →
  pack.yml + run_hf_slot.py + inputs/fixtures.json
- After the next Colab launch:
  `rclone cat gdrive:ada-nest/packs/devnest-model-slot-30m/out/metrics.json`

note: docs/ssot/ssot.dev-system.assessment.yml is rewritten by a host-side
assessment process on every commit in this worktree; one snapshot was
committed (1e6fdbe603) and the live tail left uncommitted intentionally —
it is not part of the model-slot change.

lessons:
- The prior slot pack's prep asserted /tmp/qwen3-8b-hf but nothing populated it — always trace where prep-time paths come from, not just that they're tested.
- A pack reading fixtures from queue/ is not self-contained; pack-release hashing only covers pack.yml/policy/script + inputs/, so inputs/ is the right home.
- queue-runner's requires gate reads <pack>/preflight.json verdict — writing it from run code makes "second slot only after a passing first" enforceable, not doc-only.
- `test -d /content` in prep is the cheap way to pin a pack to the Colab lane; fleet workers mounting the same Drive otherwise fit gpu_gb floors and claim it.
- Block-scalar shell lines in pack.yml must stay indented — a continuation line at col 0 silently ends the scalar and breaks YAML parse.
