# Dispatch outcome — boards-502-residuals-dns-h3-access

Card: `boards-502-residuals-dns-h3-access` — residuals from the
boards-origin-502 RCA (docs/ssot/jobs/infrastructure/2026-11-09-boards-origin-502-rca.yml).

## Part 1 — idc02 edge DNS hardening: DONE (deployed live)

**Measurement** (journal window 2026-11-10 → 11-24, ~14 days):
`caddy-edge` on idc02 is a systemd **user** quadlet (podman) — the lookup
errors live in `journalctl --user -u caddy-edge.service`, not the system
journal. Found **7** `lookup boards.h3.gizmo-thailand.com: i/o timeout`
→ public 502 events (~0.5/day; dates 11-14, 11-16 ×2, 11-17 ×2, 11-18,
11-23). Chronic low-grade confirmed — matches the RCA's "still sporadic".

**Fix applied live** on idc02 `~/.config/caddy/Caddyfile` (backup:
`Caddyfile.bak-dnsresolvers-20261124`): added
`transport http { resolvers 1.1.1.1 8.8.8.8 }` inside the reverse_proxy
blocks for **both** h3 upstreams — `boards.surf-thailand.com`→boards.h3
and `status.surf-thailand.com`→chaba.h3 (same zone/NS, same failure
class). Caddy now resolves upstreams directly via public resolvers,
bypassing the flaky systemd-resolved stub; hostname kept so a future IP
change still resolves. Validated (`caddy validate` → Valid), reloaded
(`podman exec caddy-edge caddy reload`), verified consumer surfaces:
`boards.surf-thailand.com/wp/` → 200, `status.surf-thailand.com/` → 200,
0 lookup errors post-reload.

**Rollback:** restore the `.bak-dnsresolvers-20261124` file and reload.
**Follow-up:** re-check `journalctl --user -u caddy-edge.service --since
"7 days ago" | grep -c "lookup boards.h3"` in ~a week — expect ~0.

## Part 2 — h3 forensic access: endpoint verified + registered; credential blocked on Tony

- Plesk panel **live**: Plesk Obsidian 18.0.81 at
  `https://103.99.11.249:8443` (also `http://103.99.11.249:8880`).
- SSH: port 22 filtered; alt ports 2222/2022/22022/222/8022 closed — no
  ops SSH path exists.
- Fleet secret sweep (tony-omen, idc02, idc03, tony-dell): only WP-side
  creds exist (wp-boards.env app-passwords, wiki-h3-gizmo.env MediaWiki
  bot, boards wp-admin login on tony-omen). **No Plesk/SSH credential
  anywhere** — consistent with the KNOWN_PITFALLS note that h3 is
  Tony-panel-only.
- Registered `h3-plesk-panel` in `docs/ssot/infrastructure/ssot.secrets.yml`
  (endpoint, issuer, pending slot `~/.config/secrets/h3-plesk.env`).
- Board request raised for the Plesk/ReadyIDC credential (request id
  `h3-forensic-access-plesk-panel-is-live-a-fc58e4`). Once supplied:
  store the env file, fill slots, then pull Plesk/nginx/apache/php-fpm
  logs for 2026-10-29 16:00–24:00 +07 to close the RCA trigger question.

## Deliverables

- Live change: idc02 `~/.config/caddy/Caddyfile` (2 reverse_proxy
  transport blocks) + backup file on host.
- `docs/ssot/infrastructure/ssot.secrets.yml` — new `h3-plesk-panel`
  credential entry.
- `docs/ssot/jobs/infrastructure/2026-11-24-h3-dns-hardening-plesk-access.yml`
  — full measurement/change/verification record.
- `reports/SSOT_OPTIMIZATION_WARNINGS.json` — baseline +2 entries
  (secrets.yml bloat + h3 IP data-isolation warning).
- Commit `ba952b3d63` on `dispatch/20261124-152510-...` (not pushed).

## Verify

- `ssh idc02 'journalctl --user -u caddy-edge.service --since "7 days ago"
  | grep -c "lookup boards.h3"'` → expect 0 going forward.
- `curl -sI https://boards.surf-thailand.com/wp/` → 200.
- `grep -n -A8 "reverse_proxy https://boards.h3" ~/.config/caddy/Caddyfile`
  on idc02 shows the `transport http { resolvers ... }` block.

lessons:
- caddy-edge on idc02 logs to the USER journal (podman quadlet under
  user@1000): use `journalctl --user -u caddy-edge.service`; the system
  journal shows nothing.
- Caddy reverse_proxy upstream-DNS bypass: `transport http { resolvers
  <ips> }` inside the reverse_proxy block overrides system resolvers —
  cleaner than IP-pinning when the upstream hostname may change.
- `reports/SSOT_OPTIMIZATION_WARNINGS.json` baseline must be merged, not
  wholesale regenerated: a full `ssot-optimize.mjs` run on a worktree
  59 commits behind master shrinks the baseline and can mask master's
  debt — restore old baseline and append only new warnings.
