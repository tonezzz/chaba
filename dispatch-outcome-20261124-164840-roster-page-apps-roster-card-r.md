# Dispatch outcome — roster-devin-nest-shims

## What changed

Commit `b91ed5915c` on `dispatch/20261124-164840-roster-page-apps-roster-card-r`:

- **`stacks/services/roster-shim/`** (new service, self-contained install to
  `~/.local/share/roster-shim/` on the target host):
  - `roster-shim.py` — asyncio + `websockets` daemon that terminates the ada
    lane ws contract for agents with no ada-voice lane. Lane = first ws path
    segment (`/<lane>/ws`). Implements `ready`, `history_request` →
    `history` (JSONL journal per lane+chat_id under state dir), `text` →
    `response_started` + streamed `assistant_transcript_delta` +
    `response_completed`, api_key auth with 4401/4403 denial (fail-closed
    unless `ROSTER_SHIM_ALLOW_ANY=1`), 4404 unknown lane, `GET /<lane>/health`.
    Backends: `exec` (argv templates with `{text}`/`{chat_id}`/`{lane}`/
    `{state_dir}`/`{repo}`/`{here}`/`{workspace}`, optional `first:` argv
    until `<workspace>/.started`, stdout streams as deltas, timeout+kill)
    and `http` (POST JSON, reply via `reply_path`).
  - `lanes.yml` — `devin` lane: exec `devin --respect-workspace-trust false
    -p "{text}"` first turn, `-c -p` continuation, per-chat_id workspace;
    `nest` lane: exec `nest-ask.py "{text}"`.
  - `nest-ask.py` — fronts `NEST_ORCHESTRATOR_URL` (POST `{text}` → reply
    text) when set; otherwise litellm `chat-local` with a Nest/orchestrator
    persona (same `~/.config/secrets/mddb-gemini.env` credentials pattern
    as `scripts/ada/litellm_chat.py`, vendored to keep the service
    self-contained).
  - `roster-shim.service`, `install.sh` (venv + websockets/pyyaml +
    systemd --user unit, idc03 default), `verify.sh`, `README.md`.
- **`stacks/web/public/apps/roster/index.html`** — `devin` and `nest`
  contacts are now real lanes
  (`https://idc03.taila0626a.ts.net/apps/roster-shim/{devin,nest}`) instead
  of `soon`.
- **`docs/ssot/infrastructure/ssot.routes.yml`** — `roster-shim` service
  entry (idc03 `127.0.0.1:8796`) + `idc03-serve` mount
  `/apps/roster-shim -> http://127.0.0.1:8796`; `routes.json` regenerated.

## Verification

Ran the shim on idc03 in `/tmp` (throwaway, nothing installed) using the
ada-voice venv's websockets 16.1.1:

- `GET /devin/health`, `/nest/health` → 200 JSON.
- ws with bad key → close **4401**; unknown lane → **4404**.
- ws with good key → `ready` → `history_request` → `history` → `text` →
  `response_started`, `assistant_transcript_delta`, `response_completed`
  — verified for both an `exec` backend (echo) and an `http` backend
  (local POST responder). Turn journal JSONL written and replayed.
- `nest-ask.py` plumbing reaches the litellm gateway (got HTTP 403 from
  idc03's secrets env — credential/model issue on that host, surfaces
  cleanly as a backend error reply; not shim code).
- `roster-shim.py --selftest` passes; `render-routes.py` regenerated
  routes.json (17 pre-existing shadow warnings, none new); SSOT
  pre-commit validation passed.

## Not done (deploy gate — dispatch rules say no deploy unless explicit)

1. `stacks/services/roster-shim/install.sh` on idc03.
2. `tailscale serve --bg --set-path=/apps/roster-shim http://127.0.0.1:8796`
   on idc03 (declared in ssot.routes.yml `idc03-serve.mounts`).
3. `ROSTER_SHIM_KEYS=ada-…,…` in `~/.config/secrets/roster-shim.env`.
4. Seed keys in the roster (Seed box single-key paste per contact, or
   `#key.devin=…&key.nest=…`).
5. Watch the first live `devin -p` turn — flag order
   (`--respect-workspace-trust false -c -p "…"`) is per CLI docs but
   unverified against a real session.

Card comms posted with the same summary.

lessons:
- websockets 16 `WsResponse` needs `Headers(...)`, not a dict — a plain GET health endpoint crashes the handshake otherwise.
- idc03 system python3.12 has PyYAML but NOT the websockets module; ada-voice `.venv` (websockets 16.1.1) is a handy throwaway interpreter for ws verification without installing anything.
- tailscale-serve path mounts strip the mount prefix — one `/apps/roster-shim` mount preserves `/<lane>/ws` for every shim lane; per-lane mounts to the same port would collide on `/ws`.
- "orchestrator chat entry" for nest is not defined anywhere in SSOT/code — nest-ask.py takes NEST_ORCHESTRATOR_URL so the real entry drops in without touching the shim.
