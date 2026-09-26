---
kind: note
status: active
subject: lab-stack
attribute: review-comparison
---

# Lab stack — dual review comparison (Devin vs Ada)

Date: 2026-09-26. Compares two independent reviews of the lab-stack plan
(test-stack-plan.md): Devin's GitHub-ecosystem research vs Ada's
memory-bank + model-knowledge review.

## Ada's report (verbatim, via ada_remember)

> "Review of lab stack plan: Pros include safe isolation for testing
> containers and Home Assistant changes without affecting production
> data. Cons are resource overhead on the host and the challenge of
> keeping the lab state realistically synced with production for
> accurate tests. New ideas: consider scheduled, ephemeral test
> environments that spin up on demand to save resources, and automate
> the sync of sanitized production data subsets for more realistic
> container testing."

Note: Ada has no web/GitHub search tool — her review is memory-bank +
model knowledge. (Her write misrouted — see write-hygiene note below;
this doc is the canonical copy.)

## Devin's report (GitHub research, round 2)

Ecosystem splits into four fidelity tiers:

- L0 unit: `pytest-homeassistant-custom-component` (in-process hass)
- L1 ephemeral container: `ha-testcontainer`, `hass-taste-test`
- L2 pod stack: **our lab plan**
- L3 full OS: `ha-mcp` pre-baked HAOS qcow2 pipeline (QEMU/KVM,
  scripted onboarding, addon installs, OCI artifact)

Ideas adopted:

1. **Toxiproxy sidecar** in the pod — deterministic latency/reset/bandwidth
   faults between ada-lab↔lab-mddb/lab-ha. Plain-HTTP only (matches our
   pod traffic). Turns the lab into a resilience rig — the exact class of
   production pain we've hit (embedding timeouts, HNSW rebuilds, WARP
   outages). Refs: Shopify/toxiproxy, aygp-dr/fault-injection-lab.
2. **Visual snapshot tests** for chaba cards — hass-taste-test pattern
   (isolated HA + Lovelace resources + image snapshots), or drive via
   existing playlive/chrome-devtools.
3. **Golden-image precedent** — ha-mcp's pre-baked qcow2 validates our
   golden-tar approach at container tier.
4. **Version matrix** — lab-ha pre-flights the next HA image tag
   alongside prod's pinned version (unifi-network-maps-ha pattern).
5. **fetch_component/fetch_plugin** — pull exact prod versions of
   card-mod/HACS assets for lab parity.
6. Minor: `podman quadlet install` `.quadlets` single-file bundle for
   one-shot install of stacks/lab/.

## Comparison

| Aspect | Ada | Devin |
|---|---|---|
| Isolation pro | yes | yes |
| Resource overhead con | yes | yes (7.8 GB budget, cgroup limits) |
| Realism/state-sync con | yes — **periodic sanitized prod sync** | partial — static golden tar only |
| On-demand/ephemeral lifecycle | **yes — spin up on demand** | implied (lab-reset), not foregrounded |
| Fault injection | — | toxiproxy sidecar |
| Visual/card regression | — | hass-taste-test pattern |
| Full-fidelity option | — | HAOS qcow2 (deferred) |
| Upgrade pre-flight | — | HA version matrix |

## Merged deltas → plan v5

Both reports converge: the design is sound; gaps are complementary.

- **[Ada] On-demand lifecycle**: `lab-up`/`lab-down` — pod only runs
  during test sessions; directly answers the idc01 RAM constraint.
  Default state = stopped, not always-on.
- **[Ada] `lab-refresh.sh`**: periodic sanitized prod→lab data sync
  (scrubbed mddb bank export + ha-config snapshot) — living realism
  instead of a stale golden tar. Pairs with golden tar: tar is the
  baseline, refresh is the update path.
- **[Devin] lab-toxiproxy**: optional pod member for fault-injection
  scenarios (degraded-mode, reconnect, outage tests).
- **[Devin] M6 optional**: visual snapshot regression for chaba cards.
- **[Both] Keep**: .pod+.container quadlets, pinned tags, pod-local
  Ollama, golden tar, namespaced collections/secrets/ports.

## Write-hygiene findings (for the record)

- Ada's second `ada_remember` duplicated the review into
  `personal-testo` (wrong bank, cross-person scope) — cleaned up;
  bank-arg discipline needs watching. The intended tony-projects write
  was silently deduped/absorbed — the doc never got its own key, so
  this comparison doc carries her content canonically.
- Same `confirmed: true` self-approval observed as before — the write
  gate is currently model-attested, not enforced.
