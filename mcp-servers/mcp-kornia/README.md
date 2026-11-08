# mcp-kornia

Read-only image-set evaluation tools for Gaussian Splat capture triage.

Tools (all read-only, all return JSON plus a durable `artifact_ref`):

- `inspect_image_set` — dimensions, duplicates, luma, sharpness, gates,
  recommendation (deterministic, no model).
- `match_views` — pairwise view overlap. cv2 SIFT/ORB + BFMatcher + RANSAC
  inliers when OpenCV is installed (downscaled to <=1024px); kornia
  DISK/LightGlue descriptor matches when torch+kornia exist; clean
  unavailable-backend error otherwise.
- `propose_foreground_masks` — review-only heuristic saliency masks
  (PNG + manifest). Proposals only; approval required before training.
- `score_capture_manifest` — 0-100 capture score combining image metrics
  with pack-manifest gates (hashes, privacy, file counts).
- `compare_gs_runs` — compare two run dirs: paired renders PSNR/SSIM,
  PLY gaussian counts, metrics.json, registration artifacts. LPIPS only
  when torch+lpips exist.

Artifacts land under `$GS_EVAL_ARTIFACT_ROOT` (default
`~/.local/share/gs-eval-artifacts/<tool>/<dataset>-<ts>/result.json`).

The server never trains, edits, uploads, deletes, or publishes media.

Run locally:

```bash
python3 -m pip install -r requirements.txt
python3 server.py
```
