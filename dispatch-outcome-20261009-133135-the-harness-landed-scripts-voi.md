# voice-bench-real-fixtures — outcome

## What happened
- All 20 manifest fixture wavs were 70444-byte `tone` placeholders. Regenerated with real neural TTS.
- `--engine gemini` failed: every Gemini key on tony-dell (`gemini-api-key.env`, `gemini-mic-test.env`, `ada-pi-pwa.env`, `chaba-guest.env`, `open-notebook.env`) is either a dead `AQ.Ab8`-style token (401) or quota-exhausted — free-tier `generate_content_free_tier_requests` = 10/day per TTS model; reset ~17h. One fixture (`en-cmd-light-kitchen.wav`, 37296 samples) did land via Gemini before the quota hit.
- Added a new `--engine edge` to `scripts/voice-bench/fixtures/generate.py` (edge-tts package → mp3 → ffmpeg → 16 kHz mono PCM; voices `en-US-JennyNeural` / `th-TH-PremwadeeNeural`). Remaining 19 fixtures generated with it. Also added 429/5xx retry-with-backoff to the Gemini path and a throttle delay between non-tone requests.
- Regeneration used a throwaway venv at `/tmp/vbtts-venv` (edge-tts, gtts, faster-whisper) — not part of the repo.

## Verification
- File sizes: 32 unique sizes across the 35 wavs; every manifest fixture is a distinct size (no tone placeholders remain; `tone-sized: []`).
- Durations ~2.0–2.6 s, matching phrase lengths.
- STT spot-check with faster-whisper `small` (local, CPU):
  - `en-chat-hello.wav` → "Hey, how are you doing today?" (expected: hey how are you doing today)
  - `th-chat-thanks.wav` → "ขอบคุณมากครับ" (expected: ขอบคุณมากครับ) — actual Thai speech.

## Committed
- Commit `e4522ead` on branch `dispatch/20261009-133135-the-harness-landed-scripts-voi`: 20 wavs + `generate.py`.

## Notes / follow-ups
- Mixed provenance: 1 Gemini + 19 edge fixtures. If engine uniformity matters, re-run `--engine gemini --force` after quota resets (~17h from 2026-10-09 ~14:00 UTC+7) — the retry/backoff and skip-if-exists make it safe.
- The non-manifest legacy wavs (`en-cmd-01.wav` etc.) were already real TTS from a prior manifest and were left untouched.
- Gemini keys in `~/.config/secrets/gemini-api-key.env` and `gemini-mic-test.env` look like expired short-lived tokens (401) — worth rotating; `ada-pi-pwa.env`/`chaba-guest.env` keys work but share an exhausted quota project.
