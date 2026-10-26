# Dispatch outcome — tony-ha prod placement decision

**Card:** tony-ha-prod-placement-26f033 · **Runner:** mn01 · **Date:** 2026-10-26

## What was produced

- `docs/ssot/jobs/home-assistant/2026-10-26-tony-ha-prod-placement-decision.yml` —
  full researched decision doc (evidence, options, move sketch, follow-ups).
- Board request raised on the card (`prod-tony-ha-host-a-mn01-recommended-if-bbf110`)
  with options a/b/c — Tony can answer one word. Comment posted with the summary.

## Finding

Verified live from mn01 (the dispatch runner):

- **mn01 is on the home LAN** — enp1s0 = 192.168.2.75, wifi = 192.168.2.81
  (the `ssot.values.yml` note saying "mn-home 192.168.1.0/24" is stale).
  Reaches TONY-TV cast at 192.168.2.85:8008 live. Physically viable — confirmed.
- **tony-ha on omen is up** — `https://tony-omen.taila0626a.ts.net:8123` → 200;
  idc02 stable front → 200 (the OPS-0725 front makes a backend move a
  one-line upstream repoint).
- **mn01 is the home-vision box already** — google-home-mcp, yolo-xiaomi,
  weaviate-embedding, xmeye-vms stack. tony-ha+go2rtc fit its identity;
  ~1G RAM on 7G total is feasible but the box is warm (transient load
  spikes from Wine VMS sessions).
- **Caveat found:** mn01's "always-on" claim is aspirational — SSOT says
  "off-net is normal for it" (unreachable Oct 14 & 16, ~3-day tailnet outage
  Oct 14–17). It has been up 6 days since its Oct 20 boot and GNOME won't
  auto-suspend; the role needs a real commitment (BIOS AC-restore +
  leave-powered), not just an assumption.
- **Option (c) idc03 rejected** — kills LAN device control (cast, go2rtc
  RTSP cams, esphome, LAN plugs, mDNS discovery) and idc03 is under a
  saturation watch.

## Recommendation

**(a) mn01** — conditional on Tony committing it to always-on duty.
If that commitment isn't real, **(b) keep omen** is the honest fallback
(declared lan-hub, headless 24/7 since Oct 23) with mn01 demoted to the
already-carded cold standby (HOM-0855, retargeted).

## How to verify

- Read the decision doc at the path above.
- Card request `prod-tony-ha-host-a-mn01-recommended-if-bbf110` holds the
  pending question; answer recorded on the card when Tony replies.

## Follow-ups carded in the doc

Migration card (if a), `ssot.host-capacity.yml` placement-policy update,
`ssot.values.yml` mn01 note fix, DHCP reservation for mn01's wired IP,
HOM-0855 cold-standby retarget to the losing host.
