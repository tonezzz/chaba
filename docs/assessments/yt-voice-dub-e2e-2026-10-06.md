# YT voice dub — E2E assessment

Status: **assessment for review** — written 2026-10-06 before scaling past the
minimal test. Card: `yt-voice-dub-e2e`; parent test: `yt-voice-dub-test`
(v1–v17 render history is the evidence base); sibling cards:
`yt-voice-dub-cast` (done), `yt-voice-dub-scenarios` (backlog — `blocked_by`
is now satisfied since cast closed).

## TL;DR

Cue-level edge-tts dubbing **works at minimal-test scale** — 17 render
iterations on two specimens (a 2-speaker dialogue, a 3-speaker talk-show
slice) converged on a watchable Thai dub at natural speech rate with distinct
voices per speaker, for zero marginal cost and no new infrastructure. The
approach's real ceiling is not TTS quality but **caption truth**: every major
defect Tony heard (speed, overlap, gibberish) traced back to source-caption
artifacts, not to edge-tts. Recommended next lanes, in order: **voice-mode
selector on the cast URL** (productization — today the dub is an offline
side-render, not part of `/cast`), **caption QC gate**, residual **cue-fit**
polish, **speaker casting v2**. Cloud neural TTS stays parked until demand
proves out. Hard boundary: **no voice cloning, lip-sync, or cloning-grade
diarization** until the minimal test lands.

## Pipeline today (as of v17, 2026-10-05)

All scripts repo-homed in `scripts/ops/` (`yt-pipeline-install.sh` refreshes
`~/.local/bin` copies; both resolve siblings standalone).

```
yt-dlp (video + auto-captions)
  -> subs.vtt merge (yt-vtt-translate.py, Gemini; cached per vid+langs)
  -> yt-vtt-dub.py:
       karaoke word stream from src.en.vtt
       -> rolling-caption dedup (char-level suffix-prefix strip)
       -> sentence groups (--sentences, --sent-gap 1.4s)
       -> speaker turns (--cast-detect heuristic, or --cast-times /
          pyannote diarization output) -> fixed voice per speaker
       -> edge-tts per group (rate resynth <=+35%, atempo <=1.4x,
          onset/tail silence stripped, shared --lag-budget)
       -> queue timeline (caption pauses ARE the breath; +0.3s only on
          zero-air speaker turns)
       -> loudnorm dub + sidechaincompress-ducked original -> dub.mp4
  -> served /apps/yt-live/ -> play_media on tony_tv_cast
```

Caption-less videos route through `yt-whisper-vtt.py` (faster-whisper →
karaoke VTT) first. Real diarization runs offline on tony-omen
(`~/.venvs/diarize`, pyannote speaker-diarization-3.1, torch cu130); output
is verified against transcript anchors before casting. Cast entry point is
`yt-live-api.py :8791` → `POST /cast {q|url|query, lang}` → `yt-live.sh`.

## Pros — cue-level edge-tts

- **Free.** edge-tts rides Microsoft's demo endpoint; the entire v1–v17
  iteration cost $0 in TTS.
- **Offline-capable caches already exist.** Media cache
  (`~/.cache/yt-live-media`, now staged on mn01 `~/media-corpus` with rclone
  gdrive backup) and translation cache (`~/.cache/yt-live-subs`) mean a
  repeat cast replays in ~1–6s; adding TTS mp3s to the same key scheme is a
  small extension.
- **Reuses the VTT + HLS plumbing.** No new serving path, no new cast path:
  the dub muxes into the same `apps/yt-live/` docroot and the same
  `play_media` call. `--offset`, `--burn-vtt`, `--dump-*` all ride the same
  artifacts.
- **Decent TH/EN voices for narration.** Premwadee (F) + Niwat (M) sound
  acceptable at 0.95–1.0 rate once sentence-level prosody was restored (v11).
- **Debuggable.** Every stage emits inspectable artifacts (turn table, group
  table, bare dub wav, per-video fix-map) — the v1–v17 debugging loop was
  fast precisely because each hypothesis could be isolated.

## Cons — and what the v1–v17 history showed

| Con (as specced) | Status after minimal test | Evidence |
|---|---|---|
| Rough cue timing; stretch/pad sounds mechanical | **Mostly solved** — the primitive was wrong, not the fit: sentence groups + one uniform global rate + lag budget landed natural rate (v11: 0.95; v17: 0.95) | v5 per-cue atempo ≤1.4x → v6 uniform rate → v11 sentence groups → v16d lag-budget 59.8→39s → v16h silence-strip 17→9.2s |
| No speaker separation | **Partially solved** — heuristic `--cast-detect` + real pyannote diarization both work; >2 speakers still constrained by 2 TH voices + pitch offsets | v9 hand-labeled 2-voice; v16 3 speakers via `voice@NHz` pitch; v17 pyannote 98→62 turns, anchor-verified |
| Caption errors flow into TTS | **Root cause of the worst defects; partially mitigated** | v8: rolling-caption dedup removed ~40% duplicated text (the "overlap" Tony heard); v10: same dedup applied to the burned subs; v15: `--fix-map` for systematic TH mis-reads (โล่งอก → โล่ง​อก via ZWSP). Residual: no QC gate before TTS |
| Flat ducking drowns music/fx | **Solved** — `sidechaincompress` keyed on the dub (v16f); EN drops only while Thai speaks, ambience returns in gaps | confirmed in renderer; was also misdiagnosed as "overlap" — original banter bleeding under Thai at constant 0.22 duck |
| No lip-sync | **Accepted** — fine for info/narration, wrong for dialogue-forward content. Not on the improvement path; it's a content-selection rule | The Egg (off-screen narrator) worked; Norton banter is watchable but visibly off |
| edge-tts service quirks | **Known, handled** | ~200ms leading / ~150ms trailing silence per mp3 (stripped since v16h); flaky under parallel load → 3-try retry loop; exactly 2 TH voices |

**Additional cons surfaced during the test** (not in the original spec):

- **MT translation register.** Fragment-by-fragment translation guarantees
  choppy Thai (v12 lesson); the fix is translating the sentence groups, not
  the cues. TH text runs ~1.4× longer than the EN cue window — a structural
  constraint, not a bug.
- **Auto-caption `>>` speaker markers are too noisy** for turn detection
  (72/240s on The Egg) — diarization or hand-labels are still needed for
  clean borders.
- **The dub is not wired into `/cast`.** `yt-live.sh` produces subs-only
  casts; the dub is a separate offline render + manual `play_media`. Voice
  mode can't be requested through the API today.

## Ranked improvements

The card's original ranking, annotated with where each stands after the
minimal test, and re-ranked by current leverage:

| # | Lane (spec order) | Status | Recommendation |
|---|---|---|---|
| 1 | Cue-fit TTS — pick voice rate per cue instead of post-stretch | **Substantially landed** in evolved form (sentence groups + uniform global rate + ≤1.4x atempo cap + lag budget). Residual: per-group rate spread, translation-length-aware fitting | Fold the residual into a small polish lane — **low priority** |
| 2 | Caption QC gate — flag too-short cues / implausible durations before TTS | **Partially landed** (dedup + clean burn + `<0.4s` drop + fix-map). Open: a real gate that scores cues and refuses/quarantines bad ones pre-TTS | **Filed: `yt-voice-dub-qc`** — highest quality-per-effort remaining |
| 3 | Sidechain ducking keyed to dub segments | **Landed** (v16f) | Done — regression-covered by `dub_duck_mix` in `yt-voice-dub-scenarios` |
| 4 | Voice-mode selector on the cast URL | **Open** — the productization lane | **Filed: `yt-voice-dub-mode`** — highest leverage; today nobody can request a dub except by hand-running the renderer |
| 5 | Voice casting — fixed TTS voice per detected speaker | **Partially landed** (heuristic + pyannote both proven). Open: diarization wired into the render flow (currently offline on tony-omen), >2-speaker casting, turn borders without hand-labels | **Filed: `yt-voice-dub-speakers`** — also unblocks `yt-voice-dub-scenarios` verification (voices-per-speaker metric) |
| 6 | Cloud neural TTS / full speaker-aware dub | **Gated on demand** | Not filed. Revisit only if lanes 1–5 land and real usage still bumps into the 2-voice / naturalness ceiling. Paid TTS buys more voices and better Thai prosody, not better caption truth — fix QC first |

**Re-ranked drain order** (leverage-adjusted): `yt-voice-dub-mode` →
`yt-voice-dub-qc` → `yt-voice-dub-speakers` → cue-fit residuals → (gated)
cloud TTS.

## Boundary — explicit

Until the minimal test lands (Tony's watch verdict on a full pipeline run,
tracked by `yt-voice-dub-test`):

- **No voice cloning** — edge-tts stock voices and pitch offsets only. No
  speaker embeddings used to synthesize a voice; pyannote embeddings are for
  turn *detection*, not voice reproduction.
- **No lip-sync work** — no video re-timing, no Wav2Lip-class models.
  Content selection (info/narration over dialogue) is the mitigation.
- **No cloning-grade diarization** — speaker-diarization-3.1's
  SPEAKER_NN labels + transcript-anchor naming (v17 method) is the ceiling;
  no biometric voiceprint identification of who a speaker *is* beyond
  transcript anchors.

If Tony rejects the minimal test, the whole program retires — none of the
lanes above are worth building on a dub nobody watches.

## Follow-on cards filed

| Card | Lane | Priority |
|---|---|---|
| `yt-voice-dub-mode` | voice-mode selector on `/cast` (off/TH/EN), dub wired into `yt-live.sh` + media-cache key | high |
| `yt-voice-dub-qc` | caption QC gate pre-TTS + TH fix-map watchlist automation | medium |
| `yt-voice-dub-speakers` | diarization-driven casting in-render, >2 speakers, auto turn borders | medium |
| `yt-voice-dub-cuefit` | residual cue-fit polish: per-group rate, length-aware TH fitting | low |

Not filed: cloud neural TTS (gated on demand). Already tracked elsewhere:
`yt-voice-dub-scenarios` (benchmark/scenario coverage — `blocked_by` cast is
now satisfied, ready to queue).

## How to review

1. Watch the current renders: `dub-v17-diar.mp4` (Graham Norton 3-speaker)
   and the `dub-compare.html` page under `/apps/yt-live/` on any browser;
   `yt-voice-dub-test` comms carry the per-version changelog.
2. Decide the minimal-test verdict: land / iterate / retire.
3. Queue whichever follow-on lanes are wanted (`▶ Start` on the cards);
   close `yt-voice-dub-e2e` when the ranking above looks right.
