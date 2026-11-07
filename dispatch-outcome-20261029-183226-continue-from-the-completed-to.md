# Dispatch outcome — kk-video-preview-output-qc-assembly (OPS-0952)

Session: dispatch-wt-20261029-183226-continue-from-the-completed-to on tony-macbook, 2026-10-29.

## What this session found (verified, not assumed)

The card spec describes the state after Colab run-20261027-0843 (artifact gate
rejecting small shots, zero-byte narration). Board comms show that state was
resolved later:

- The preview pack was rewritten to validate each MP4 with ffprobe metadata,
  full decode, and blackdetect instead of the >50KB size cutoff; shot04 was
  selectively rerendered; Edge-TTS handling gained rc/non-empty checks and
  serialized retries.
- `run-20261028-1329` completed the **private V1 60s teaser**: all 10 shots
  passed per-shot QC (73f/3.04s each, full decode, black=0.00s),
  narration.mp3 = 152,685B (Edge `th-TH-PremwadeeNeural`), TH/EN SRTs,
  teaser-preview.mp4 = 1,216,460B, done marker + verdict.md on Drive.
- Tony then approved: all v1_01 PDF pages for private use
  (`source-image-private-use-approval`), `storyboard-order-v2` scene mapping,
  KK voice-clone permission, and `approve-private-v2` — one private V2 preview
  with mapped shots + cloned narration, no public release.
- The answer-sweep queued that approval; a prior session built and staged
  `packs/kk-video-c9f99fee6146-preview-v2/` in Drive (2026-10-29 18:08).

## What this session did

1. Downloaded and reviewed the staged V2 pack (`pack.yml`,
   `run_preview_v2.py`, `run_narration_v2.py`, `inputs/scene-map.yml`):
   - Scene map binds shots 1-10 to audited v1_01 storyboard images
     (image-006..015 on pages 9..36); source sha256 pinned to the approved
     PDF hash; every image verified by byte size + sha256 at run time.
   - Renders via LTXImageToVideoPipeline with the existing shot embeddings;
     resumable sidecars; per-shot QC = h264 640x384, >=70/73 frames, full
     decode, blackdetect <80%.
   - VYNCX v2 / F5-TTS-TH narration gated on consent manifest scope+sharing
     and the probe verdict's reference hash; 4 cues x 15s = 60s narration.wav;
     per-cue duration/RMS/read-back QC.
   - Final teaser QC = h264+aac, 59-61s, full decode; verdict.json + report.md.
2. Verified all prerequisites read-back from Drive:
   - v1_01 `audit.json` sha256 = `5a6ef654…` matches scene-map binding; all
     10 required images hash+size-match their declared pages.
   - 10/10 shot embeddings present (`embeds/shot*.pt`, 4,197,011B each).
   - V1 `teaser-preview.th.srt` satisfies the strict 4-cue x 15.0s contract;
     `.en.srt` present.
   - `voice-reference/manifest.json` scope/sharing gates pass; probe
     `verdict.json` = probe-pass, reference file/hash matches a manifest
     sample (d54cfb4e…, used_s 10.07 within 5-12s).
   - `r4-preflight` done + `preflight.json` verdict=pass (0 fails) — satisfies
     the `*-preflight` requires claim gate. All 6 `requires` packs are DONE.
   - Pack files on Drive are byte-identical to canonical source.
3. Landed the canonical pack source + regression test + job doc into this
   dispatch branch (they previously existed only as untracked files in
   worktree `chaba-wt-kk-pdf-image-audit`). 4/4 unit tests pass.
4. Confirmed there is no fleet-side way to execute the pack here:
   this host has no CUDA (Intel iGPU + AMD Radeon); the pack requires
   `torch.cuda` and `needs.gpu_gb: 14`; the only live nest-worker
   (KKs-Mac-Studio) fits CPU packs only. All managed Colab sessions are
   stale; the console documents that consumer Colab runtime provisioning
   is a manual UI action.

## Result

- **The V2 run is HELD per Tony.** At 19:31 the staged `pack.yml` gained a
  requires-gate on nonexistent pack
  `kk-video-c9f99fee6146-preview-v2-resume-authorized` — comment: "Deliberate
  hold per Tony; remove only when resuming the Colab V2 run." The gate fails
  closed at claim time on every worker (Colab and fleet nest-worker), so no
  worker can claim the pack until the authorization pack's done marker
  exists or the requires line is removed. I mirrored the hold line into the
  canonical repo copy so Drive and repo stay byte-identical.
- Before the hold, this session verified the V2 pack end-to-end as
  claim-ready (all inputs hash-verified, all requires DONE, r4 preflight
  pass, 4/4 unit tests).
- Resume path: create the `preview-v2-resume-authorized` marker pack (or
  remove the requires line), run console Cell 1 on a managed T4, then
  `colab_queue_start`; afterwards verify every declared artifact glob reads
  back non-empty and run independent ffprobe/decode QC before marking the
  Nest job done.
- The board request for Cell 1 remains open on the card but is superseded
  by the hold unless Tony lifts it.
- V1 private teaser artifacts remain intact and verified on Drive.

## How to verify

- `rclone lsl gdrive:ada-nest/packs/kk-video-c9f99fee6146-preview-v2/` —
  pack staged, no out/ until a run completes.
- `rclone cat gdrive:ada-nest/packs/kk-video-c9f99fee6146-preview/done` —
  V1 artifact-gate record.
- `python3 -m unittest tests.colab.test_kk_video_preview_v2` — 4/4 pass.
- Job doc: `docs/ssot/jobs/nest/2026-10-29-kk-private-v2-preview.yml`.
