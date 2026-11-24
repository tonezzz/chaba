# roster-shim

Ada-lane ws contract shim for roster contacts that have no ada-voice lane
(card `roster-devin-nest-shims`, follow-up of `roster-agents-tab`).

The Agents roster page fronts every contact with a stock
`ada-webchat-card`, which dials `wss://<lane>/ws?api_key=…&channel=web
&chat_id=web-<member>&mode=text&device_id=…` and speaks
`ready → history → {text} → response_started /
assistant_transcript_delta* / response_completed`. Agents without a lane
(devin CLI, the nest orchestrator) get a shim lane: this daemon
terminates that contract on `127.0.0.1:8796` and forwards each text turn
to a per-lane backend.

## Lanes

Lane = first ws path segment: `/<lane>/ws`. Config: `lanes.yml`.

| lane   | backend | what it fronts                                        |
|--------|---------|--------------------------------------------------------|
| devin  | exec    | `devin -p` CLI session per chat_id workspace; `-c` continues it |
| nest   | exec    | `nest-ask.py` → `NEST_ORCHESTRATOR_URL` if set, else litellm `chat-local` with the Nest persona |

Backend types: `exec` (argv template, `{text}`/`{chat_id}`/`{lane}`/
`{state_dir}`/`{repo}`/`{here}`/`{workspace}` placeholders; `first:` argv
runs until `<workspace>/.started` exists; stdout streams as deltas) and
`http` (POST `{text,chat_id,lane}` JSON, reply via `reply_path`).

## Edge mount

idc03 tailscale-serve (see `docs/ssot/infrastructure/ssot.routes.yml`,
`idc03-serve.mounts`):

    /apps/roster-shim -> http://127.0.0.1:8796

The mount strips `/apps/roster-shim`, so the roster contacts are:

    https://idc03.taila0626a.ts.net/apps/roster-shim/devin
    https://idc03.taila0626a.ts.net/apps/roster-shim/nest

Apply once on idc03 (persisted in the serve config):

    tailscale serve --bg --set-path=/apps/roster-shim http://127.0.0.1:8796

## Keys

api_key auth mirrors the ada lanes: the socket closes 4401 on a bad key
(the roster shows "key denied — re-seed"). Keys are secrets — put them in
`~/.config/secrets/roster-shim.env` on the shim host:

    ROSTER_SHIM_KEYS=ada-<token1>,ada-<token2>

Generate with `openssl rand -hex 16` and prefix `ada-`. Seed into the
roster via the Seed box (single-key paste binds to the selected contact)
or `#key.devin=…&key.nest=…` hash pairs.

## Install / verify

    ./install.sh            # idc03 (default); ./install.sh <host>...
    ./verify.sh             # health + bad-key 4401 + contract probe
    python3 roster-shim.py --selftest

State: `~/.local/share/roster-shim/` — `history/<lane>/<chat_id>.jsonl`
(turn journal, replayed on `history_request`), `workspaces/<lane>/<chat_id>/`
(per-chat exec cwd; devin's `-c` session continuity lives there).

## Not deployed by default

This dispatch landed code + SSOT/roster wiring only. Remaining steps:
`./install.sh`, the tailscale-serve mount above, `ROSTER_SHIM_KEYS` in
`~/.config/secrets/roster-shim.env`, then seed keys in the roster.
