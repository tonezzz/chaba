# Dispatch outcome — reconcile the two proxy variants

Card: `gemini-proxy-live-repo-divergence` (MEM-1464)
Dispatch: 20261126-234625-reconcile-the-two-proxy-varian
Result: **DONE — option (a) executed.** Live variant's uncommitted work merged
into repo master on top of the free-lane budgets. Commit `b1aca5f9a1` on
`dispatch/20261126-234625-reconcile-the-two-proxy-varian` (not pushed).

## What changed

- `scripts/mddb/gemini-ollama-proxy.mjs` (790 → 867 lines,
  sha256 `c2a618cb91fec6d7c168521b2e1237f6966a85ee038c371c41624b8c344576a8`):
  - Added LiteLLM gateway leg verbatim from live: `EMBED_GATEWAY_BASE` /
    `EMBED_GATEWAY_KEY`|`LITELLM_KEY` / `EMBED_GATEWAY_MODEL`,
    `EMBED_VIA_GATEWAY`, `OR_LEG_CONFIGURED`, `fetchGatewayEmbedBatch`.
    Gateway is backup-only — `OPENROUTER_PRIMARY` still requires a raw
    `OPENROUTER_API_KEY`.
  - Replaced single-key `freeGeminiCircuitOpenUntil` with the live
    free-key ring: `GEMINI_API_KEY` + `GEMINI_FREE_KEYS` +
    `GEMINI_FREE_KEYS_NN`, per-key `freeGeminiCircuits` map, `keyTag`.
  - Kept all repo budget machinery (`FREE_GEMINI_HOURLY_BUDGET`,
    `FREE_GEMINI_BULK_DAILY_BUDGET`, `PAID_GEMINI_BULK_ALLOW`,
    `x-embed-lane: bulk` / `"lane":"bulk"` marker, tagged `freeBudget`
    errors that don't trip the provider circuit). Budget gates evaluate
    before key iteration; `freeCallServed(bulk)` counts once per batch.
  - "Free key configured" gates switched `GEMINI_API_KEY` →
    `GEMINI_FREE_KEYS.length` so ring-only configs engage the free leg.
  - Kept repo's `GEMINI_API_BASE` env override (live hardcoded the API
    base — this is what forced the prior fetch-intercept probe harness).
  - `/health` reports the union: `embed_gateway`, `circuit.free_keys`,
    all budget counters.
- `tests/embed/test_gemini_proxy_ring_gateway.mjs` (new): per-key failover
  + gateway-leg tests in the existing stub style.
- `docs/ssot/infrastructure/ssot.services.yml`: replaced the stale
  "repo lacks keyring — reconcile before deploy" note with the reconciled
  state + restart hazard.
- `docs/ssot/jobs/mddb/2026-11-26-gemini-proxy-variant-reconcile.yml`:
  full decision/verification/hazard record.

## Verification

- `node --check` clean; both YAML files parse; SSOT pre-commit validation
  passed.
- `node --test tests/embed/test_gemini_proxy_budget.mjs
  test_gemini_proxy_ring_gateway.mjs` → **5/5 pass** (budget suite
  unchanged, new ring+gateway suite 2/2).
- Manual probe (`.dispatch-scratch/reconcile/`, untracked): hourly budget
  hit → paid leg serves (`gemini-embedding-2-paid`, `paid_calls=1`,
  circuit NOT tripped); `x-embed-lane: bulk` + `PAID_GEMINI_BULK_ALLOW=0`
  → paid leg skipped as designed.
- Live file pulled read-only via ssh (sha256 `a8c3df80…275ba` matched the
  card); diff preserved at `.dispatch-scratch/reconcile/live-vs-repo.diff`.

## CRITICAL extra finding — restart hazard is worse than carded

The ansible-regenerated quadlet
(`~/.config/containers/systemd/gemini-ollama-proxy.container`, generated
2026-11-26T02:17Z) mounts the repo file at `/app/proxy.mjs` **and dropped
`EnvironmentFile=/home/tony/.config/secrets/mddb-gemini.env`**. The
running container (created 2026-11-25 19:15, `podman inspect` verified)
carries `GEMINI_API_KEY`, `GEMINI_API_KEY_PAID`, `GEMINI_FREE_KEYS_01..10`,
`EMBED_GATEWAY_BASE/MODEL`, `LITELLM_KEY`, `GEMINI_PROXY_HOST` — all from
that env file. The proxy never reads `GEMINI_API_KEY_FILE`, so the next
`gemini-ollama-proxy.service` restart yields a container with **zero
provider keys** → "no embedding provider configured" → total embed outage
until env is restored. This is a template regression in the chaba-ansible
repo (not in this checkout).

**DO NOT restart the unit.** Filed as card `gemini-proxy-quadlet-envfile-drop`
(MEM-1469, backlog, high) via board-api; hazard also recorded in SSOT
`ssot.services.yml` and the job record. After MEM-1469 lands and
chaba-repo-sync refreshes `~/CascadeProjects/chaba` on idc03, the next
restart picks up merged code + full env; verify `/health` shows
`free_keys:6`, `embed_gateway:"embedding"`, budget counters.

## How to verify

```
node --check scripts/mddb/gemini-ollama-proxy.mjs
node --test tests/embed/test_gemini_proxy_ring_gateway.mjs \
            tests/embed/test_gemini_proxy_budget.mjs   # 5/5
git show b1aca5f9a1 --stat
```

Post-merge live check (after MEM-1469 + restart):
`ssh idc03 'curl -s 127.0.0.1:11435/health'` → `free_keys: 6`,
`embed_gateway: "embedding"`, `provider_mode`, budget counters present.

lessons:
- Ansible-regenerated quadlets can drop `EnvironmentFile=` silently — diff the generated unit against the running container's `podman inspect .Config.Env` before ANY restart; env loss is a bigger outage than the code swap the card described.
- `node --test tests/embed/` on the directory fails (picks up .py files); run the .mjs test files explicitly.
- Repo file now honors `GEMINI_API_BASE` — no fetch-intercept harness needed for future proxy probes; point it at a local stub.
- Live-on-host variants drift fast: the "live" proxy was a hand-patched file with ring+gateway that existed nowhere in git; pulling it read-only via ssh + diffing against master was the fastest reconcile path.
