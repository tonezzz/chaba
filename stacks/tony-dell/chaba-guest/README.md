# chaba-guest — guest assistant + HA auto-login on tony-dell

The guest-facing Chaba assistant: `ada-pi` `pwa_server.py` running with
`CHABA_MEMORY=1` (file-backed public memory, no MDDB) plus two LAN-only
listeners so visitors' phones can reach it.

## Components

| piece | listens | purpose |
|---|---|---|
| `chaba-guest.service` | `127.0.0.1:8014` | guest PWA + WS + chaba memory tools |
| `chaba-guest-lan.service` | `192.168.2.67:8126` → `127.0.0.1:8014` | LAN access to guest PWA (plain HTTP, LAN only) |
| `ha-guest-lan.service` | `192.168.2.67:8125` → `127.0.0.1:8123` | LAN access to HA web UI (plain HTTP, LAN only) |

## Deploy steps (tony-dell)

1. **ada-pi checkout** — clone/pull `/home/tony/CascadeProjects/ada-pi` on
   tony-dell and create the venv (`backend/requirements.txt`).
2. **Chaba data dir** — `mkdir -p ~/.local/share/chaba/{guests,users,pending,revoked}`
   and render `context-guest.md` (see chaba repo `scripts/chaba/render-memory.py`;
   the chaba repo checkout on tony-dell provides the control file).
3. **Guest HA user** — create user `guest` (non-admin, random password) via the
   tony-ha UI or `config/auth_provider/homeassistant/admin_create` WS command.
   Put the password in `CHABA_GUEST_PASSWORD`.
4. **Env** — copy `chaba-guest.env.example` to `~/.config/secrets/chaba-guest.env`
   and fill it in.
5. **Units** — install the three `.service` files into
   `~/.config/systemd/user/`, then `systemctl --user daemon-reload &&
   systemctl --user enable --now chaba-guest chaba-guest-lan ha-guest-lan`.
6. **HA package** — merge `ha-package.yaml` into tony-ha config (packages dir)
   and add `chaba_api_key` to secrets. Reload config.
7. **Gate page** — `../tony-ha/www/chaba-gate.html` must exist in tony-ha's
   `www/` (deploy with the other cards).
8. **QR flow** — admin runs `script.chaba_guest_qr`; the printed
   `input_text.chaba_guest_qr_url` is encoded into the QR. Guest scans →
   `chaba-gate.html` → auto-login → `/` dashboard. Guest chat lives at
   `http://192.168.2.67:8126/guest/`.

## Guest flow

```
QR (rotating one-time token, auto-refresh after each scan)
  → guest PWA /guest/  — name prompt → {type:"register"} → pending/
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
- LAN listeners are bound to the LAN IP only — nothing is exposed on tailscale
  or the internet.
