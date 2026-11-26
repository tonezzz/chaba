# Dispatch outcome — ada-engine-contract-suite (ADA-0154)

Card: `ada-engine-contract-suite` — from ai-engine-lines
(`ssot.apps.ada-engines.yml` contract_v1): no named conformance pack
existed. Task: tag a subset of ada-voice `tests/scenarios-live` as
contract — ws auth + caller-key tier refusal, tool_call/tool_result
trace events, `[persona->sender]` tagged reply, `/api/health`, loud
failure on undeclared capability. The suite is the gate before any
engine (ada-2, chaba-ops, edge) may bind a live lane.

## What changed (ada-voice repo)

All work in dedicated worktree
`~/CascadeProjects/ada-voice-wt-engine-contract`, branch
`dispatch/engine-contract-suite` off `origin/main` (678b960), commit
`a3807da` — **not pushed** (dispatch rails; merge/push is the
operator's close-out step).

### The pack — `contract: true` tag + `--tier contract` selection

`contract:` is an orthogonal boolean tag, not a tier — scheduling tier
(smoke/full/gate) and conformance membership are different axes.
`scenario-report.py --tier contract` selects only tagged files
regardless of their `tier:`; `scenario-schema-check.py` validates the
field is a real boolean. Six scenarios carry the tag:

| scenario | contract_v1 item | asserts |
|---|---|---|
| `contract_health` | `/api/health` | 200 + `"ok"`; `/api/auth/status` `auth_configured:true` (caller keys are contract, not optional) |
| `contract_ws_auth` | ws auth | `ws_auth` turns: bogus key → reject pre-`ready`, no key → reject, lane key → `ready` (control proves refusals are auth-caused) |
| `contract_tool_surface` | loud failure on undeclared capability | `/api/tools` authed 200 + `"tools"` list; unauthed → 401; `POST /api/tools/call` bogus tool → `status:"error"` + `Unknown tool` |
| `contract_tool_trace` | tool_call/tool_result trace events | `min_calls: 1` + `min_results: 1` — both event types on the ws, tool-agnostic; deliberately NO `needs_any` gate so a tool-less engine FAILS rather than exiting UNIMPLEMENTED |
| `contract_session_scope` | per-(channel,room,sender,persona) sessions | `/ws` accepts relay binding params (`?channel=line&chat_id=`) and serves a scoped session |
| `doc_policy_gate` (tagged) | caller-key tier refusal | server-side policy denies scoped caller `user-kk` |

`tests/scenarios-live/CONTRACT.md` is the pack index: coverage map,
run instructions, and caveats (doc_policy_gate's `user-kk` fixture is
lane-conditional — absent key records `skip`; the literal
`[persona->sender]` reply tag is relay-side formatting asserted by
`tests/test_line_relay_group.py`, while the engine half — accepting
binding params — is what contract_session_scope checks).

### Driver extensions (`scripts/scenario-live.py`)

- `ws_auth:` turn type — raw `/ws` connect with its own credentials,
  asserts `expect_reject`/`expect_ready` on the handshake outcome
  (ready / rejected / closed:<code> / timeout). Asserts the OUTCOME
  (no `ready`), not wire close-code — pre-accept closes surface to
  clients as HTTP handshake rejections. 60s ready-wait budget matches
  cold Gemini Live connect patience.
- `http_check:` — `status` accepts int or list; `headers`/`method`/
  `body` enable authed GETs and POST probes; 4xx/5xx are asserted
  not raised (HTTPError returns status+body).
- `min_calls:`/`min_results:` expect keys — trace-event floors.
- `{http_base}`/`{api_key}` runtime tokens inside turn specs — probes
  follow whatever `--url`/`--api-key` the run targets; no lane-specific
  URLs or secrets in yaml.
- `scenario-report.py` — `--tier contract` argparse choice +
  contract-flag selection.

## Verification

- `pytest tests/ -x -q` (full suite, worktree venv): **1983 passed,
  7 skipped** — includes 3 new harness tests (min_calls/min_results,
  http_check status-list/POST/401-assert, `_ws_auth_turn` vs live
  local websockets servers). 10/10 in `test_scenario_live_harness.py`.
- `scenario-schema-check.py`: 216 files, 0 violations.
- `scenario-report.py --tier contract`: selects exactly the 6 tagged
  scenarios (live run locally hits INFRA — no backend on this host,
  expected).
- `tool-lint.py`: clean.
- Server behavior cross-checked against `pwa_server.py`: `/api/health`
  returns `"ok":true`; `/api/auth/status` returns `auth_configured`/
  `authenticated`; `/api/tools/call` unknown tool → HTTP 200
  `{"status":"error","error":"Unknown tool: …"}`; unauthed `/api/tools`
  → 401 via `_require_api_key`.

## Caveats / follow-ups

- Live verification pending: run `--tier contract` against a real lane
  (e.g. `ws://127.0.0.1:8002/ws` on idc03) post-merge — recorded in the
  job trail `docs/ssot/jobs/ada/2026-11-25-engine-contract-suite.yml`.
- Contract scenarios carry `tier: smoke` — they also run inside the
  normal hourly smoke tier (intentional: the contract is a strict
  subset; CONTRACT.md documents this).
- Sibling card `ada-engine-self-report` adds engine identity to
  `/api/health`; `contract_health` can be extended to assert
  `engine_line`/`contract_version` once that lands.
- `contract_tool_trace`/`contract_session_scope` make real model calls
  — they share the live-suite flake profile (auto-retry → `flaky`).

lessons:
- ada-voice dispatch worktrees need backend light-deps installed for the full pytest gate (numpy, pillow<13, qrcode, fastapi, uvicorn, google-genai); torch/speechbrain/faster-whisper/soundfile/av stay skippable per KNOWN_PITFALLS.
- scenario-live.py ws connect waits up to 120s for cold Gemini Live 'ready' — auth probes asserting pre-ready rejection must not copy a short recv timeout or they false-fail slow providers.
- FastAPI/uvicorn emit compact JSON separators — http_check test mocks must match `("status":"error")` not `("status": "error")` or contains-asserts diverge from production.
- `/api/tools/call` returns HTTP 200 with `status:"error"` for unknown tools — loud-failure contract probes assert the body, not the status code.
