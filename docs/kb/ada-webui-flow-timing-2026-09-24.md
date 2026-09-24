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

## Network hop timing (each leg measured)

```
tony-omen ──7ms──▶ idc01 ──<1ms──▶ mddb / proxy / ollama / surreal
    │              │
    │              ├──32ms tcp / 99ms ttfb──▶ generativelanguage.googleapis.com
    │              ├──165ms ttfb──▶ googleapis (calendar)
    │              ├──7ms──▶ tony-dell (tony-ha API ttfb 32ms)
    │              ├──7ms──▶ mn01
    │              └──7ms──▶ michael-ha (API ttfb 248ms)
```

| Hop | Connect | TTFB | Notes |
|---|---|---|---|
| tony-omen → idc01 tailnet | 7ms RTT (direct, not relayed) | 41ms | WireGuard direct via 157.85.110.99 |
| tony-omen → idc01 sslip.io | — | 153ms | +110ms vs tailnet: slower dns+TLS |
| idc01 → uvicorn :8001 | 0.2ms | <1ms | loopback |
| idc01 → mddb :11023 | 0.2ms | 1ms | same host |
| mddb → embed proxy :11435 | 0.2ms | 1ms | same host |
| proxy → ollama :11434 | — | 3ms | same host |
| idc01 → open-notebook :5055 | 0.3ms | 4ms | same host |
| idc01 → generativelanguage | 32ms tcp / 64ms TLS | 99ms | ws handshake ≠ this — Live session init is ~5s server-side |
| idc01 → googleapis (calendar) | 30ms tcp | 165ms | agenda prefetch hop |
| idc01 → tony-dell / mn01 / michael-ha | ~7ms each | 32–248ms | all direct tailnet, VPS is region-local |

**Takeaway:** no network hop explains latency except Gemini. The whole
internal path (mddb + embed + tools) is <5ms; every tailnet leg is ~7ms.
The ~5s `ws→ready` is Gemini Live session setup server-side, not transit.

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
