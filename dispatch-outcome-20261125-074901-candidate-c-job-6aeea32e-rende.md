# dispatch-outcome — omen-sdxl-full-model-experiment (OPS-1078)

## What changed / was found

**Experiment ran end-to-end.** Controlled re-run of the candidate-C
prompt through `/sdcpp/v1/img_gen` on a full `sdxl-base-1.0-Q8_0.gguf`
checkpoint on tony-omen:

- Parallel `sd-server` instance on `:8400` via transient systemd unit
  `sd-q8-exp` (MemoryMax=12G, Nice=10, threads 6). Production
  `sd-server.service` on `:8399` (lightning) was never touched and
  stayed active — verified after teardown.
- Job `job_6b063236_00000000`, verbatim candidate-C prompt/negative,
  seed 20261106, 20 steps, txt_cfg 7.0, euler_a, 1344x768 — 5591s wall
  (~93min) under omen load ~10-50.
- Result landed to the campaign as
  `comparison-h-omen-sdxl-q8-cprompt`
  (gdrive:ada-nest/adobe-stock/campaigns/AS-2026-11-05-REMOTE-WORK-001/30-candidates/,
  sha256 `13ab4de2…`, 1344x768, qc pending_tony). QC context note with
  metrics appended to `40-qc-review.md`.

**Premise correction:** the card says C ran "20 steps/CFG7" — the
actual Nov-6 submission (`~/adobe-stock-gemini-c.7wBI1T/sd_submit.py`
on tony-dell) used `sample_steps=8, txt_cfg=1.0`, Lightning's intended
recipe. Painterly output happened at the checkpoint's design point.

**Prior art discovered:** the Q8 model was already on omen (pulled
2026-11-07) and the experiment had effectively already run as
`comparison-d-omen-sdxl-q8` (job_6aeee1d0) + `comparison-g` — Tony QCd
D as "smooth and good, but doesn't feel like photorealistic … model
ceiling (SDXL Q8 CPU)". This dispatch adds the airtight third data
point with the verbatim prompt and documented params.

**Gate answer:** sd-server (master-964) has NO hot model swap — one
`-m` checkpoint at startup, no reload route (verified in source route
table + `/sdapi/v1/sd-models`). Non-disruptive swap = parallel instance
on another port (proven today, ~4GB params RAM + render buffers);
alternative = service restart with new `-m` (~1-2min down, kills
in-flight). omen swap was 100% full — the MemoryMax-capped transient
unit is the safe wrapper.

**Verdict:** painterly = Lightning distillation, not Q4 quantization.
Q8 base gives ~26-37% more Laplacian-variance detail (C 1218 / D 1670
/ H 1531) but CPU SDXL still isn't stock photoreal → omen sd lane is
**illustration-tier**; photo lanes stay kk-mac diffusers / gemini-image
/ CF workers-ai.

## Files

- `docs/ssot/jobs/nest/2026-11-25-omen-sdxl-q8-experiment.yml` — full
  trail: question, premise correction, prior evidence, method,
  gate answer, runbook, result, verdict.
- `docs/ssot/infrastructure/ssot.tools.yml` — `media.render_image`
  gained a `notes:` marking the omen sdcpp lane illustration-tier.
- Campaign artifacts on gdrive (above) — candidate + QC note.
- omen scratch: `~/sd-q8-exp/` (submit.json, watch.sh, status.txt,
  job-result.json, result-meta.json, PNG) — kept for audit;
  `sd-q8-exp.service` stopped, port 8400 closed.

## How to verify

- `rclone lsf gdrive:ada-nest/adobe-stock/campaigns/AS-2026-11-05-REMOTE-WORK-001/30-candidates/comparison-h-omen-sdxl-q8-cprompt/`
- `ssh tony-omen 'systemctl --user status sd-server'` → active, :8399,
  lightning model; `curl -s http://100.75.102.88:8399/v1/models`
- `curl -s http://100.75.102.88:8400/v1/models` → connection refused
  (temp instance gone)
- SSOT: `docs/ssot/jobs/nest/2026-11-25-omen-sdxl-q8-experiment.yml`;
  `python3 -c "import yaml;yaml.safe_load(open(...))"` clean;
  `node scripts/ssot-validate-all.mjs` → 6392 files, 0 errors.

## Followups

- Tony visual QC of comparison-h (expected same band as D).
- comparison-g-omen-sdxl-q8-wallfix QC still pending in SESSION.json.
- If a future lane needs the Q8 checkpoint routinely, promote the
  parallel-instance pattern into a second declared unit or keep
  sd-cli for batch work.

lessons:
- sd-server jobs are in-memory only — params/prompt of past renders
  are unrecoverable after restart; always record the submit payload
  (this run's submit.json saved the day).
- `curl -d @~/file` does NOT expand `~` — use absolute paths in
  non-interactive ssh commands.
- omen swap was 100% full while 16GB RAM sat "available" — check
  `free -m` swap line, not just available, before adding a ~5GB
  resident model; a systemd MemoryMax cap protects neighbors.
- The read tool cannot display images to this model — verify renders
  via metrics (Laplacian variance) + prior human QC of the same
  pipeline, and leave the aesthetic call to Tony's QC flow.
