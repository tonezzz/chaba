# claw-channel (lab)

Credential-free command/report channel on the Cloudflare edge — card
`lab-cf-kv-claw-channel`. One KV namespace + one Worker; no Tailscale,
no CF Access, no origin server.

## Surface

Host `claw.surf-thailand.com` (dedicated workers-only hostname —
`edge.surf-thailand.com` is DNS-only onto idc02 and can't fire routes).

| Method | Path              | Auth           | Reads / writes                                       |
| ------ | ----------------- | -------------- | ---------------------------------------------------- |
| GET    | `/<agent>`        | none           | `KV cmd:<agent>`                                     |
| GET    | `/digest/<name>`  | none           | `KV digest:<name>`                                   |
| GET    | `/report/<agent>` | none           | `KV report:<agent>:latest`                           |
| POST   | `/report/<agent>` | `X-Ingest-Key` | KV `report:<agent>:<ts>` + `:latest` (+ R2 if bound) |
| POST   | `/cmd/<agent>`    | `X-Ingest-Key` | `KV cmd:<agent>`                                     |
| POST   | `/digest/<name>`  | `X-Ingest-Key` | `KV digest:<name>`                                   |

Everything else 404s; wrong/missing ingest key 403s; bodies must be
JSON ≤1 MiB. `x-robots-tag: noindex` on every response.

## Files

- `edge/claw-channel/worker.js` — the worker (~90 lines, zero deps)
- `edge/claw-channel/wrangler.toml` — template; `deploy.sh` renders
  `wrangler.deploy.toml` with the real namespace id + hostname
- `stacks/edge/claw-channel/deploy.sh` — idempotent: namespace, ingest
  secret, DNS AAAA `claw -> 100::` proxied, deploy, verify curls
- `scripts/claw-publish.py` — sanitized board digest -> `digest:board`

## Secrets

- `~/.config/secrets/cloudflare.env` — `cfut_` token (scopes in
  `stack.yml` `requires:`)
- `~/.config/secrets/claw-channel.env` — `CLAW_INGEST_KEY`, created by
  `deploy.sh` on first run. This is the only credential claws need for
  report ingest; it is never stored in KV.

## Verify (post-deploy)

```bash
curl https://claw.surf-thailand.com/demo                  # seeded cmd
curl -X POST -H "X-Ingest-Key: wrong" -d '{}' \
     https://claw.surf-thailand.com/report/x             # 403
python3 scripts/claw-publish.py                          # digest -> KV
curl https://claw.surf-thailand.com/digest/board         # phone-read
```

Out of scope (per card): live memory stays MDDB/sqlite, no credentials
in KV, no migration of existing channels.
