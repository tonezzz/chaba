# dispatch-outcome: mddb-circuit-open-page

Card: `mddb-circuit-open-page` (MEM-0046) — runner mn01, branch
`dispatch/20261112-072259-all-same-space-providers-down-`,
commit `3f2439f3b8`.

## What changed

Moved embed-outage paging from the 15-min probe tick to failure time, in
the component that knows first — `gemini-ollama-proxy`:

- `scripts/mddb/gemini-ollama-proxy.mjs` — new `emitOpsEvent()`: a
  fire-and-forget POST to `{MDDB_OPS_URL}/v1/add` writing the same
  `kind=ops-event` doc shape `embed-probe.py` uses
  (`session_id=gemini-ollama-proxy`). Emits `embed_circuit_open` when the
  OR or Gemini circuit trips closed→open, `embed_providers_down` after
  `EMBED_FAIL_ALERT_AFTER` (3) consecutive failed embed requests — once
  per episode, re-armed by `embed_provider_restored` on the first success
  after an alerted episode. `OPS_ALERT_MIN_MS` (15min) rate-limits repeat
  emits per type; a 4s abort + catch means alerting can never delay or
  fail an embed response. `/health` gains `embed.consecutive_failures /
  failures_total / ok_total / last_error`.
- `scripts/ada/embed-probe.py` — `check_provider_health()` treats
  `health.embed.consecutive_failures >= EMBED_PROXY_FAIL_ALERT` (3) as
  degraded: backstop so the probe still pages on its next tick if the
  proxy's own emit couldn't reach the ops collection.
- `scripts/ops-digest.py` — `FLAGGED` gains `embed_outage`,
  `embed_providers_down`, `embed_circuit_open`.
- Docs: `docs/kb/mddb-embedding-providers.md` (env vars, event types,
  deploy step), `ssot.services.yml` gemini-ollama-proxy env note,
  trail `docs/ssot/jobs/infrastructure/2026-11-12-mddb-embed-circuit-open-page.yml`.

## Result / verify

Local simulation on mn01 with stub OR upstream + stub ops receiver:
OR 401 → `embed_circuit_open` emitted on request **1** (a cap-hit now
pages at ~minute 0, not ~30); requests 2–4 502'd with
"all same-space providers down (OR circuit-open + Gemini failed)" →
`embed_providers_down` at request 3, no repeat emits; stub flipped to
200 → `embed_provider_restored` and `consecutive_failures` reset to 0.
`node --check` + `py_compile` clean; pre-commit/SSOT gates passed.

## Deploy needed (not done — dispatch mode)

The repo file is source of truth but the live proxy is a manual copy:
`cp scripts/mddb/gemini-ollama-proxy.mjs` →
`idc03:~/.config/containers/mddb/proxy/` then
`systemctl --user restart gemini-ollama-proxy` (same for idc01 standby).
The probe change ships via `chaba-repo-sync.timer`; no unit changes
needed. Until the proxy copy lands, detection stays at probe cadence.
