---
category: operations
---

# Phase 9 — Tailscale Client Auto-Updates (Selected)

Enable automatic Tailscale client updates on all nodes so security patches and bug fixes apply without manual intervention.

- Command on Linux: `tailscale set --auto-update`
- Package-manager alternative: keep the `tailscale` package on the stable repo and enable the OS’s unattended-upgrades mechanism.
- Status: **selected for implementation**.

### Why

Keeps the tailnet secure and reduces operational toil on each node. For a single-node setup this is low risk; for multiple nodes it should be combined with a maintenance window or update notifications.

### Risks

- An update could introduce a breaking change on a remote/headless host.
- Mitigation: test updates on `tony-omen` first and keep a local console/SSH backup path.

## Future (not now)

- **Exit node** — make `tony-omen` an exit node for secure mobile internet routing. Useful, but not required until you want to route all remote traffic through home.
- **Headscale** — self-hosted Tailscale control plane. Only if you want to remove the cloud coordination server dependency.

## Appendix: Post-Rollout Merges (PR #4)

Following the Tailscale rollout, the same `tailscale-funnel-connections` branch was used to merge additional infrastructure and SSOT documentation updates. These are now in `master` at `13d7b08`.

- **`docs/ssot/apps/ssot.apps.playlive.yml`** — documented the multi-host PlayLive setup, with `playlived` on `tony-omen:9231` and `tony-dell:9230`, remote CDP override for `tony-dell`, and offloading of UI verification to `tony-dell`.
- **`docs/ssot/infrastructure/ssot.health.yml`** — added a `barrier-server` health check for the Barrier KVM server on `tony-omen`, including `systemctl` state checks, port checks, and recovery actions. The Barrier client on `tony-dell` connects to `100.75.102.88:24800` over the tailnet.
- **`docs/ssot/ssot.mysystem.home.yml`** — updated `tony-omen.local` LAN IP to `192.168.1.51`, corrected the Barrier client binary path to `/home/tony/.local/bin/barrierc`, and documented the auto-fix commands.
- **`stacks/web/public/apps/trade/tradecanvas-ui/`** — added `CurrencySelector` component and API data status to TradeCanvas (`chart-loader.js`, `compare2.html`, and new `ui-components.js`).

### Why this is in scope

The `barrier-server` health check is a direct tailnet consumer: it verifies that the Barrier client on `tony-dell` can reach `tony-omen` over the `100.x` Tailscale address. Keeping these notes in the Tailscale KB makes the operational relationship explicit.

