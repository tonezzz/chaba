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
Combos with a different protocol declare `adapter: <name>` in combos.yml
and the matching callable in `adapters.py` owns the exchange. Available:
`openai_realtime` (OpenAI Realtime ws events — used by `hf-s2s`).

## hf-s2s combo (ran 2026-10-09 on tony-omen)

- Launcher: `hf-s2s-serve.sh` — `speech-to-speech serve` with
  faster-whisper small (multilingual) on CPU, ollama chat-completions
  (`S2S_LLM_BASE_URL`, `S2S_LLM_MODEL`, default `qwen2.5:1.5b`), qwen3-tts
  ggml `Q4_K_M`. Needs a venv with `speech-to-speech[faster-whisper]` —
  see `docs/ssot/jobs/voice/2026-10-09-hf-s2s-bench.yml` for the env
  recipe (`uv venv .venv-s2s --python 3.12`, cu12 nvidia libs for
  qwentts-cpp, `CUDA_VISIBLE_DEVICES=""` on the 4GB 1650).
- Fixture wavs are real edge-tts speech (`generate.py --engine edge`,
  no key needed).
- Single-session server: bench.py sleeps 12s between adapter fixtures and
  the adapter retries connects for ~40s (slot drains ~10s post-close).

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
