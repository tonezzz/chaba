# chaba-guest — guest assistant + HA auto-login on tony-dell

The guest-facing Chaba assistant: `ada-pi` `pwa_server.py` running with
`CHABA_MEMORY=1` (file-backed public memory, no MDDB) plus two LAN-only
listeners so visitors' phones can reach it.

## Components

| piece | listens | purpose |
|---|---|---|
| `chaba-guest.service` | `127.0.0.1:8014` | guest PWA + WS + chaba memory tools |
| `chaba-guest-lan.service` | `192.168.2.67:8126` → `127.0.0.1:8014` | LAN access to guest PWA (socat, plain HTTP, LAN only) |
| `ha-guest-lan.service` | `192.168.2.67:8125` → `127.0.0.1:8123` | LAN access to HA web UI — **Caddy with XFF**, so HA sees real guest IPs |

⚠️ The HA listener must be a real HTTP proxy (Caddy), never raw socat:
`127.0.0.1/32` is in `trusted_networks` for the bridge — socat would make
every guest look like loopback and get the trusted-networks user picker.
With Caddy + XFF, guests keep their LAN IPs and get normal login.

## Deploy steps (tony-dell) — all handled by `deploy.sh`

1. **ada-pi checkout** at `~/CascadeProjects/ada-pi` (venv from
   `backend/requirements.txt`).
2. **Chaba worktree** — `~/CascadeProjects/chaba-tony-dell-worktrees/master`
   (detached at origin/master; the `chaba-tony-dell` checkout is on a feature
   branch — don't touch it). `python3 scripts/chaba/render-memory.py` produces
   `~/.local/share/chaba/context-guest.md`.
3. **Env** — `~/.config/secrets/chaba-guest.env` (see `.env.example`).
   `CHABA_GUEST_PASSWORD` may stay empty — the bridge uses the
   trusted_networks login flow.
4. **Shared chat key** — once: `POST /api/auth/keys {"name":"guest"}`.
5. **`bash deploy.sh`** — merges HA config (trusted_networks +127.0.0.1/32,
   rest_commands, pending sensor, scripts, input_text), deploys www files,
   installs units, restarts tony-ha. Idempotent — safe to re-run.

## QR flow (live)

`script.chaba_guest_qr` mints BOTH a burn-once bridge token and a fresh
redeem link for the shared `guest` chat key, then writes the combined URL to
`input_text.chaba_guest_qr_url`:

```
http://192.168.2.67:8125/local/chaba-gate.html?t=<bridge>&r=<encoded redeem url>
```

Guest scans → gate page writes `hassTokens` (logged in as `guest`) → offers
"Open dashboard" and "Open guest chat" (redeem → binds key → `/guest/`).

## Guest flow

```
QR (one-time; script.chaba_guest_qr re-mints both tokens each run)
  → /local/chaba-gate.html?t=<bridge>&r=<chat redeem>
  → hassTokens written → dashboard (HA 'guest' user) or guest chat
  → guest PWA /guest/ — name prompt → {type:"register"} → pending/
  → voice clip → /api/speakers/enroll (guest-<slug>)
  → admin: ada-users-card "Pending guests" → Promote
  → person.<name> created, voiceprint bound, session pushes identity_changed
  → memory moves guests/<name>.yml → users/<name>.yml + private file created
```

No expiry — sessions persist until admin revokes (`script.chaba_guest_revoke`
archives the user's files and drops live sessions).

## Security notes

- Guest tool surface is an allowlist (`CHABA_ALLOW` in realtime_provider.py) —
  no memory banks, no devin/calendar/cms tools, no covers/gates/locks/buttons.
- `control_entity` additionally deny-patterns `lock|cover|button|gate|garage|
  door|siren|alarm` server-side.
- Bridge tokens burn on first fetch and expire after 15 min.
- `127.0.0.1` in trusted_networks only authorizes the loopback bridge — LAN
  guests arrive via Caddy with their real IPs (XFF) and get normal login.
- HA-side auth note: the `guest` user itself is NOT trusted-networked; the
  bridge selects it via the user-picker flow server-side.
- LAN listeners are bound to `192.168.2.67` only — nothing on tailscale
  or the internet.
