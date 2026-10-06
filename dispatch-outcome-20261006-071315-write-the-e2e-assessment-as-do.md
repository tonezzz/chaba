# Dispatch outcome — yt-voice-dub-e2e

**Task:** Write the E2E assessment for the yt-voice-dub program and file
follow-on cards for chosen lanes.

## What was produced

- `docs/assessments/yt-voice-dub-e2e-2026-10-06.md` — full E2E assessment:
  - Pipeline-as-built summary (karaoke word stream → sentence groups →
    edge-tts per group → sidechain-ducked mix → HLS → cast).
  - Pros (free, offline caches, reuses VTT+HLS plumbing, decent voices,
    debuggable) and cons — each con annotated with landed/partial/open
    status drawn from the yt-voice-dub-test v1–v17 history, plus two cons
    the spec missed (MT register, noisy `>>` markers, dub not wired into
    `/cast`).
  - Ranked improvements table in spec order with status, re-ranked drain
    order: **mode → qc → speakers → cuefit → (gated) cloud TTS**.
  - Explicit boundary: no voice cloning, no lip-sync, no cloning-grade
    diarization until the minimal test lands.
- Four follow-on cards in `docs/ssot/kanban/cards/`, all `column: backlog`,
  `program: yt-voice-dub`, dispatch-armed (status idle — Tony picks):
  - `yt-voice-dub-mode` (high) — `voice: off|th|en` on `POST /cast`, dub
    muxed into `yt-live.sh` HLS, media-cache key extended.
  - `yt-voice-dub-qc` (medium) — caption QC gate before TTS + TH fix-map
    watch-list.
  - `yt-voice-dub-speakers` (medium) — pyannote turn files drive casting,
    >2-speaker pitch-offset families, no hand labels.
  - `yt-voice-dub-cuefit` (low, blocked_by mode) — sentence-level TH
    translation on the group table + bounded per-group rate.
- Not filed: cloud neural TTS (gated on demand per spec). Flagged on
  `yt-voice-dub-scenarios` that its `blocked_by` is satisfied.
- Board comms posted to both cards; commit `3b90bb59` on
  `dispatch/20261006-071315-write-the-e2e-assessment-as-do` (not pushed).

## How to verify

- Read `docs/assessments/yt-voice-dub-e2e-2026-10-06.md` — the "How to
  review" section lists the render artifacts to watch.
- `python3 -c "import yaml; yaml.safe_load(open('docs/ssot/kanban/cards/yt-voice-dub-mode.yml'))"` — all four new cards pass ssot-validate-all.mjs.
- Card `yt-voice-dub-e2e` closes on Tony review per spec.

## Notes

- One pre-existing SSOT validation error unrelated to this work:
  `docs/ssot/jobs/kanban/2026-10-05-board-request-notify.yml` is missing a
  `title` field.
