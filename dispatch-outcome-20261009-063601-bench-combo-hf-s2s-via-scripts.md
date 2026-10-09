# dispatch outcome — bench combo hf-s2s

## What happened

The `voice-bench-harness` merge-sweep salvaged the card but not the code —
`scripts/voice-bench/` never reached master (idc03 checkpoint failed on git
identity). I recovered it from the idc03 worktree via scp, then extended it:

- `adapters.py` — new `adapter:` hook in combos.yml; `openai_realtime`
  adapter (~140 lines) streams a fixture wav over the OpenAI Realtime event
  set, captures transcript / first-audio latency / tool call / event surface.
- `bench.py` — ws:// readiness probe (TCP connect loop), 12s inter-fixture
  settle for single-session orchestrators.
- `fixtures/generate.py` — new `edge` engine (edge-tts, no key); all 20 wavs
  regenerated as real speech (they were tone placeholders).
- `hf-s2s-serve.sh` — launcher for `speech-to-speech serve` (faster-whisper
  small CPU + ollama chat-completions + qwen3-tts ggml Q4_K_M).
- `combos.yml` — registered combo `hf-s2s` (labels: gpu, adapter:
  openai_realtime).

## Stack actually run (tony-omen, GTX1650 4GB)

- STT: faster-whisper `small`, multilingual, language=auto — CPU int8
  (GPU too full: ollama llama-server holds ~2.2GB)
- LLM: ollama `qwen2.5:1.5b` via http://100.75.102.88:11434/v1
  (pulled qwen3:0.6b and qwen2.5:1.5b to ollama during setup)
- TTS: repo default qwen3-tts 1.7B CustomVoice, ggml, Q4_K_M — CPU
  (BF16 and Q4 both OOM'd on GPU; qwentts-cpp needs cu12 pip libs +
  LD_LIBRARY_PATH, handled in the launcher)
- VAD: silero + smart-turn-v3.2

## Results — results/hf-s2s-20261009T012606Z.json (merged best-of-3 runs)

- 20/20 fixtures ok. Mean ttfa 75.8s, mean round-trip 132.6s (CPU TTS is
  the bottleneck: RTF ~0.02–0.17). STT ~9–13s/turn CPU.
- WER: English 0.00 on all 10; Thai mean ~0.21 — whisper-small weak on Thai
  (worst: "ปิดแอร์ห้องนอน" → detected as Hindi, WER 1.0).
- Tool calls: 0 exact / 1 partial / 13 none. The native OpenAI
  `function_call_arguments.done` path works (phi3-gguf can't — 400 "does not
  support tools"; qwen2.5:1.5b emits valid calls but only chose to on 1/14).

## Key question — does the OpenAI-Realtime event set adapt cleanly to our
## gemini-protocol client shape?

**Yes, with caveats.** Near-1:1 mapping (session.update~setup,
input_audio_buffer.append~realtimeInput, output_audio.delta~serverContent,
function_call_arguments.done~toolCall, response.done~turnComplete,
server_vad~automatic VAD). Caveats: GA event names (`response.output_audio.*`,
not beta `response.audio.*`); exclusive sessions — pool=1 rejects with close
1008 and holds the slot ~10s after disconnect; tool follow-up is two-step
(function_call_output item + explicit response.create); the LLM endpoint
must support `tools=` natively (or use the transformers backend which
prompt-injects `<code>` blocks).

## Artifacts / verify

- `docs/ssot/jobs/voice/2026-10-09-hf-s2s-bench.yml` — full findings
- `reports/voice-fallback/LATEST.md` + `trend.md` (reports/ is gitignored)
- `scripts/voice-bench/results/hf-s2s-*.json` — raw per-fixture data
- Verify: `python3 scripts/voice-bench/bench.py --combo hf-s2s --dry-run`
  (schema), and with the server up: `hf-s2s-serve.sh` then
  `bench.py --combo hf-s2s --timeout 240`.
- Vendored clone: `experiments/hf-speech-to-speech/` + `.venv-s2s/` — both
  gitignored, local-only.
- Branch: `dispatch/20261009-063601-bench-combo-hf-s2s-via-scripts`, 2
  commits. Server stopped after the run.
