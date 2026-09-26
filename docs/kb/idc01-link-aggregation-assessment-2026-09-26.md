# idc01 Link Aggregation Assessment — Final Recommendation

Distilled from Devin session `good-gosling` (2026-09-22, continued through the
SSOT commit) and the follow-up incident on 2026-09-24. Live state re-verified
2026-09-26.

## Question

Can idc01's effective bandwidth be increased by bonding the available
WiFi/mobile connections, and is it practical? A secondary question settled in
the same session: should idc01's public IP be stored in SSOT via
`${ssot(...)}`/`__ref__` dynamic references?

## Host facts

- **idc01 is a VPS** (Siamdata Communication, Bangkok) — Ubuntu 24.04,
  2 vCPU, kernel 6.8. It has **no radios**; WiFi/mobile bonding cannot
  happen on idc01 itself.
- Tailnet: `100.74.146.0`; public edge via a dedicated Siamdata IPv4
  (masked in SSOT per data-isolation — resolve live with
  `tailscale status` CurAddr or the Siamdata panel).
- Direct tailnet path from tony-dell: ~7 ms RTT, no DERP relay.
- Role: public web edge (Caddy :80/:443) + MDDB replica + Ada backends.
  Detail: `docs/ssot/infrastructure/ssot.security.idc01.yml`;
  unmerged host card `ssot.idc01.yml` on branch `test/ultralytics-yolo-ha`
  (commit `1eb2138c`).

## Measured baseline (2026-09-22)

| Path | Result |
|---|---|
| tony-dell → idc01, single TCP flow (21 MB via MDDB API) | ~280 Mbps up / ~250–310 Mbps down |
| Same, 4 parallel flows | ~302 Mbps aggregate — **no scaling** |
| idc01 → Cloudflare BKK edge | ~78 Mbps via `import-url`; ~229 Mbps direct from shell |
| idc01 → international, single flow | 2–5 Mbps (Tele2 SE 2.8, Gutenberg US 10.2, GitHub CDN 95) |
| idc01 → international, 4 parallel | ~8.8 Mbps aggregate — **linear scaling** |
| Control: kernel.org CDN from home | ~55 Mbps/flow (distance/RTT-limited) |

Interpretation:

- **Inbound/domestic is capped at ~300 Mbps by the destination path** (idc01's
  VPS port/plan or domestic peering) — a single flow already fills it, parallel
  flows don't add. Aggregation on the client side cannot exceed it.
- **International egress is per-flow limited, not pipe-limited** — parallel
  streams scale linearly. That's a TCP-window/per-flow-shaping signature, not
  a thin pipe.
- **MDDB ingestion is app-limited, not network-limited**: a 21 MB doc took
  >120 s to store (embedding/FTS on 2 vCPUs) while the same bytes crossed the
  wire in 0.6 s. Huge single documents serialize MDDB's store pipeline —
  effectively a self-DoS.

## Options analyzed

| Approach | Pros | Cons |
|---|---|---|
| Failover (route metrics) | Simple, reliable | No bandwidth gain |
| ECMP / mwan multipath | Free; sum-of-links for *parallel* flows | Single flow never exceeds one link; public-IP flapping breaks sticky sessions; rp_filter/NAT fiddling |
| MPTCP / OpenMPTCProuter | Real per-flow bonding + seamless failover | Needs remote aggregation endpoint; sub-additive with LTE jitter (~1.2–1.6× best link); added latency; maintenance |
| Speedify | Zero config | Subscription; their exit IPs; latency |

**The Tailscale wrinkle:** all traffic to idc01 rides `tailscale0` — one UDP
flow pinned to one WAN path. Tailscale does no multipath, so ECMP on the
client does nothing for tailnet traffic. Bonded Tailscale would require a
bonding tunnel *under* Tailscale (OMR carrying Tailscale's UDP) — a whole
extra layer.

## Verdict: link aggregation — not worth it for idc01

- Already at the ~300 Mbps destination cap **per flow**; bonding cannot raise it.
- Tailscale pins traffic to one path anyway.
- WiFi+LTE bonding is sub-additive and adds latency/jitter that hurts the
  interactive/voice workloads (Ada, speaker-enroll) on idc01.

Where a second link *would* still pay off:

- **Failover** — mobile as backup WAN at home; cheap, high value.
- **Traffic splitting** — route bulk international traffic over mobile, keep
  the primary link clean for tailnet.
- Only revisit bonding if the ~300 Mbps cap turns out to be the home ISP plan
  rather than idc01's port.

## What was actually done about idc01's international egress

1. **2026-09-22 — Cloudflare WARP deployed** (after gaining shell via
   tony-omen's authorized key; tony-dell key then added — direct
   `ssh tony@100.74.146.0` works). Tailnet + peer-endpoint exclusions set;
   **BBR+fq enabled persistently** (`/etc/sysctl.d/90-bbr.conf`). Worst-case international improved ~3–10× (Tele2 2.8→10.5,
   OVH ~3→35.5 Mbps); CDN traffic unchanged.
2. **2026-09-24 — WARP disabled.** warp-svc starved tailscaled twice in one
   day (tailnet edge dead: serve proxy, MagicDNS, tailscale-ssh all wedged
   while the host looked alive). Documented in
   `docs/ssot/ssot.learning.idc01-warp-tailscaled.2026-09-24.yml` and the
   `egress.warp` deviation in `ssot.security.idc01.yml`.
   **Verified 2026-09-26: `warp-svc` still `disabled`; BBR still active.**

### Current recommendation for idc01 egress (in order)

1. **Keep BBR** (already persistent) — free, part of the fix.
2. **Parallel-capable downloads** — `aria2c -x16` for big pulls; measured
   linear scaling means ~30–50 Mbps achievable with no proxy at all.
3. **Tailscale exit node via tony-dell** if a whole-system egress boost is
   needed: `tailscale set --advertise-exit-node` (tony-dell already has
   `ip_forward=1`) + `tailscale set --exit-node=tony-dell` on idc01. Costs
   home bandwidth, adds ~7 ms, changes idc01's egress IP to home.
4. **WARP re-enable — only with Siamdata console access in hand**, after
   verifying route exclusions/policy-routing can't starve tailscaled (or
   move to the free Zero Trust tier for managed enrollment). Do NOT flip it
   back on remotely; the 9-24 incident shows recovery needs the console.
5. **SG VPS relay** (~$4–6/mo) if none of the above suffice — best intl
   transit from Thailand.

## Decision: public IPs in SSOT — keep placeholders, no `${ssot(...)}`

The data-isolation scan (`ssot-optimize.mjs` in the pre-commit hook) rejects
hardcoded public IPv4 in **every** file under `docs/ssot/**`, including the
canonical `ssot.values.yml` — so there is no legal canonical home for a public
IP today. Options were ranked:

1. **Placeholders** (`<IDC01_PUBLIC_IP>`, matching `<IPHONE_USB_GATEWAY>`
   precedent) + "resolve live via `tailscale status` / Siamdata panel" —
   **adopted** (committed in `1eb2138c`).
2. Record the real IP in `devin-kb` (`docs/machines/idc01.md`) — outside the
   scan, durable — optional complement, still open.
3. Amend the linter (exempt `ssot.values.yml` or add an allowlist) —
   rejected: a project-wide rule change for one quasi-static address, and it
   weakens a check that has caught real stale-data bugs.

Why `${ssot(...)}` loses here specifically: the mechanism earns its keep when
a value is volatile, consumed by many places, and resolved by tooling. A VPS
public IP is static, appears mostly in narrative text, and its authoritative
source is live infrastructure — a committed copy can only drift. Unresolved
readers (`yaml.safe_load`, MDDB sync, `mcp_read_ssot`, humans) would see the
raw reference blob, which is worse than a self-describing placeholder.

## Artifacts and references

- Commit `1eb2138c` on `test/ultralytics-yolo-ha` (**unmerged**):
  `docs/ssot/infrastructure/ssot.idc01.yml` (new host card),
  `ssot.host-roles.yml`, `ssot.values.yml` idc01 entry with masked IP.
- `docs/ssot/infrastructure/ssot.security.idc01.yml` — listeners, ufw,
  egress/warp deviation (merged).
- `docs/ssot/ssot.learning.idc01-warp-tailscaled.2026-09-24.yml` — WARP +
  tailscaled starvation symptom signature.
- Job trail: `docs/ssot/jobs/infrastructure/2026-09-26-idc01-link-aggregation-assessment.yml`.

## Open follow-ups

- Decide whether `ssot.idc01.yml` (`test/ultralytics-yolo-ha`) should be
  cherry-picked to `master` — note its WARP section describes the 9-22
  enabled state; re-check against the disabled reality before merging.
- Optionally write `~/devin-kb/docs/machines/idc01.md` with the real public
  IP + Siamdata panel path (per decision option 2).
- If international egress still hurts, evaluate the tailscale exit-node
  option (cheap) before re-attempting WARP.
