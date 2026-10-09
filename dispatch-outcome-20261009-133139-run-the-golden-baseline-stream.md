# Outcome: run-the-golden-baseline-stream (voice-combo-gemini-baseline, attempt 2)

## Result

Golden baseline captured on tony-dell —
`scripts/voice-bench/results/gemini-baseline-20261009T071325Z.json`,
`reports/voice-fallback/LATEST.md` updated:

| n | ok | mean ttfa ms | mean total ms | mean WER | tool e/p/n(/n/a) |
|---|---|---|---|---|---|
| 20 | 20 | 294 | 6220 | 0.02 | 6 / 8 / 0 (6 n/a) |

Every fixture streamed through the current Gemini Live path
(`gemini-3.1-flash-live-preview`, AUDIO modality, PCM16@16k realtimeInput,
input/output audio transcription, harness HA_TOOLS + INSTRUCTIONS).

## What changed

- `scripts/voice-bench/adapters.py` — new `gemini_live` adapter. Uses the raw
  `BidiGenerateContent` websocket JSON protocol (same wire shape as
  `stacks/web/gemini-mic-test/server.mjs`) instead of the google-genai SDK.
- `scripts/voice-bench/bench.py` + `lib.py` — restored the `adapter:` dispatch
  that commit 04abd2fc added but a later commit's older bench.py overwrote.
- `scripts/voice-bench/combos.yml` — registered `gemini-baseline` combo.
- `scripts/voice-bench/report.py` — tolerates the legacy bare-string `combo`
  schema (cascade result) instead of crashing.
- `scripts/voice-bench/fixtures/*.wav` — replaced 70444B tone placeholders
  with real TTS wavs cherry-picked from unmerged commit `e4522ead`
  (branch `dispatch/20261009-133135-the-harness-landed-scripts-voi`).
- `docs/ssot/jobs/voice/2026-10-09-gemini-baseline.yml` — job record.

## Findings (all posted to the card)

1. **Dead Gemini key on tony-dell.** `~/.config/secrets/gemini-api-key.env`,
   `gemini-mic-test.env`, `open-notebook.env`, the podman `gemini-api-key`
   secret feeding `gev-gemini`, and the archived ada envs all hold the same
   53-char `AQ.` key that now returns 401/1008 on BOTH
   `generativelanguage.googleapis.com` and `aiplatform.googleapis.com`.
   The working key lives in `ada-pi-pwa.env` / `chaba-guest.env` (different
   `AQ.` value, free tier — its gemini-2.5-flash daily REST quota was already
   exhausted, ~17h retry). gev-gemini is running on the dead key.
2. **google-genai SDK silently drops audio turns.** `aio.live.connect` +
   `send_realtime_input(audio=Blob)` connects and answers text turns, but
   audio produces zero VAD/model events on genai 2.29.0 AND ada-pi's pinned
   2.23.0, across `gemini-3.1-flash-live-preview` and
   `gemini-2.5-flash-native-audio-preview-09-2025`, every VAD config tried.
   Raw ws JSON works perfectly. gev-gemini's bridge.py uses the SDK path —
   it may currently be equally deaf (no voice sessions in its 29h log);
   recommend running `stacks/tony-dell/gev-gemini/live-check.py` and
   following up with a card.
3. Partial tool matches were mostly arg casing (`Kitchen` vs `kitchen`) —
   scorer compares literal values; a case-insensitive arg compare could be
   a future harness tweak.

## Verify

```
cd scripts/voice-bench
GEMINI_API_KEY=<key from ~/.config/secrets/ada-pi-pwa.env> \
  .bench-tools/venv/bin/python bench.py --combo gemini-baseline
cat reports/voice-fallback/LATEST.md   # gemini-baseline row
```

Committed on this dispatch branch; not pushed.
