# Secret rotation — Ada stack (GEMINI_API_KEY + HOME_ASSISTANT_TOKEN)

Runbook for rotating the secrets exposed in pre-2026-09-22 transcripts.
Companion script: `scripts/ada/rotate-ada-secrets.sh` (fingerprint-matched —
updates env files by current-value suffix, never prints secrets, restarts
only already-active units).

## What rotates

| Secret | Current fingerprint | Files holding it |
|---|---|---|
| `GEMINI_API_KEY` | `...UEQA` | all `ada-*.env` on mn01/tony-dell/idc01, `chaba-guest.env`, `mddb-gemini.env` (idc01) |
| `HOME_ASSISTANT_TOKEN` (tony-ha, remote URL) | `...6823` | `ada-ha-tony.env` (mn01, idc01), `ada-pi-pwa.env` (tony-dell, idc01) |
| `HOME_ASSISTANT_TOKEN` (tony-ha, loopback) | `...d-uM` | `ada-ha-pwa.env`, `ada-ha-tony.env`, `chaba-guest.env` (tony-dell only) |
| `HOME_ASSISTANT_TOKEN` (michael-ha) | `...M_sY` | `ada-ha-michael.env` (all hosts) |

**Not touched:** `...jjmw` Gemini key (`gemini-api-key.env`, `gemini-mic-test.env`,
`open-notebook.env`) — separate, unexposed. `NOTEBOOKLM_REST_API_KEY`, `ADA_API_KEY*`,
`MDDB_MCP_API_KEYS` — different credentials, rotate separately if ever exposed.

## Step 1 — generate new values (manual, per provider)

### Gemini API key — Google AI Studio

No automation path exists on our hosts (no `gcloud`/OAuth anywhere). In the browser:

1. <https://aistudio.google.com/apikey> → **Create API key**
2. Copy the new key.
3. **Do not delete the old `...UEQA` key yet** — delete it only after step 3
   verifies green, so nothing is down if a file is missed.

Alternative (no new key needed): the unexposed `...jjmw` key could be promoted
to shared use as a stopgap — but it then shares quota with open-notebook, so a
fresh key is still the right end state.

### Home Assistant long-lived tokens — HA profile UI

LLATs can only be minted via the frontend (or an OAuth+WS flow with a
refresh-token login — see note). Per instance:

1. Open the HA UI → click your user avatar (bottom-left) → **Security** tab →
   **Long-lived access tokens** → **Create token**.
2. Name it `ada` (or `ada-rotate-2026-09`).
3. Copy the token (shown once).
4. Delete the old token **after** services are verified on the new one.

Do this twice for tony-ha (the `...6823` and `...d-uM` tokens are two separate
LLATs — one used by remote-URL envs, one by loopback envs) and once for
michael-ha (`...M_sY`).

> Automation note: `auth/long_lived_access_token` exists on the HA websocket
> API but requires a refresh-token-authenticated connection — an LLAT cannot
> mint another LLAT. With UI username+password the OAuth login flow yields a
> refresh token and the whole thing is scriptable; stored nakva creds exist
> for michael-ha (`~/.local/share/home-assistant-michael/credentials.json`),
> none for tony-ha.

## Step 2 — apply

```bash
~/CascadeProjects/chaba/scripts/ada/rotate-ada-secrets.sh \
  --gemini NEWGEMINIKEY \
  --ha-tony-remote NEWTONYTOKEN1 \
  --ha-tony-local  NEWTONYTOKEN2 \
  --ha-michael     NEWMICHAELTOKEN
```

- `--dry-run` first to see the planned file list (prints filenames + old
  fingerprints only).
- `--no-restart` to update files without touching services.
- Any subset of flags works — only those values rotate.

Affected services (restarted only if already active):
mn01 `ada-ha-*`, idc01 `ada-ha-*`/`ada-pi-pwa`/`gemini-ollama-proxy`,
tony-dell `ada-pi-pwa`/`chaba-guest*`.

## Step 3 — verify, then revoke old values

```bash
# health
for h in idc01 mn01; do ssh $h 'systemctl --user is-active ada-ha-tony'; done
curl -s -o /dev/null -w '%{http_code}\n' https://idc01.taila0626a.ts.net/api/auth/status

# then in AI Studio: delete the ...UEQA key
# and in each HA profile: delete the rotated LLATs
```

Rollback: the old values are gone once revoked — keep the new env files as the
only copy (they already are; nothing else references the secrets).
