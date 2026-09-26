---
category: research
status: drafted 2026-09-26 — needs mn-home on-site measurement before build
---

# Public exit-node / VPN egress — findings + service plan

Context: can we route home networks through our public VPS for speed or a
fixed egress IP — and is this a service we could offer friends/customers?

## Benchmark (2026-09-26, from tony-home LAN vantage)

| path | latency | download | upload |
|---|---|---|---|
| direct WAN | ~7 ms | 357 Mbps | 70 Mbps |
| via idc01 (SSH SOCKS) | ~127 ms | 192 Mbps | 45 Mbps |

idc01 ceiling ~190 Mbps — loses to tony-home direct, could still beat a slow
residential line at mn-home (AIS) or sites with bad international peering.
Not measured at mn-home — **needs an on-device test there**.

## Capability already built

- idc01 has `ip_forward=1` + `tailscale set --advertise-exit-node` (routes
  `0.0.0.0/0` + `::/0` registered)
- Blocked at **tailnet admin approval**: Machines → idc01 → Edit route
  settings → check "Exit node". After approval any tailnet device can
  `tailscale set --exit-node=idc01` opt-in.
- Zero-downtime today — advertisement is inert until approved/used.

## Service idea (friends & customers)

"Managed egress" product shape:
- Customer device(s) join our tailnet or run a dedicated WireGuard profile
- Traffic exits via our VPS: fixed IP, filtered, optionally split-tunnel
  (only international traffic through us)

**Constraints to size around:**
- idc01 is 2 vCPU / 12G / 100G with **metered bandwidth** — one household can
  eat a month's transfer. CPU is fine (WireGuard is cheap), bandwidth is the
  bill.
- Current panel: 17.9G IN / 33.4G OUT cumulative — check the plan's transfer
  cap before offering this to anyone.

## Options to grow

1. **Bump idc01** — RAM upgrade already applied in panel (still 12G until a
   full power-off/on — pending). Bandwidth cap is the real question, not RAM.
2. **Second VPS in-region** — another Thai VPS for redundancy + capacity.
3. **VPS outside Thailand** (SG/JP/US) — gives a **foreign egress IP**:
   better for geo-blocked content and can have superior international
   transit; for domestic Thai traffic it's a detour. Right fit if the
   customer's pain is geo/IP, not raw speed.

## Cloudflare — risk-free test plan

Hard rule from the 2026-09-24 incident (`ssot.learning.idc01-warp-tailscaled`):
**never run `warp-svc` on a host that also runs `tailscaled`** — WARP starves
the userspace networking stack and kills the tailnet edge silently.

Safe ways to test:

1. **WARP on a spare/throwaway device** (old laptop, test VM, a $5 VPS) —
   never on a tailscale host. Measure WARP vs direct vs our-VPS exit from the
   same vantage.
2. **`cloudflared` tunnel** is safe everywhere — it's an outbound service
   tunnel, doesn't fight tailscaled. Different product direction though:
   it *publishes* services, doesn't give egress.
3. **Customer-side WARP** — if the goal is "better egress for a friend's
   device", the client just installs 1.1.1.1/WARP themselves; our involvement
   is zero-risk setup help, no server changes.
4. Optional namespace isolation: run WARP inside a dedicated podman container
   with its own netns on a non-tailscale host — still avoid mixing on hosts
   that carry tailscaled.

## Next actions

- [ ] Tony: approve exit-node route in tailnet admin (one checkbox)
- [ ] On-visit: speedtest at mn-home direct vs via idc01 exit-node
- [ ] Check idc01 plan bandwidth cap before any customer pilot
- [ ] Price a small SG/JP VPS for the foreign-egress variant
- [ ] Try WARP only on a throwaway host if we ever need it
