# International Hosting Providers — latency-checked shortlist

**Status: For anything Ada-facing or interactive from Thailand, Singapore-region
providers measure ~30 ms from the home uplink and Hong Kong ~62–70 ms — EU
providers are 190–280 ms, batch-workload-only. Thai DCs still win at ~7 ms;
nothing offshore beats the prior report's ReadyIDC pick for local use.**

## Latest

- **2026-10-07** — First edition. Latency column is ICMP-measured from
  tony-dell (Thailand home uplink) where a public test target exists, and
  labelled *published* where it comes from a provider looking glass /
  latency table. Companion to the
  [Hosting Provider Assessment](https://idc03.taila0626a.ts.net/cms/#/hosting-provider-assessment)
  (Thai shortlist: ReadyIDC / Contabo / Hetzner for idc02).

Sections: [Measured — Thailand uplink](#measured--thailand-home-uplink) ·
[By target location](#latency-by-target-location-published--estimated) ·
[Providers](#candidate-providers) · [Method](#method--sources)

## Measured — Thailand home uplink

ICMP echo, 3 probes, averaged, from `tony-dell` on 2026-10-07 ~21:20 +07.
Single-ISP snapshot (home uplink, Bangkok-metro routing) — treat as
indicative, not a procurement benchmark.

| Provider / target | Region | Avg RTT | Source |
|---|---|---|---|
| Siamdata — idc01 (157.85.110.99) | Thailand (Bangkok) | **6.9 ms** | measured |
| AWS — `dynamodb.ap-southeast-1.amazonaws.com` | Singapore | **29.7 ms** | measured |
| Vultr — `sgp-ping.vultr.com` | Singapore | **29.9 ms** | measured |
| Akamai/Linode — `speedtest.singapore.linode.com` | Singapore | **37.4 ms** | measured |
| AWS — `dynamodb.ap-east-1.amazonaws.com` | Hong Kong | **62.4 ms** | measured |
| Dataplugs — test IP `103.199.106.17` | Hong Kong | **69.6 ms** | measured |
| Akamai/Linode — `speedtest.frankfurt.linode.com` | Frankfurt, DE | **188.6 ms** | measured |
| Vultr — `fra-de-ping.vultr.com` | Frankfurt, DE | **194.7 ms** | measured |
| OVH — `proof.ovh.net` | France | **216.5 ms** | measured |
| OVH — `ping.ovh.net` | France | **255.3 ms** | measured |
| Hetzner — `fsn1-speed.hetzner.com` | Falkenstein, DE | **275.8 ms** | measured (jittery, mdev 14 ms — likely suboptimal routing on this ISP) |

No-ICMP endpoints (filtered, not dead): DigitalOcean `speedtest-*`,
Hetzner `speed.hetzner.de` / `nb1-speed`, Vultr `nrt`/`lax`, GCP
`gcping.com` (HTTP-only ping tool), Oracle speedtest.

## Latency by target location (published / estimated)

All figures in this section are **published or estimated** — only the
Thailand column above is measured by us.

**Philippines (Manila)** — Philippine traffic for SEA is best served from
Hong Kong or Singapore; both are one submarine hop away.

| Destination | RTT | Source |
|---|---|---|
| → Hong Kong DC | ~17–45 ms | published: Dataplugs looking glass 21 ms, Zenlayer Manila 32 ms, Tencent SEA matrix 45 ms |
| → Singapore DC | ~25–51 ms | published: Tencent 25 ms, Zenlayer 38 ms, WonderNetwork ~51 ms |
| → Frankfurt | ~141 ms | estimated (OnionVPS Manila table — great-circle floor) |

**Norway (Oslo)** — Nordics peer into EU core; Asia is a far hop.

| Destination | RTT | Source |
|---|---|---|
| → Frankfurt / German DCs | ~25–35 ms | published-typical (Oslo–FRA fibre norms) |
| → Helsinki (Hetzner FI) | ~15–25 ms | published-typical |
| → Singapore | ~170–190 ms | estimated |
| → Hong Kong / Thailand | ~200–240 ms | estimated |

**Germany** — local DCs are effectively free latency-wise; Asia is long-haul.

| Destination | RTT | Source |
|---|---|---|
| → Hetzner FSN/NBG, OVH DE, AWS eu-central-1 (FRA) | ~1–15 ms | published-typical |
| → Singapore | ~155–180 ms | published-typical |
| → Hong Kong | ~175 ms | published: Dataplugs looking glass (Frankfurt→HK-DC) |

**Thai locations** — all international transit from Thailand concentrates
in Bangkok (SG/HK submarine gateways); upcountry sites pay only the
domestic backhaul delta on top of the Bangkok numbers.

| Site | → Thai DC (e.g. idc01) | → Singapore | → Hong Kong | → EU (FRA) | Source |
|---|---|---|---|---|---|
| Bangkok | ~5–10 ms | ~30 ms | ~62–70 ms | ~190–276 ms | measured (tony-dell uplink = Bangkok-metro routing) |
| Chonburi | ~6–12 ms | ~31–33 ms | ~63–73 ms | ~190–280 ms | estimated — Bangkok + ~1–3 ms domestic |
| Khao Yai | ~8–15 ms | ~32–35 ms | ~65–75 ms | ~192–282 ms | estimated — Bangkok + ~2–5 ms domestic |

## Candidate providers

| Provider | Relevant regions | Rough entry price | RTT class from TH (measured) | Fit |
|---|---|---|---|---|
| **Vultr** | SG, JP, FRA, … | ~$6–24/mo VPS | ~30 ms (SG) | Best price/perf for a Singapore node; per-hour billing |
| **Akamai/Linode** | SG, FRA | ~$5–24/mo | ~37 ms (SG) | Same tier as Vultr; predictable pricing |
| **AWS** | ap-southeast-1 (SG), ap-east-1 (HK) | Lightsail $5+, EC2 higher | ~30 ms SG / ~62 ms HK | Mature, but bandwidth pricing punishes chatty workloads |
| **DigitalOcean** | SG, FRA | ~$6–24/mo | no public ICMP target — expect ~30–45 ms SG (published) | Same tier; verify with their speedtest before buying |
| **Dataplugs** | Hong Kong (dedicated, CN2/BGP) | dedicated ~US$99+/mo | ~70 ms (HK) | HK dedicated/bandwidth-heavy role; overkill vs a small VPS |
| **Hetzner** | FSN/NBG (DE), HEL (FI), SIN cloud | €4.5–23/mo | ~276 ms (FSN, jittery path) | Best EU value; Asia-facing only via its pricey SIN cloud |
| **OVH** | FR/DE/CA, SG via OVHcloud | €4–15/mo | ~216–255 ms (FR) | Cheap EU; too far for interactive Thai use |
| **Contabo** | DE/SG/US | ~€5–11/mo | not measured; SG region exists | See prior assessment — CPU-steal caveat stands |
| **ReadyIDC / Siamdata** | Thailand | ~฿800/mo | ~7 ms class (idc01 measured) | The local pick — see prior assessment |

## Takeaways

- **Region beats provider.** From Thailand: TH ~7 ms → SG ~30–37 ms →
  HK ~62–70 ms → EU ~190–280 ms. Pick the region for the audience, then
  the cheapest reputable provider in it.
- **Singapore is the offshore sweet spot** for Thai/SEA-facing services;
  Hong Kong only if the audience includes China/Philippines north-SEA.
- **Philippines users**: HK or SG both land ~20–50 ms — a Manila DC
  (Zenlayer/local) only matters for sub-10 ms requirements.
- **Norway/Germany users**: EU providers (Hetzner, OVH, netcup, AWS
  eu-central-1) at ~5–35 ms; never serve them from SG/HK interactively.
- **For the idc02-class role** (batch, indexing, lab): EU value is real
  but the measured 190–280 ms hurts admin/interactive sessions — the
  prior report's "EU fine for batch" holds.

## Method & sources

- **Measured**: ICMP echo request ×3, averaged, from tony-dell
  (Thailand home uplink), 2026-10-07 evening +07. Endpoints that filter
  ICMP are listed as such — absence is not a down signal.
- **Published**: Dataplugs looking glass (dataplugs.com/en/company/looking-glass),
  Zenlayer Manila DC latency table, Tencent Cloud SEA latency matrix,
  OnionVPS Manila RTT estimates (great-circle floors), WonderNetwork
  Manila↔Singapore.
- **Estimated**: Khao Yai / Chonburi deltas and Norway→Asia figures are
  geography-based estimates, labelled as such.
- Single-evening, single-ISP snapshot — run provider looking glasses
  before committing spend.

---
*Generated by devin-dispatch (card hosting-provider-intl-report) · 2026-10-07 ·
sources: measured ICMP (tony-dell) + provider looking glasses/latency tables*
