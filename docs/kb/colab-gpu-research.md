# Colab GPU Image/Video Generation Research

## Experiment 01: Stable Diffusion 512×512 on Tesla T4

| Field | Value |
|---|---|
| Model | prompthero/openjourney |
| Prompt | a serene lake in the mountains at sunset, highly detailed |
| Resolution | 512×512 |
| Steps | 25 |
| Guidance scale | 7.5 |
| Seed | 42 |
| Device | Tesla T4 |
| Pipeline load time | 119.4 s |
| Generation time | 5.2 s |
| Peak VRAM | 3257.6 MB |
| Output image | `~/.local/colab-research/exp-01/generated.png` |
| Output JSON | `~/.local/colab-research/exp-01/report.json` |

## Observations

- `diffusers`, `transformers`, `accelerate` install and load cleanly on the Colab T4 runtime.
- Pipeline download + UNet load dominates wall time; actual 25-step inference is fast.
- VRAM stays well under the 15 GB T4 budget for 512×512 fp16 generation.
- HF downloads were unauthenticated (no `HF_TOKEN`); gated models (SDXL, FLUX, etc.) would need a token.

## Next

- Try 768×768 or SDXL/FLUX to measure VRAM/time scaling.
- Test short video (Wan 2.1 / SVD) once the image pipeline is trusted.

---

## Working agreement — on-demand sessions

Free Colab GPU is quota-limited and VMs idle-timeout fast, so **we never keep sessions warm**. Each experiment runs via `colab run` which allocates a fresh VM, executes the script, and releases it:

```bash
source ~/.local/venvs/colab-test/bin/activate
uvx --from google-colab-cli==0.7.4 colab run --gpu T4 \
    scripts/colab/img_gen.py -- \
    --model prompthero/openjourney --prompt "<prompt>" \
    --width 512 --height 512 --steps 25 --seed 42
```

- `--timeout` defaults to 30 s — pass `--timeout 600` for weight-cached runs, more on cold starts (pipeline load was ~119 s).
- Outputs land in `/content/output` on the VM; pull with `colab download -s <session> ...` — or use `--session <name> --keep` to hold the VM open for follow-up `colab exec`, then `colab stop -s <name>`.
- The browser `colab-mcp` server (`open_colab_browser_connection`) stays available for interactive notebook work on whichever runtime is switched to GPU.
- Note: `google-colab-cli` 0.6.0 `exec` is broken with the installed `jupyter-kernel-client`; pin `uvx --from google-colab-cli==0.7.4` until the venv is upgraded.

## Experiment queue

| # | Task | Model | Config | Status |
|---|---|---|---|---|
| exp-01 | SD baseline | prompthero/openjourney | 512×512, 25 steps, g7.5, seed 42 | ✅ done — 5.2 s gen, 3.26 GB VRAM |
| exp-02 | Resolution scaling | prompthero/openjourney | 768×768, 25 steps | queued |
| exp-03 | Larger model | stabilityai/sdxl-turbo (needs HF token) | 512×512 | queued — gated model |
| exp-04 | Video probe | aiges/svd or similar | short clip | queued — needs T4+ feasibility check |
