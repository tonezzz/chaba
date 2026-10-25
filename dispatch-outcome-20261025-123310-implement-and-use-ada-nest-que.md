# Dispatch outcome — nest-gap-gpu-runner (OPS-0854)

## What changed

Implemented `ada-nest/queue/gap-runner.py` + gap-packs properly — the
13:36 staging on Drive was **broken and never ran**: `pack.json` was
invalid JSON (stray `chmod` line → silent skip forever), `queue/gap-lease`
was declared but never used, there was no mid-run abort (a gap pack would
keep burning GPU after the main queue reclaimed it), no artifact
verification, and `claim()` always returned True.

New canonical sources in repo (commit `addddab6` on the dispatch branch):

- `scripts/colab/gap-runner.py` — one-pass scanner; gates on fresh
  heartbeat (<=60s) + phase in {prep, prep-wait} + `nvidia-smi` free VRAM
  >= pack floor + free/owned `queue/gap-lease` + unclaimed pack. Mid-run:
  polls window+lease every 10s, SIGTERM→SIGKILLs the pack's process group
  on close, releases the claim for retry. Verify-before-mark artifact
  gate; `done`/`failed` FILE markers; forbidden-pattern scan (model pulls,
  cache writes, second runner); `queue/gap-heartbeat` for fleet watchers.
- `scripts/colab/gap-packs/embedding-smoke/pack.json` — first gap pack:
  10 docs through RESIDENT nomic-embed-text (ollama /api/embed), explicit
  no-pull guard (/api/tags check → refuse, never fetch), 120s timeout,
  writes only under `gap-packs/embedding-smoke/out/`. Zero production
  mutation.
- `scripts/colab/gap-packs/PROCEDURE.md` — policy + pack contract.
- `scripts/colab/gap-launcher-cell.py` — detached 20s supervisor loop,
  rerun-safe via `queue/gap-runner.pid`.
- `tests/colab/test_gap_runner.py` — 9 sandbox tests, all pass: stale-hb /
  run-phase / low-VRAM / foreign-lease blocks, forbidden-pattern skip,
  no-pull guard (0 embed calls), end-to-end DONE (10 docs, 768 dims,
  artifact + done + lease released + idempotent second pass), prep-wait
  window, mid-run abort.
- `docs/ssot/jobs/nest/2026-10-25-ada-nest-gap-runner.yml` — job record.
- `docs/kb/colab-mcp-jobs.md` — gap-pack section added.

## Deployed

`rclone copy` to `gdrive:ada-nest/queue/gap-runner.py` (md5-identical to
repo source) + `gdrive:ada-nest/gap-packs/` (PROCEDURE.md, valid
embedding-smoke/pack.json).

## Use / verification status

- Sandbox "use" proven end-to-end on mn01 (no GPU/ollama here — stub
  nvidia-smi + mock ollama on :11434 exercised the real code path).
- No live fire possible this session: queue heartbeat was ~13min stale,
  `QUEUE-DRAINED` 12:19 UTC, `runner.pid` gone — no awake runtime, so the
  gate correctly has nothing to fill. First real run needs a Colab
  runtime + one paste of `gap-launcher-cell.py`; it then self-fires on
  the next fresh prep/prep-wait window.
- Verify then: `rclone cat gdrive:ada-nest/queue/gap-runner.log`,
  `queue/gap-heartbeat`, `gap-packs/embedding-smoke/{done,out/}`.
