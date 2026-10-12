# Capacity Adjust — procedure (QA / QC / audit)

Trigger: the system report's `host_loads` shows a host persistently under
or over capacity, or a placement decision needs right-sizing. Registry:
`docs/ssot/infrastructure/ssot.host-capacity.yml` (`procedure:` block is
the short form; this doc is the full one).

## Phase 0 — MEASURE (evidence, not vibes)

- Use the **5-min `host-loads` sampler** output in the system report —
  `snapshot_age` must be <1h or re-run `scripts/host-loads.py` first.
- One snapshot proves nothing (nights idle, laptops sleep). Sustained =
  same verdict across ≥3 daily reports.
- Thresholds:
  - **over**: disk free <15%, mem used >80% sustained, load >2× cores.
  - **under**: mem used <30% AND disk <50% AND the host holds movable
    services (a warm-standby/DR host being idle is *by design* — check
    `role:` before calling it waste).
- As of 2026-10-12 the live verdicts: **tony-dell disk 86% = over** (the
  real pressure), **macbook load ~8 on 4 cores = oversubscribed**,
  **idc03 mem 4.3G free = tight**, while omen (25G free + GPU), idc02
  (11G free, 220G disk), mn01 (warm) = under. Check fresh numbers — they
  move.

## Phase 1 — DECIDE (card it)

Card `capacity-move-<service>` with:

- source host → target host, service(s), headroom math (mem/disk delta).
- **blast radius**: what else breaks if the target goes down —
  co-tenancy is a real cost (kk-ha already shares idc03 with all Ada
  backends; don't stack the guest lane on the busiest box "because it
  fits").
- **QA plan** (pre-flight checklist, filled on the card):
  - service deps: ports, mounts, env/secret files, DB volumes
  - routes: caddy/tailscale-serve/edge entries pointing at old host
  - identity: systemd unit names, container names that embed the host
  - consumers: hard-coded IPs/hosts in other services' env
  - run `scripts/ops/ref-sweep.sh <old-identity>` BEFORE moving —
    finds every reference to the old host:port/service name.
- placement must satisfy `placement_policy` + isolation rules (member/
  guest lanes don't inherit owner co-tenancy).

## Phase 2 — EXECUTE

- Move via the service's **own stack** (`stacks/services/<svc>/`
  quadlet + install.sh) — never ad-hoc rsync (existing rule).
- Stateless: cut over directly. Stateful: provision target → sync data
  → stop source → cutover → leave source **stopped-but-present 24h**
  (instant rollback).
- Same-session approval required for prod moves (`ha-node-migrate`
  pattern — kk-ha/michael-dev moved this way 2026-10-09).

## Phase 3 — QC (verify the move, not the hope)

1. Service health endpoint green on target.
2. `audit-hosts.py --host <src> --host <dst>` — deltas must equal
   *exactly* the intended change; anything else = investigate/rollback.
3. Route-health node: public URL still 200 through the edge.
4. **Soak 24h**: host-loads sampler on target stays under thresholds
   (a move that trips its own trigger was a bad move — roll back).
5. Consumer smoke: one real request through the service's actual user
   path (e.g. a voice-card turn, not just /health).

## Phase 4 — AUDIT (make it durable)

- Update `ssot.host-capacity.yml` — re-measure the hosts, bump as-of.
- Update `ssot.services.yml` host fields + `ssot.audit.hosts.yml`
  expected-service list (else tomorrow's audit reports phantom deltas —
  the exact noise this procedure exists to kill).
- Close the card with evidence: health output, before/after `df`/`free`,
  soak result. No evidence = stays open (`drift-reconcile` re-flags it).

## Current capacity picture → candidate moves

| Host | State | Candidate action |
|---|---|---|
| tony-dell | disk 86% — over | prune first (disk-trend top-growers), then move stateful storage off / |
| tony-omen | 25G free + GPU | already dedicated nest lane — keep |
| idc02 | 11G mem / 220G disk free | absorbs member HA nodes per policy |
| idc03 | mem tight, hosts all Ada | do NOT add; consider moving a member node to idc02 |
| mn01 | warm | leave warm (DR posture) |
| macbook | load 8+/4 cores | laptop — shed runner work, never add |
