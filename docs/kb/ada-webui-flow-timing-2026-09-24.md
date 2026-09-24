# Ada WebUI flow timing — 2026-09-24

Measured end-to-end on `ada-pi-pwa` (idc01), build `a598560`, with
`scripts/ada/webui-timing.py` — a probe that walks the same stages as the
browser: page → auth → ws → ready → primed greeting → first answer.

## Results

| Stage | Loopback (:8001) | Tailnet (wss, tony-omen) |
|---|---|---|
| `GET /` HTML shell | 0.03s | 0.05s |
| JS bundle | ~0s | 0.04s |
| `POST /api/auth/session` | ~0s | 0.04s |
| ws connect → `ready` | 4.97s | 4.87s |
| `ready` → greeting first token | 1.94s | 1.09s |
| `ready` → greeting complete | 17.45s | 8.15s |
| question → first token | 1.23s | 1.21s |
| question → `response_completed` | 8.93s | 8.15s |

## Where the time goes

1. **~5s — Gemini Live handshake** (`ws_connect → ready`). The biggest
   fixed cost of opening the UI; unavoidable cloud round-trip per socket.
   Note `ready` is sent immediately after the provider connects
   (`001e0f0`) — session priming no longer gates it.
2. **Greeting ~8–17s** — the primed greeting is a real model turn that
   can include tool calls (agenda prefetch → Google Calendar API,
   `devin_status`, memory searches). Variance is content-dependent.
3. **Answers: ~1.2s to first token, ~8–9s complete.** Model-bound;
   memory tools themselves cost ~1s (see latency-probe results).
4. **Tailnet + TLS ≈ +50ms total** — remote access is not a factor.

## Perceived-latency summary

- Open → interactive: **~5s** (ws handshake; page+auth are ~0)
- Open → greeting starts: **~6–7s**
- Question → first audio/text: **~1.2s** (the metric users feel)
- Question → turn done: **~9s** typical, up to ~30s with tools

## Bug found during measurement (fixed before this report)

The provider stream was crash-looping every ~3min:
`'GeminiLiveProvider' object has no attribute 'usage_input_tokens'` —
`__init__` had been split by a mid-init method insertion, so usage attrs
only existed inside `_note_search_result`. Each crash dropped the ws
stream, reconnected (`resumed=False`), and replayed the primed greeting —
sessions never completed their greeting turn. Fix `a598560` restored the
attrs to `__init__`; redeployed to idc01 + mn01 (services verified active).

Watch: `journalctl --user -u ada-pi-pwa | grep "stream ended"` should
show no `AttributeError` repeats.

## Harness

`scripts/ada/webui-timing.py <base-url> <api-key>` — prints the stage
table. Runs on idc01 loopback (`http://127.0.0.1:8001`) or any tailnet
host against `https://idc01.taila0626a.ts.net`.
