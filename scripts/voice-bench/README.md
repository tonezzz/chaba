# voice-bench — voice-fallback combo harness

Benchmark harness for Gemini Live fallback stacks (research base:
`docs/kb/voice-fallback-options.md`). Every combo card registers one
entry in `combos.yml`; the harness owns fixtures, lifecycle, timing, and
scoring — combos own their orchestrator's wire protocol.

## Layout

- `combos.yml` — declarative combos: `{id, stt, llm, tts, orchestrator,
  host_labels, runtime, endpoint, notes}`. GPU combos set
  `host_labels: [gpu]` so only gpu-labelled runners claim their cards.
- `fixtures/manifest.yml` — 20 phrases (10 en / 10 th): HA commands,
  tool-call questions, chit-chat. Per fixture: `<id>.wav` +
  `expected_transcript` + `expected_tool_call`.
- `fixtures/generate.py` — synthesizes wavs via `--engine gemini|azure`
  (env keys `GEMINI_API_KEY` / `AZURE_SPEECH_KEY`+`AZURE_SPEECH_REGION`),
  or `--engine tone` for offline placeholder audio (not speech — WER
  numbers are meaningless until a real engine is run).
- `bench.py --combo <id>` — brings the stack up (`runtime.kind`:
  podman | local | none), streams each fixture, measures ttfa_ms /
  total_ms / WER / tool-call match, writes `results/<combo>-<ts>.json`.
- `report.py [--card <id>]` — renders `reports/voice-fallback/LATEST.md`
  (combo x metric), appends `trend.md` rows, optionally posts a summary
  comment to a kanban card via board-api.

## Transport contract

The orchestrator under test should accept `POST <endpoint>/bench` with a
wav body and reply JSON `{transcript, tool_call, first_audio_ms}`.
Combos with a different protocol (e.g. OpenAI Realtime events) supply
their own adapter — see `bench.py:run_fixture`.

## Runner card (action.type=script)

```yaml
action:
  type: script
  labels: [gpu]            # only for gpu combos
  script:
    repo: chaba
    cmd: >-
      python3 scripts/voice-bench/bench.py --combo <id> &&
      python3 scripts/voice-bench/report.py --card <card-id>
```

## Smoke

```
python3 scripts/voice-bench/bench.py --combo dry-run-dummy --dry-run
python3 scripts/voice-bench/report.py
```

Dry-run exercises the full result schema (status `dry_run` per fixture)
with no services up.
