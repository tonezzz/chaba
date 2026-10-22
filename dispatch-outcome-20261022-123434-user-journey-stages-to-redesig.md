# Dispatch outcome — vcast-ux-flow (2026-10-22)

## What the card asked

Assess + redesign the vcast user/operator journey per the 6-stage spec:
PAIRING (clear waiting state + claim code + expiry + approver), IDENTITY
(stable label primary, preferred-vs-assigned slots, no dup live labels),
LIFECYCLE (explicit derived states incl. stale from last_seen+socket),
CASTING (honest delivery + last-cast per pane), RECOVERY (one-click
reclaim/release + sweep + reason+next errors), OPERATOR VIEW (fleet
health line + flap metric) — plus audit timeline, recovery benchmark, and
a CMS evidence page.

## What changed (commit 97a8faf3 on the dispatch branch)

**Relay — `stacks/web/input-bridge/server.mjs`**
- `lifecycleOf()` derives per screen: `pairing` (pending row or in-flight
  claim), `connected`, `idle`, `playing`, `reconnecting(age_s,
  reclaim_in_s)`, `stale(age_s)` — from socket state + timestamps, not
  registry presence. A **live socket gone silent**
  (`VCAST_STALE_SEEN_MS`, default 120s) also derives stale with
  `silent_socket:true` — this catches the zombie case the live fleet
  shows today (screens 2/4 read `connected:true` with 6-day-old
  `last_seen`).
- `GET /displays` now returns: screens (label-primary identity,
  preferred_screen/drift/label_dup, lifecycle fields, per-pane
  `last_cast {type,url,at}`), pending (code + `expires_in_s` +
  device_id), `released[]` tombstones with `reclaim_until`, `health{}`
  (connected/reconnecting/stale/pending/released + `flaps_24h` +
  `last_flap` — same abnormal-close/supersede definition
  vcast-auto-health.py counts in journald), `events` (last 40).
- `POST /sweep {screen|all:true}` — force-frees dead entries (the
  one-click "name held by dead socket" fix); 409s a live screen with a
  next action.
- Errors carry reason + next action: claim 409 → `held_by`,
  `retry_in_s`, `next`; `/release` → `tombstone_until` + note "released —
  name reserved 30d for reclaim"; `/screen` → 409 on a dup label against
  a live screen; 404s get `next` hints.
- Audit: persisted `displays-events.json` (cap 400, `VCAST_EVENTS`)
  logs pending/claim(+resurrected/reclaimed)/register(+rebind)/
  supersede/disconnect(code,abnormal)/sweep/release/dismiss/relabel/
  move/register-refused. `lastCast` entries wrapped `{msg,at}`.
- `vcast-headless.mjs` now heartbeats state every 30s like the real page
  (keeps `last_seen` honest for sims).

**Display — `index.html`**: pair view shows "waiting to pair" + code +
expiry countdown (`pending.ttl_ms`) + "anyone on the tailnet can approve
— scan or tell Ada claim display NNNN"; HUD counts disconnect age +
"reconnected after Ns" toast; released displays get a tombstone toast.
`sw.js` bumped vcast-v13 (+displays.html asset).

**Operator — new `/apps/vcast/displays.html`**: fleet health line,
pending cards (code/expiry/Pair/Dismiss), screen cards (lifecycle badge,
reclaim countdown, state_detail render proof, per-pane last cast, ▶
test/■/Sweep now/Release), released tombstone rows, 20-event timeline;
every action toasts `ok` or `error → next`. `pair.html` gained expiry +
approver text + 409 next-action + link to the displays view.
`vcast-screens-card.js` (HA) renders fleet health, lifecycle, pending
code+expiry, Sweep on dead rows, Release with note, error+next alerts —
backward-compatible against an un-upgraded relay.

**Docs**: `ssot.apps.vcast.yml` (new "Operator UX" section + endpoint
list), `docs/ssot/jobs/vcast/2026-10-22-vcast-ux-flow.yml` (full job
trail).

## Results

- New `vcast-ux-check.mjs`: **37/37 PASS** — covers every stage
  including silent-socket stale and the benchmark.
- Full suite: registry 19/19, claim 19/19, cast 17/17, flap 7/7,
  handoff 6/6 — **105 total, 0 failures** (loopback, node 22).
- **Benchmark**: disconnect→rebound **350ms** self-heal (client backoff
  ≤5s worst case) vs ~30min manual ops surgery before. Dead-entry
  reclaim = one click.
- Evidence page: `ada-cms-pages/vcast-ux-flow-report` (kind:report,
  domain:vcast) with before/after registry states + flap metric —
  reports index regenerated.

## NOT deployed

Dispatch worktree only. To ship: rsync `stacks/web/public/apps/vcast/`
to the web container (instant) + restart `input-bridge` on idc03 +
the next www sync for the HA card. Promotion needs explicit approval
per AGENTS.md.

## How to verify

1. `cd stacks/web/input-bridge && npm i && node vcast-ux-check.mjs`
   (37 PASS lines + BENCH line).
2. After deploy: open `/apps/vcast/displays.html` — expect the fleet
   line to immediately flag screens 2/4 as `stale · socket open, app
   silent` (they showed connected:true on the old code while last_seen
   was 6 days old).
