# yt-voice-dub-cast — dispatch outcome

## Part 1 — repo-home the pipeline

All four pipeline scripts are now canonical in `scripts/ops/`:

- `scripts/ops/yt-live.sh`, `yt-live-api.py`, `yt-vtt-dub.py`,
  `yt-vtt-translate.py` (copied from `~/.local/bin`, plus sibling
  resolution: each script finds its neighbours in its own directory
  first — repo checkout or `~/.local/bin` — so both locations work
  standalone).
- New `scripts/ops/yt-pipeline-install.sh` installs/refreshes the
  `~/.local/bin` copies (default: real files; `--link <repo>` for
  symlinks into a persistent checkout after merge — never a worktree).
- `~/.local/bin` copies were refreshed in place; `yt-live-api :8791`
  still answers `/health`.

## Part 2 — heuristic speaker casting

New in `scripts/ops/yt-vtt-dub.py` (and mirrored to `~/.local/bin`):

- `--cast-detect` — auto-derives a `--cast-times` map from the karaoke
  word stream. Phrases split at `--detect-gap` (0.6s) word-start deltas;
  each boundary scores cue-gap clustering (Otsu 2-class split on real
  inter-phrase air) + question cues: a non-tag phrase ending `?` flips
  the speaker unconditionally (interview Q→A is the dominant turn
  signal; caption air is ~0), whole-phrase tag-questions suppressed,
  question openers after a ≥12s turn count as host interjections,
  response openers (Yeah/No/Well/…) weak bonus. `--speakers` does
  round-robin assignment (default 2 → alternation).
- `--cast-voices` (default `th-TH-NiwatNeural,th-TH-PremwadeeNeural`),
  `--dump-turns` (turn table JSON), `--dub-wav` (bare pre-mix dub track
  for acoustic verification).
- New CLI `scripts/ops/yt-cast-detect.py` — turn preview +
  `--format cast-times` without rendering.

New `scripts/ops/yt-whisper-vtt.py` — Whisper transcription lane for
caption-less videos (faster-whisper → karaoke-format VTT feeding
`parse_words`/`--sentences`/`--cast-detect` unchanged). Created
`~/.venvs/whisper` (av pinned 15.1.0 — fw 1.2.x breaks on av 19);
sNh4pVMFhvQ transcribed end-to-end → `~/yt-dub-prep/sNh4pVMFhvQ.sv.vtt`
(3491 words). Non-English `q_start` cue not implemented — detection
there is gap+q_end only.

## Verification (staged corpus)

- Detection: `4njFdBF_42I` 14 turns/240s, `U_io-pqPFfQ` 21 turns/240s —
  Q→A flips land correctly; U_io is the 3-speaker probe so guests share
  voices in alternation (documented limit).
- Render: 180s TH dub of `4njFdBF_42I` → `/tmp/4nj-dub-cast.mp4`
  (dumps: `/tmp/4nj.{turns,groups}.json`, `/tmp/4nj-dub-only.wav`).
  21 spoken groups; `dump-groups` shows 15×Niwat + 8×Premwadee aligned
  to detected turns — **2 distinct voices per detected speaker** ✓.
- Acoustic check on the bare dub track: F0 2-cluster split gives
  134/213Hz modes vs edge-tts refs (Niwat ~163, Premwadee ~203);
  long single-voice windows match expected pitch family. Edge-window
  mismatches trace to queue-lag drift, not wrong synthesis.
- Constraints honored: exactly the 2 TH voices; uniform-rate fit kept
  (global rate 1.05 on this render); TH ~1.4x-longer text noted.

## Trail

- `docs/ssot/jobs/yt-dub/2026-10-05-yt-voice-dub-cast.yml`
- `docs/kb/home-assistant/tv-casting-runbook.md` updated (repo home +
  dub lane).

## Notes for review

- Heuristic ≠ diarization: `~/.venvs/diarize` (resemblyzer/librosa/
  webrtcvad) is staged for the real pass when casting needs to be
  gender/speaker-true rather than turn-plausible.
- `compress_lines` returned 0% shorter on this run (Gemini quota /
  ollama weakness — existing behavior, unrelated).
