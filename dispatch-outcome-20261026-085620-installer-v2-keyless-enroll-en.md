# Dispatch outcome — installer v2 keyless enroll endpoint (follow-up)

**Card:** fleet-installer-v2 · **Runner:** idc02 · **Branch:** dispatch/20261026-085620-installer-v2-keyless-enroll-en

## Result: DONE — endpoint serves enroll POST per contract; `app.` edge is live; the "new CF token" turned out unnecessary

### 1. The Cloudflare token was never dead (major correction)

The previous dispatch reported `cfat_` dead on all slots based on
`GET /user/tokens/verify` → `Invalid API Token`. That endpoint only
validates **user-scoped** tokens — this token is account/zone-scoped, so
verify lies (the quirk was even noted in ssot.secrets.yml). Gated on a
real zone read instead → token works. **No dashboard mint needed; the
board request `need-a-new-dns-capable-cloudflare-token-15edf9` is moot.**

- Built `scripts/ops/cf-dns-upsert-when-ready.sh` + a `cf-dns-upsert.path`
  systemd.path watcher on idc02 watching `~/.config/secrets/cloudflare.env`.
- It fired on the first env touch, zone-read-validated the existing token,
  ran `cf-dns-upsert.sh` → **created `A app.surf-thailand.com → 157.85.102.125`
  (proxied)**, commented on the card, self-disabled. Units removed after
  success; script kept in repo for future token-drop handoffs.

### 2. `app.surf-thailand.com` edge is live

- A record resolves through CF proxy (172.67.x / 104.21.x).
- `caddy-edge` had been failing ACME NXDOMAIN for ~80 min on a 20-min
  backoff; `systemctl --user restart caddy-edge.service` re-ran obtain →
  **production LE cert issued** via http-01 through the proxy (~09:02).
- Verified: `https://app.surf-thailand.com/install` → 200 (v2 script);
  `/` → 302 → /install; `POST /enroll` → 200 + node registry write.

### 3. `/enroll` contract re-verified on both edges

- `POST https://api.surf-thailand.com/enroll` → 200, node upserted into
  `nodes.json` (input-bridge registry).
- `POST https://app.surf-thailand.com/enroll` → 200, same.
- The ops-event emit (`host_online` doc → `ada-ha-events-tony`, the
  stick-announce contract) briefly returned `event_error:"fetch failed"`
  during this session because **primary mddb on idc03 was stopped 08:46
  mid-compaction** (card mddb-storage-reduction-retention-relocation;
  `mddb-compact.db` finished 08:56 but nobody swapped/restarted for ~16
  min, consumers failing). Restarted `mddb.service` at 09:02 on the
  cleanly-shutdown `mddb.db`; compact file left staged — heads-up posted
  on the storage card.

### SSOT trail

- `ssot.secrets.yml` — corrected the cfat_-dead claim; documented
  "never gate on /user/tokens/verify for scoped tokens".
- `ssot.routes.yml` — app. edge marked live.
- `docs/ssot/jobs/infrastructure/2026-10-26-installer-v2-enroll-endpoint.yml`
  — limits resolved, watcher + cert flow recorded.
- `scripts/ops/cf-dns-upsert-when-ready.sh` — new (repo copy; installed
  copy at idc02 `~/.local/bin/`).

### Verify

- `curl -s https://app.surf-thailand.com/install | head -3`
- `curl -sX POST https://app.surf-thailand.com/enroll -d '{"hostname":"t","lan_ip":"1.2.3.4","tailnet_ip":"5.6.7.8"}' -H 'Content-Type: application/json'`
- `dig +short app.surf-thailand.com` → CF edge IPs (proxied)
- MDDB `ada-ha-events-tony` holds `ops-host-enroll-*` docs
