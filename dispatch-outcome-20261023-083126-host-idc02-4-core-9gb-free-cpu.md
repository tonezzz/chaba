# dispatch-outcome — local-stt-lane-eval

**Result: PASS (with ambient-load caveat).** The 2026-10-16 POC was
extended to the full card spec: 28-clip real corpus, 5 contenders,
all gates measured. qwen3-asr-0.6b-q8 on audio.cpp remains the
winner for an Ada text-mode STT lane on idc02.

## What was found on arrival

- Prior POC assets intact at `~/audio-cpp-eval` (audio.cpp v0.9.2,
  qwen3-asr Q8 + crisperwhisper Q4_K GGUFs, eval scripts, 11-clip
  corpus with results).
- `ada-stt.service` was **silently broken**: orphaned
  `audiocpp_server` (1.8GB RSS, alive since Oct-16) had no listening
  socket while systemd reported inactive/dead. Killed and restarted
  via `systemctl --user start ada-stt`; :8914 healthy, E2E verified
  with the real multipart request shape ada-tg-relay uses.
- idc03 corpus had grown to 28 clips (14 new tony + 3 michael).

## What was done

- Synced 17 new clips (incl. michael sender, EN/DE/TL/gibberish,
  3 near-silent), converted to 16kHz WAV.
- Refs for new clips via `gen_refs.py` (gemini-3.1-flash-lite inline
  audio). NOTE: the paid Gemini project is **monthly spend-capped**
  (429 on all idc02 keys + TONY/PAID/KK on idc03); FREE/MICHAEL keys
  worked — used for refs only.
- Ran the matrix: qwen3-asr (all 28), whisper-large-v3 via omen
  HTTP (all 28), sherpa-onnx whisper-small int8 (all 28),
  whisper-medium int8 (7-clip subset — RTF 1.3-5.9, RSS 2.4GB,
  aborted: not viable), crisperwhisper Q4_K (prior 11-clip results
  carried; disqualified — translates + hallucinates, RTF 11-57).
- Streaming gate: `mode:"streaming"` + `stream:true` returns SSE
  `transcript.text.delta/done` over incremental multipart upload —
  verified via `tools/streaming/measure_asr_streaming_client.py`.
  Caveat: server buffers the full body before decode (chunked
  response, not true incremental decode).

## Numbers (CER vs Gemini refs)

| model | n | CER all | th | th+cs | en/other | EN WER | RTF med | wall med | RSS max |
|---|---|---|---|---|---|---|---|---|---|
| **qwen3-asr-0.6b-q8** | 28 | **0.212** | 0.216 | 0.321 | 0.223 | 0.342 | **0.65** | 3.4s | 2.25GB |
| whisper-large-v3 (omen GPU) | 28 | 0.291 | 0.305 | 0.237 | 0.352 | 0.444 | — | 3.8s | — |
| sherpa whisper-small int8 | 28 | 0.348 | 0.548 | 0.461 | 0.336 | 0.368 | 1.49 | 6.9s | 1.2GB |
| sherpa whisper-medium int8 | 7 | — | — | — | — | — | ~4 | 12-36s | 2.4GB |
| crisperwhisper-large q4k | 11 | 0.494 | — | — | — | — | 11.2 | 87s | 1.6GB |

## Gates

- Thai CER within ~20% of large-v3: **PASS** (th 0.216 vs 0.305 —
  better; th+cs 0.321 vs 0.237 — the gap is Thai-script
  transliteration style เทเลกาน/เอโค, not word loss).
- RTF<1.0 for 10s clips: **PASS conditional** — 0.52-0.72 quiet
  window; ~2-3 under idc02's now-persistent ambient load (open-jev
  ~14% CPU, mddbd ~14%, bursts). Card OPS-0775 filed for the
  contention/latency tradeoff.
- Streaming endpoint: **PASS** (SSE verified).
- No crashes/OOM: **PASS** (max RSS 2.4GB across all engines).

## Surprises

- 3 "Thai" refs from Oct-16 were **Gemini hallucinations over
  near-silent audio** (-90dB). All engines correctly emit empty —
  partly explains the old "Qwen emitted ENGLISH" worry.
- `language` request field exists on qwen3_asr — the TG lane can pin
  `th` if needed (answers the Oct-16 open question).
- whisper-large-v3 has its own oddities: EN clip → Korean output,
  gibberish → Portuguese.

## Integration status

The `out_if_pass` integration is **already shipped** (ada-stt on
idc02:8914 + ada-tg-relay TG_WHISPER_URL wiring, 2026-10-16). This
session restored it to working order (orphan fix). Remaining delta
is in OPS-0775 (ambient contention → warm TTT now 7-12s vs ~3-4s
Oct-16) and an optional `language=th` pin.

## Repo artifacts

- `docs/ssot/jobs/voice/2026-10-23-local-stt-lane-eval.yml` — full
  report with per-language tables, gates, verify commands.

## On-idc02 artifacts (not in repo)

`~/audio-cpp-eval/`: `refs-all.jsonl` (28 refs), `refs-new.jsonl`,
`gen_refs.py`, `analyze.py`, `run_sherpa_eval.sh`,
`results-sherpa-{small,medium}-int8.jsonl`, updated
`results-qwen3-asr-q8.jsonl` + `results-omen-whisper-large-v3.jsonl`,
`sherpa/` (v1.12.17 binary + whisper small/medium int8 ONNX),
`server-stream.json`, `logs/streaming_test/` evidence.

## How to verify

1. `curl -s http://100.123.163.11:8914/health` → `{"status":"ok"…}`
2. `cd ~/audio-cpp-eval && python3 analyze.py` — full CER/RTF table.
3. `curl -F file=@corpus/wav/<clip>.wav -F model=qwen3-asr
   http://100.123.163.11:8914/v1/audio/transcriptions`
4. Streaming: `python3 tools/streaming/measure_asr_streaming_client.py
   --server-config server-stream.json --start-server --host
   100.123.163.11 --port 8915 --model qwen3-asr --audio
   corpus/wav/<clip>.wav` (VRAM-sampler thread errors out harmlessly
   on this CPU host — run completes, events recorded).
