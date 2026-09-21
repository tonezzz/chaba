---
status: approved
created: 2026-09-21
---

# Secrets Console — one place for keys, logins, rotation

Status: APPROVED v1, 2026-09-21. Motivated by the same-day incident where a
leaked `GEMINI_API_KEY` turned out to be scattered across 6 env files on 2
hosts with no record of which service consumed it.

## The idea

Every credential is one logical thing with many bindings:

```
CREDENTIAL (logical) → SLOTS (env files / unit files / whole files, per host)
                     → CONSUMERS (systemd units, scripts)
```

The console stores the mapping in SSOT, writes a new value to every slot in
one action, restarts the consumers, and re-verifies parity by fingerprint.
It never stores or returns a value — fingerprints only (sha256 prefix +
mtime), so "mn01 still has the old key" is visible at a glance.

## Two parts

1. **Credential registry** — manifest `docs/ssot/infrastructure/ssot.secrets.yml`
   (metadata only, commit-safe) + backend that reads/writes slots over ssh.
   Slot types: `var` (env-file line), `file` (whole file is the secret —
   JSON key files), `unit` (inline `Environment=` in a systemd unit —
   daemon-reload after write).
2. **Login vault** — for creds with no env slot (router logins, DVR
   passwords, recovery codes). Fernet-encrypted JSON at
   `~/.local/share/secrets-vault/vault.json.enc`, key file mode-600.
   Values shown only on explicit reveal (X-API-Key required).

## Decisions (2026-09-21)

- **Host**: tony-dell (most secrets live there; ssh's to mn01 + tony-omen).
- **Vault replica**: after every vault write, scp the encrypted file to
  tony-omen `~/.local/share/secrets-vault/` — the only unique state.
- **Unlock**: key file `~/.local/share/secrets-vault/key` mode 600.
- **Unit-file slots**: managed like env slots (yomi-api's inline
  `GEMINI_API_KEY` included); daemon-reload after write.
- **Track issuer/expiry**: manifest records issuer console URL, rotation
  steps, and optional expiry — the rotation checklist is generated.

## Safety rails

- Tailnet-only — the app **refuses to start** with `ADA_DEPLOY=public`.
- `X-API-Key` (env `SECRETS_CONSOLE_API_KEY`) gates every mutation AND the
  vault reveal endpoint. Unset → fully read-only.
- Values write-only for env slots — paste in, fingerprint out.
- Writes are atomic (tmp+rename, mode 600, timestamped `.bak` kept).
- Every write → append-only `~/.local/share/secrets-vault/audit.log` +
  chaba-event (`severity: warn`) — visible in the Events feed.
- Vault/env content never enters MDDB, git, or session transcripts.

## API

```
GET  /api/health
GET  /api/credentials              # manifest + slot fingerprints/parity
GET  /api/credentials/{id}         # detail + rotation checklist
POST /api/credentials/{id}/set     # {value, restart?} → all slots
POST /api/credentials/{id}/verify  # re-hash slots → parity report
GET  /api/vault                    # entry metadata only
POST /api/vault/{id}/reveal        # secret fields (X-API-Key)
POST /api/vault                    # add entry
PUT  /api/vault/{id}               # update entry
DELETE /api/vault/{id}
```

## Runtime

- `apps/secrets/server.py` under the ada-pi venv on tony-dell (FastAPI
  already there — same trick as obsidian-vault on mn01).
- systemd user unit `secrets-console.service`, bound to the tailscale IP
  on :8005 + loopback. URL: `https://tony-dell.taila0626a.ts.net` path or
  `http://tony-dell:8005/` over tailnet.
- UI: `stacks/web/public/apps/secrets/index.html` — two tabs (Credentials
  / Logins), dark theme matching the obsidian app.

## Phases

- M0 manifest inventory (~20 credentials, ~50 slots) — done at authoring
- M1 read-only: inventory grid + fingerprints + drift badges
- M2 slot writes + consumer restart + audit + events
- M3 login vault (Fernet) + tony-omen replica
- M4 rotation wizard polish, expiry reminders, credential retirement

## Non-goals

Not a team secrets manager; no public exposure ever; not a git-crypt/SOPS
store (values stay out of the repo entirely).
