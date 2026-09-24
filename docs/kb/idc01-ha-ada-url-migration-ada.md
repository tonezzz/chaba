# Analysis: Migrating Home Assistant and Ada Public URLs to idc01

This document outlines the pros and cons of moving the public entry points for Home Assistant and Ada from their current location on `mn01` to `idc01` (Siamdata VPS, tailnet node 100.74.146.0).

## Current Architecture
- Ada is public via `mn01` Tailscale Funnel.
- `tony-ha` is tailnet-only.
- `idc01` has tailscale serve on tailnet only, no funnel enabled.

## Pros

*   **Consolidation:** Moves public-facing component to a dedicated, public-facing VPS (`idc01` has a static public IP), potentially simplifying network management and decoupling public access from internal node `mn01`.
*   **Availability:** VPS generally has higher availability and more reliable direct network access than a residential connection subject to ISP whims.

## Cons

*   **Increased Latency:** Moving the entry point to `idc01` introduces an additional network hop for the voice websocket (User -> `idc01` -> tailnet to `mn01`). This likely increases voice response latency.
*   **Origin Change:** A new public URL means the browser context (origin) changes. This will **invalidate device-bound API keys** stored in browser `localStorage` and will require re-installation of installed PWAs.
*   **Migration Effort:** Requires configuring `tailscale serve`/`funnel` on `idc01`, updating DNS, updating Ada's configuration, and migrating user data across all devices.
*   **Security Exposure:** Enabling public ingress on `idc01` presents fresh attack surface to the internet.

## Recommendation

Due to the increased voice latency and the breaking changes for users (PWA reinstall, API key invalidation), **migration is not recommended** at this time unless direct `mn01` ingress becomes untenable, or if `idc01` provides tangible performance gains outweighing the extra hop. The current configuration on `mn01` via Tailscale Funnel appears optimal for balancing security, latency, and operational simplicity.