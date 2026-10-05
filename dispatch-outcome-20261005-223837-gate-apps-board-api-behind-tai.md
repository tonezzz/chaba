# board-api-auth — gate /apps/board-api writes behind Tailscale identity

## What changed

**`scripts/board/board-api.py`** — write gate in `do_POST` via new pure
function `caller_identity(headers, peer_ip)`:

- `Tailscale-User-Login` header (injected by `tailscale serve` on
  tailnet-authed requests) **and** every X-Forwarded-For hop must be a
  tailnet (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`) or loopback address —
  Caddy appends the real client IP per hop, so a LAN client forging the
  header still leaves its LAN IP in the chain → denied.
- Direct loopback callers with no XFF (dispatch rails, systemd fail
  units, kanban-dispatch, card-pipeline — all post to `127.0.0.1:8787`)
  are trusted as `local`.
- Optional `BOARD_API_ALLOWED_LOGINS` env (comma list) narrows allowed
  logins; unset = any tailnet identity.
- Denied writes get `403`; allowed writes log `via=<login|local>` to
  stderr (journald) and return it in the response.
- GET `/cards` + `/health` unchanged — readable by anyone who can reach
  the edge.
- `--selftest` extended with 9 gate cases (local, ts v4/v6, anonymous,
  forged, spoofed-XFF, garbage).

**`stacks/web/Caddyfile`** — `/apps/board-api/*` handle now 403s
non-GET/HEAD requests lacking `Tailscale-User-Login` (`@anon_write`
matcher; verified with `caddy validate`). This is the `/apps/vms/`
pattern the card asked to replicate — note the security SSOT flags that
the vms gate itself was never actually committed; this change makes the
pattern real for board-api and goes one step further with the app-level
re-check.

**Docs**: `ssot.kanban.yml` write_path.api now describes the gate;
`ssot.security.tony-dell.yml` gained a `ts-serve:443/apps/board-api/`
listener row; decision/runbook trail at
`docs/ssot/jobs/security/2026-10-05-board-api-tailnet-gate.yml`.

## Verification (worktree instance, BOARD_API_PORT=18787)

| request | result |
|---|---|
| GET /health, /cards (anon) | 200 (cards 404'd pre-render — pre-existing, now renders fine) |
| POST /comment, direct loopback | 200 `via=local` |
| POST /comment, XFF=LAN, no header | 403 |
| POST /comment, XFF=ts-ip + Tailscale-User-Login | 200 `via=tonezzzz@github` |
| POST /comment, forged header + LAN XFF | 403 |

`python3 scripts/board/board-api.py --selftest` → ok;
`caddy validate` on updated Caddyfile → Valid.

## NOT done / post-merge steps (needs a deploy — out of scope here)

1. Merge this branch → live `chaba-tony-dell` checkout.
2. `systemctl --user restart chaba-board-api.service web` on tony-dell.
3. Live verify: `curl -X POST https://tony-dell.taila0626a.ts.net/apps/board-api/comment`
   without creds → 403 at edge; a tailnet browser board click → 200.
   Caveat: LAN access to the board page still renders, but write buttons
   will 403 — use the tailnet URL.

## Pre-existing issue noticed (not fixed, out of scope)

`node scripts/ssot-validate-all.mjs` reports 1 error:
`jobs/kanban/2026-10-05-board-request-notify.yml` is missing required
field `title` (from commit 6be5fe45, the kanban-push-notify session).
