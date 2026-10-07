# Dispatch outcome — yt-voice-dub-speakers

Upgrade speaker casting to diarization-driven. **Done, verified end-to-end.**

## What changed

- `scripts/ops/yt-vtt-dub.py`
  - `--diarize-file` — accepts RTTM or the v17 `start end SPEAKER_NN` txt;
    `<0.3s` micro-turns dropped (`--min-turn`), adjacent same-speaker spans
    merge; turns convert to cast-times through the existing `voice_at()`
    bisect path (`turns_to_cast_times` now accepts 3-tuples).
  - `speaker_voices()` — `--cast-voices` entries accept `voice@pitchHz`;
    speakers beyond the base count round-robin into pitch-offset families
    (`PITCH_LADDER`: member 1 = +8Hz, 2 = -10Hz, 3 = -18Hz...). Applies to
    both `--diarize-file` and `--cast-detect`.
  - `--anchors 'Name=phrase;...'` — transcript-anchor naming: finds the
    phrase as a token run in the karaoke word stream, resolves the covering
    turn under extended coverage; matched names auto-feed `--names` for
    burn-vtt speaker tags.
  - `--names-map FILE` — writes speaker→voice→name resolution JSON
    (anchor match time, turn count, airtime) for reproducible renders.
- `scripts/ops/yt-diarize.py` (new) — pyannote speaker-diarization-3.1 →
  turn file (+ `--rttm`); runs on tony-omen `~/.venvs/diarize`.
- `scripts/ops/yt-diarize-remote.sh` (new) — omen→mn01-corpus→dell
  handoff: pushes media to omen, diarizes, lands `VID.diarize.{txt,rttm}`
  in `mn01:~/media-corpus/yt-dub-prep/`.
- `scripts/ops/yt-pipeline-install.sh` — FILES += both new scripts.
- `tests/yt_dub/test_diarize_cast.py` — 7 regression tests (green).
- `tests/fixtures/yt-dub/` — U_io turn file, names-map, turns dump.
- `docs/ssot/jobs/yt-dub/2026-10-07-yt-voice-dub-speakers.yml` — runbook:
  handoff commands + separability ceiling documentation.

## Verification (U_io-pqPFfQ, ~20min music interview)

- pyannote on tony-omen GPU: **394 raw turns, 5 speakers → 139 turns**
  after the 0.3s filter.
- **Full render, zero hand-labeled turns** (360s): 68 sentence groups →
  61 spoken, global rate 1.25, lag 15.6s.
- **Anchors spot-checked**: all 4 speakers active in the window named
  (Host=SPEAKER_01 @0.5s "how did you come back", Guest=SPEAKER_00
  @12.5s, Guest2=SPEAKER_04 @157.9s "the seahorses", Guest3=SPEAKER_03
  @279.8s); SPEAKER_02 speaks only past 500s.
- **voices-per-speaker == 1** — each SPEAKER_NN maps to exactly one voice
  spec; 0 group-voice mismatches vs turn coverage. Ready input for the
  yt-voice-dub-scenarios benchmark.
- Artifacts: `mn01:~/media-corpus/yt-dub-prep/` has
  `U_io-pqPFfQ.diarize.{txt,rttm}`, `dub-v18-diar.mp4`, `burn.vtt`,
  `names-map.json`; local copies in `/tmp/ydub/` and
  `tests/fixtures/yt-dub/`.

## Caveat

All Gemini API keys on tony-dell returned **401** this session — merged
TH subs could not be generated, so verification rendered `--lang en`
(identical casting path). A TH render needs a valid `GEMINI_API_KEY`
for `yt-vtt-translate.py` + the compress pass. Separability ceiling
(TH = 2 base voices, ~3-4 members/family) documented in the jobs yml
and card comms. Note: the raw karaoke VTT is not a valid subs input —
feed a cleaned/merged file.

## How to verify

```
python3 -m pytest tests/yt_dub -q                       # 7 green
scripts/ops/yt-diarize-remote.sh mn01:media-corpus/yt-dub-prep/<VID>.mp4
yt-vtt-dub.py VID.mp4 VID.en.th.vtt out.mp4 --sentences --en-vtt VID.en.vtt \
    --diarize-file VID.diarize.txt --anchors "Host=...;Guest=..." \
    --names-map names.json --dump-turns turns.json
```
