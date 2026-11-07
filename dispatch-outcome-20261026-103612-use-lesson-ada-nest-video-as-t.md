# Dispatch outcome — ada-nest-fishing-final-cut (2026-10-26)

## What was done
Built the Golden Hour Catch 14s teaser final cut from the preserved baseline
(`full_story.mp4`, 7 shots / 2.04s cuts, 640x384@24 H.264, silent — SHA-256
verified against the gdrive reference manifest, untouched).

Both card gates were already answered by Tony (14s-teaser +
neutral-thai-narrator), so the session went straight to production:

- **Narration**: edge-tts `th-TH-NiwatNeural` (neutral, non-cloned), rate −8%,
  4 beats placed at 0.35 / 4.25 / 8.30 / 11.40s matching the shot groups.
- **Ambience**: synthesized gentle surf bed (filtered brown noise, ~4.5s swell),
  sidechain-ducked under VO — no stock asset existed in gdrive:ada-nest.
- **Captions/credits**: Thai burned via libass + Noto Sans Thai (the static
  ffmpeg build lacks drawtext); EN+TH title 0.45–4.2s; credit 12.3–14.29s.
- **Mix**: VO ≈ −17 dB mean, ambience gaps −27..−34 dB, loudnorm −16 LUFS,
  max −1.4 dB, AAC 48 kHz mono.
- **QC**: `scripts/ops/video-qc.py` (from feat/ops-0882-p0 @661b8e373) all
  checks pass — decodes, no black/freeze, audio finite; manual
  T2V-CompBench/VBench-style rubric noted in the manifest (i2v wardrobe
  drift between shots = known LTX limitation, acceptable for teaser).

## Deliverable
`gdrive:ada-nest/renders/golden-hour-catch-final/`
- `golden-hour-catch-teaser-v1.mp4` — H.264+AAC, 14.292s, 2,352,026 B,
  sha256 `4e06a67f681b099bcd0e17efa07e54c27587a6456a9556d4af9dae46e5a3581e`
- `final-manifest.md`, `captions.ass`, `subs-th.srt`, `vo-lines.txt` (sources)

## Access review (explicit)
Lands in the same `gdrive:ada-nest/renders/` tree as the reference archive —
inherits identical sharing, no permission change made. NOT uploaded to WP
media: the original uploads URL is already anonymous-fetchable, so publishing
the final there is a deliberate exposure step left for Tony (option in the
open request).

## Board / trail
- Card comms updated (status + full result); open request asks Tony to
  approve-final / approve-and-wp / needs-fixes.
- Lesson `ada-nest-video` (post 1914) updated in place with the final-cut
  section and the mn01 tooling note.
- SSOT trail: `docs/ssot/jobs/nest/2026-10-26-golden-hour-catch-final-cut.yml`
  (committed on the dispatch branch; `media/` added to .gitignore — 237M
  scratch: static ffmpeg + venv + work files).

## Verify
`rclone lsl gdrive:ada-nest/renders/golden-hour-catch-final/` then play the
mp4 — expect TH VO over 7 fishing shots, title at 0.5s, captions per beat,
credit on the final wide, clean fade ~14.3s. Baseline still at
`golden-hour-catch-reference/` unchanged.

## Remaining gate
Tony's review of the rendered file (board request open). No paid Veo calls,
no permission changes, no pushes.
