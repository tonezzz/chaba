# mddb-panel — web UI for mddb

Stock `tradik/mddb:panel-latest`, tailnet-only on :3002 (`HOST=<tailnet IP>`,
ufw-gated). Stateless query UI — points at the leader via `MDDB_SERVER`.

## Files

- `mddb-panel.container` — quadlet (`Network=host`)
- app override: `~/mddb-panel/server.js` (mounted ro)

## Move

Copy `~/mddb-panel/` + quadlet. On the target, replace the tailnet IP in
`HOST` and `MDDB_SERVER` (render: `$(tailscale ip -4)`); point
`MDDB_SERVER` at wherever the leader lives.
