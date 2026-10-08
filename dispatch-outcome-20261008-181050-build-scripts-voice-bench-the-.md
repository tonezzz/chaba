# dispatch outcome: voice-bench harness (2026-10-08)

## What changed

Built `scripts/voice-bench/` — the shared benchmark harness for
voice-fallback combo cards (research base:
`docs/kb/voice-fallback-options.md`):

- `combos.yml` — declarative combos `{id, stt, llm, tts, orchestrator,
  host_labels, runtime, endpoint, notes}`. 4 entries seeded:
  openai-realtime-hosted, hf-s2s-vllm-local (`[gpu]`), a CPU pipeline
  sketch, and `dry-run-dummy` for harness self-test.
- `fixtures/` — `manifest.yml` with 20 phrases (10 en / 10 th): HA
  commands, tool-call questions, chit-chat; each carries
  `expected_transcript` + `expected_tool_call`. 20 wavs committed —
  **tone-synthesized placeholders** (no TTS key on this host);
  `fixtures/generate.py --engine gemini|azure` re-synthesizes real
  speech once a key is available.
- `bench.py --combo <id> [--dry-run]` — stack lifecycle via
  `runtime.kind` (podman | local | none), streams each fixture,
  measures ttfa_ms / total_ms / WER (word-level en, char-level th) /
  tool-call match (exact/partial/none). Writes
  `results/<combo>-<ts>.json` (schema `voice-bench-result` v1).
  Transport contract: `POST <endpoint>/bench` wav → JSON
  `{transcript, tool_call, first_audio_ms}`.
- `report.py [--card <id>]` — renders `reports/voice-fallback/LATEST.md`
  (newest run per combo), appends `trend.md` rows, optional board-api
  comment. Empty-results case renders a clean empty table.
- `lib.py` — loader/validation, WER, scoring, result schema.
- Docs: `scripts/voice-bench/README.md` + job trail
  `docs/ssot/jobs/voice/2026-10-08-voice-bench-harness.yml` (includes the
  action.type=script runner card snippet).

Committed on session branch `dispatch/20261008-181050-...` (658742e8),
not pushed. Board comment posted to `voice-bench-harness`.

## Verified

- `bench.py --combo dry-run-dummy --dry-run` → full 20-fixture JSON schema.
- `bench.py --combo hf-s2s-vllm-local --dry-run` → same (labelled combo).
- `bench.py --combo dry-run-dummy` (real run, no endpoint) → clean
  skipped-status results, no crash.
- `report.py` → `reports/voice-fallback/LATEST.md` empty table, no error
  (reports/ is gitignored — generated output).
- Unit-checked wer()/tool_call_match() incl. Thai char-level WER.

## Caveats / next

- Fixture audio is placeholder tones, not speech — WER is meaningless
  until `generate.py --engine gemini|azure` runs with a real key.
- Combos themselves are NOT implemented (per card scope); a real combo
  needs its stack + a `/bench` adapter + a combos.yml entry.
