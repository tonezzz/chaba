# NotebookLM re-auth runbook

NotebookLM cookie auth expires frequently (observed ~15-60 min of API use;
`__Secure-*PSIDTS` rotates fast, so hand-copied headers are often stale on
arrival). When `nlm` reports "Authentication expired", do NOT paste a stale
header — harvest a live one from the logged-in Chrome on tony-omen via the
chrome-devtools MCP:

1. `new_page https://notebook.google.com/` (loads authenticated; the user's
   Google session must be active in that Chrome profile).
2. `list_network_requests` → find any POST to notebook.google.com
   (e.g. a `batchexecute` call).
3. `get_network_request` → copy the `cookie:` request header value.
4. Write it to `/tmp/nlm_cookies.txt`, then:
   `scp /tmp/nlm_cookies.txt mn01:~/.local/share/notebooklm/.notebooklm-mcp-cli/cookies_import.txt`
   `nlm login --manual -f /root/.notebooklm-mcp-cli/cookies_import.txt -p default`
5. Verify: `nlm notebook list --json` should return notebooks.

Caveats:

- The container mounts `~/.local/share/notebooklm/.notebooklm-mcp-cli` on
  mn01 as `/root/.notebooklm-mcp-cli`; the `-f` path is container-side.
- `nlm login` (browser flow) does not work inside the container — no Chrome.
- Known open issue: notebooklm-rest logs `Failed to write updated cookies
  to /data/storage_state.json: OSError` — refreshed cookies may not persist,
  so re-auth is recurring until that mount/perm issue is fixed.

## Better paths (found 2026-09-18)

- PREFERRED: `scripts/nlm-reauth.sh mn01` on tony-omen runs the REAL
  nlm binary (`~/.local/share/nlm-venv/bin/nlm`) — a full browser login —
  then scp's `cookies.json`/`metadata.json` to the container profile dir.
  A real login saves a Chrome profile, which is required for
  `nlm auth refresh` (non-interactive cookie reissue) to work; manual
  cookie imports can never use `auth refresh` ("saved Chrome profile may
  be missing or its login expired").
- `nlm auth refresh` can keep a session alive indefinitely IF a saved
  Chrome profile exists — candidates: `nlm-reauth.sh` (real login) or
  `nlm login --provider openclaw --cdp-url <url>` (attaches to an external
  Chrome over CDP; tony-omen's debug Chrome listens on 127.0.0.1:9228 with
  `--user-data-dir=~/.config/google-chrome-debug`; the notebooklm-mcp
  container is host-networked, so `ssh -R <port>:localhost:9228 mn01`
  could expose it as http://127.0.0.1:<port> — unverified).
- Sizing rule: one harvest buys ~20-60 min ≈ 1-2 archive sessions.
  Multi-session batches WILL hit expiry mid-run; either reauth per
  session or fix durable auth (real login + `auth refresh`) first.
- Safety gates verified: sessions are never deleted unless the summary
  is archived AND the staging notebook is deleted; partial runs leave a
  `staging-*` orphan (list: `nlm notebook list --json` | grep staging;
  delete: `nlm notebook delete <id> --confirm`) and keep the session.
- `devin-chunked-extract.sh` accepts ONE session-id per invocation —
  loop for batches. Extraction (full.md) works without auth; only the
  NotebookLM stages and `--delete` gate on it.
