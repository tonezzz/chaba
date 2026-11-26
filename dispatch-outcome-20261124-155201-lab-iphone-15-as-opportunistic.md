# Dispatch outcome — lab-iphone-webgpu-worker (iteration 3)

Card: `lab-iphone-webgpu-worker` (OPS-0779) — Lab: iPhone-15 as
opportunistic WebGPU inference worker. Host: tony-dell, branch
`dispatch/20261124-155201-lab-iphone-15-as-opportunistic`.

## What changed

**bge-compat question answered without the phone.** The page's button-6
test (does browser bge-m3 share the ollama bge-m3 bank vector space?) had
shipped 2026-10-23 but never produced a result comm. Vector space is
device-independent, so I ran the identical model call headlessly:
`Xenova/bge-m3` dtype q4 via `@huggingface/transformers` on Node
(onnxruntime-node CPU EP) vs the committed reference vector
(`bge-ref.json`, from ollama bge-m3):

- pooling=cls → cosine **0.9664** — COMPATIBLE (1024 dims)
- pooling=mean → 0.7598 — divergent (bge-m3 is a CLS model; page already
  takes max(cls, mean) so it would report compatible)

Repro script committed: `scripts/nest/webgpu-bge-compat.mjs`.

**embed-nest-bridge rebuilt.** The MEM-0805 lane-B pull→push bridge
(browser/nest workers behind the embed pool) was lost with its dirty
dispatch worktree on 2026-11-14 and never reached master. Reimplemented
per the card's comms spec in `scripts/nest/embed-nest-bridge.py`:
`POST /api/embed` enqueues+blocks (ollama-shaped `{embeddings}`),
workers long-poll `GET /v1/job` + `POST /v1/result`; instant 503 when no
worker seen in 45s; 7s job TTL under the pool's 8s upstream timeout; 20s
claim lease requeues once; timed-out waiters cancel their job.

**embed-pool-shim DEFER tier restored.** `EMBED_POOL_DEFER_UPSTREAMS`
join the `/api/embed` race only after `EMBED_POOL_DEFER_AFTER_MS`
(default 1500) with no primary winner — opportunistic workers burn
device cycles only on fleet slack. Pass-through calls try deferred last.
`/health` reports both tiers.

**Page iteration 3** (`stacks/web/public/apps/webgpu-bench/`):
- `manifest.webgpu.json` + apple-touch metas → Add to Home Screen gives
  a standalone "GPU Worker" icon whose start_url `?pool=1` auto-boots.
- Auto-probe + auto-start worker loops via `?worker=1` / `?pool=1` or
  remembered localStorage toggles.
- job.json staleness: `created` stamped by `webgpu-mddb-job.py`, page
  skips jobs >12h (previously a stale pending job re-ran + re-posted to
  the card on every reload).
- Poll-error backoff (30s after 3 consecutive failures) + live
  worker/pool status lines.
- Button 7 **pool worker**: long-polls `/apps/embed-nest/v1/job`
  (bge-m3, cls pooling — bank-compatible), posts `/v1/result`.

**Caddy route** (`stacks/web/Caddyfile`): `/apps/embed-nest/*` →
`http://idc03.taila0626a.ts.net:11440`, same-origin so the https page
dodges Safari mixed-content; writes gated on `Tailscale-User-Login`
like board-api.

## Verified

- `pytest tests/nest/test_embed_nest_bridge.py
  tests/embed/test_pool_shim_defer.py` — **11 passed** (queue/claim/
  lease-requeue/TTL/caps/defer-tier semantics).
- Live smoke of the bridge: worker claim → `/api/embed` blocked →
  `/v1/result` → `200 {"embeddings": ...}`; no-worker → instant 503.
- `node --check` on the page script; manifest JSON parses;
  `py_compile` clean on all touched Python.
- bge compat numbers above (real model run, ~5min incl. download).

## NOT deployed (dispatch scope — needs approval + iPhone hands)

1. idc03: run `embed-nest-bridge.py` as a user unit bound to
   `100.102.134.91:11440` (tailnet only — never 0.0.0.0 on the VPS).
2. idc03 `embed-pool-shim` unit: add
   `EMBED_POOL_DEFER_UPSTREAMS=http://100.102.134.91:11440`, redeploy
   shim (defer tier is new code).
3. tony-dell web stack: reload Caddy for `/apps/embed-nest`.
4. iPhone: `/apps/webgpu-bench/` → Share → Add to Home Screen → button 7.

Full trail: `docs/ssot/jobs/nest/2026-11-24-embed-nest-bridge-iphone.yml`.
Card comm posted with the same summary.

## Notes / risks

- iOS Safari suspends background tabs — foreground-only worker, as the
  card brief already states. No Battery API on iOS; keep it on charger.
- Pool job budget ≤6.5s end-to-end; mddb sends single texts so bge-m3
  on A16 fits comfortably. bge-m3 q4 (~300MB) + MiniLM coexist lazily.
- `ssot-validate-all.mjs` fails locally with ENOBUFS (pre-existing,
  unrelated); the new jobs YAML parses cleanly.

lessons:
- transformers.js vector-space compat is testable headlessly in Node —
  don't wait for the device to answer a model-space question.
- bge-m3 needs CLS pooling; mean pooling diverges (cosine 0.76) — the
  compat gate is pooling-specific, not just model-specific.
- Lost-worktree recovery works: the lane-B bridge spec survived in card
  comms; rebuild + unit tests restored it in one dispatch.
- npm onnxruntime-node postinstall fails on CUDA download — set
  ONNXRUNTIME_NODE_INSTALL_CUDA=skip (CPU EP is enough for compat tests).
