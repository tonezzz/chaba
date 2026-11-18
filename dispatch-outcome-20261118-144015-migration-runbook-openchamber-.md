# Dispatch outcome — openchamber-migrate-tony-dell-to-idc02

Runner: idc02 · Branch: `dispatch/20261118-144015-migration-runbook-openchamber-`

## What was done

**The pane is cut over.** ada-ocb.surf-thailand.com now serves OpenChamber
running locally on idc02; dell's pane stays up as the soak fallback.

1. **Install (step 1, done).** node-v24.14.0 tarball → `~/.local/node24`;
   `@openchamber/web@2.7.0` + `@opencode/cli@2.3.2` installed with
   `--prefix=~/.local/node` — exact version/layout match with dell.
   `openchamber.service` + `10-litellm-env.conf` drop-in +
   `openchamber-update.{service,timer}` copied verbatim from dell;
   enabled + active, managed opencode child spawning normally.
   Clean `startup.env` written (dell's was polluted with a captured
   desktop session env — only the 3 real keys carried over, values pulled
   dell-side via ssh, never printed): `OPENCHAMBER_UI_PASSWORD`,
   `OPENCHAMBER_FRAME_ANCESTORS`, `OPENCODE_BINARY` + rebuilt PATH.

2. **Config + secrets copy (step 3, done).** `~/.config/openchamber/`
   (jwt-secret, settings, preferences, environment.json, trust, passkeys,
   etc.) and `~/.config/secrets/litellm-ada.env` copied dell→idc02 over
   ssh — never into chat/card. Same UI password + jwt-secret ⇒ Tony's
   login and existing session cookies carry over. `opencode.json`
   merged: dell's pane config (litellm model set, `mcp ada-control`,
   agent defaults, omen-llamacpp) ∪ idc02's extra litellm models =
   **22 litellm models enabled** in `/api/model`.

3. **LiteLLM lane verified.** Real session → `litellm/gemini-3.5-flash-lite`
   → prompt → assistant reply "ok". Key + proxy path proven end-to-end.

4. **Edge repoint (step 4, done).** `~/.config/caddy/Caddyfile` ada-ocb
   upstream `https://tony-dell.taila0626a.ts.net:8443` →
   `http://127.0.0.1:3000`; `caddy validate` + `caddy reload`
   (zero-downtime). Direct-bind probe
   `--resolve ada-ocb.surf-thailand.com:443:45.136.236.190` → **200** with
   `frame-ancestors` CSP intact (iframe still allowed from ada-ha).
   Rollback = restore one line + reload (backup:
   `Caddyfile.bak-ada-ocb-repoint-20261118`).

5. **Consumer repoints (step 5, done + corrections).**
   - ada-voice "bridge" is the local `ada-control` MCP process
     (`opencode/ada_mcp.py`) — it hits board-api/MDDB, never the pane
     URL; the card's "targets dell" premise was stale. No repoint needed.
   - `ada-ocb-smoke.timer` was **ExecCondition-skipping every hour**
     (`scripts/ocb-smoke.py` never reached the staging checkout — it
     smokes the MCP bridge, not the pane). `git pull --ff-only` on
     `~/CascadeProjects/ada-voice` landed the merged suite; the timer
     now runs for real.
   - Bridge dep fix: idc02 python3 lacked `mcp` (dell has it in user
     site). Created `~/.local/venvs/ada-mcp` with `mcp==1.29.0` and
     repointed the ada-control command in the host-local opencode.json;
     bridge boots clean (tools=26).
   - HA iframe src = public hostname → unchanged by design. No dell:8443
     references in ada-voice or chaba consumer artifacts.
   - tailscale-serve backup on :8443 skipped — port is owned by the
     bserver container (also: needs sudo). Dell :8443 remains the
     fallback path.

6. **Docs.** `ssot.audit.hosts.yml` (idc02 declarations + dell soak note),
   `docs/kb/openchamber-claude-agent-provider.md` fleet table,
   new job doc `docs/ssot/jobs/devnest/2026-11-18-openchamber-idc02-migration.yml`.

## Gates / what remains

- **claude-agent lane — board request raised.** claude-code 2.1.327
  installed at the pinned path; `environment.json` already carries
  `OPENCODE_CLAUDE_PATH`. Only missing: `claude auth login` on idc02
  (interactive OAuth — Tony's declared gate). Options in the request:
  (a) Tony runs `claude auth login` on idc02 [recommended], (b) approve
  `.credentials.json` copy, (c) setup-token. After auth lands, run
  `scripts/claude-code/openchamber-wire.sh` (any host, `--host idc02`) —
  steps 5-8 finish: credential store → reload → haiku smoke. Current
  `--check`: [1][3][4] green, [2][5][7] auth-blocked.
- **Browser pass (Tony, ~1 min):** open https://ada-ocb.surf-thailand.com,
  log in (same password), send a litellm + a claude-agent prompt, glance
  at the HA chaba-admin iframe.
- **Soak/close-out:** dell `openchamber.service` left active; after
  24–48h Tony decides retire vs local-only backup — then close the card.

## How to verify

```bash
systemctl --user status openchamber.service                 # idc02, active
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/   # 200
curl -sk --resolve ada-ocb.surf-thailand.com:443:45.136.236.190 \
     -o /dev/null -w '%{http_code}\n' https://ada-ocb.surf-thailand.com/  # 200
scripts/claude-code/openchamber-wire.sh --host idc02 --check      # after auth: all green
journalctl --user -u ada-ocb-smoke.service -n 20                  # next hourly run executes
```
