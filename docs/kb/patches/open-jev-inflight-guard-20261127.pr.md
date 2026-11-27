# PR body — open-jev in-flight inference guard (daseinlabs/open-jev)

> Prepared by chaba ops follow-up, 2026-11-27. Apply the sibling
> `open-jev-inflight-guard-20261127.patch` to a checkout at `origin/main`
> (`8f2ced8`) and open the PR from a fork with write access. The clean commit
> is already available locally as `ops/openjev-inflight-guard` @ `7c864c3`.

## Summary

Bound concurrent inference on CPU-serving `open-jev` lanes. Every FastAPI
route in `server.py` is a synchronous `def`, so Starlette dispatches it to
anyio's 40-token threadpool. An unbounded burst of multi-minute Gemma3
forwards fills all 40 workers, `/health` can no longer get a slot, and the
process has to be SIGKILLed. This patch rejects excess inference requests
immediately with `429 + Retry-After: 60` instead of queueing them into
another pileup. `/health` is deliberately not gated.

Also included:

- `openjev/lane_metrics.py` — a stdlib-only monotonic `GET /metrics`
  (requests, questions, escalations, latency buckets) attached by
  `create_app()`, so lane health can be observed without log scraping.
- `openjev/torch_backend.py` — load CPU checkpoints as `bf16` instead of
  `fp32`. Gemma activations still overflow on fp16, so CUDA/MPS keep their
  existing capability checks; CPU bf16 halves the ~18G fp32 working set to
  ~9G on 30G workstations.

## Configuration

`OPENJEV_MAX_INFLIGHT` (default `2`) matches the 2-CPU systemd quota used on
the affected host. It is set explicitly in the systemd drop-in managed by
chaba's `open-jev-guard.yml`. Callers should honour `Retry-After`.

## Verification

- `python -m py_compile` on all three changed files.
- Stubbed scorer + `TestClient`: three concurrent `/score` calls returned
  `[200, 200, 429]`; `/health` stayed 200 throughout the burst.
- Production (tony-omen, 2026-11-27 09:24–09:47): `/health` 200 throughout,
  service swap 5.69 GiB → 0.98 GiB, zram 23G → 17.9G, load 39.18 → 6.44,
  11 completed calls and 12 load-shed bursts, no AnyIO pileup.
- Caveat: completed calls took ~130s each (all above the 60s latency bucket).
  The guard fixes availability, not inference throughput; caller timeouts
  and model/hardware sizing remain a separate concern.

## Risk

Requests beyond the cap now fail fast rather than waiting. That is the
intended trade-off: the previous behaviour was a total outage requiring a
forced restart. Set `OPENJEV_MAX_INFLIGHT` higher only with a matching CPU
quota and memory budget.
