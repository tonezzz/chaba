# Dispatch outcome — gev-google-maps-key-suspect-dead-verify-be569a (attempt 2)

## What this run did

Attempt 1 (17:38) completed the verification but left its deliverables
uncommitted, so merge-sweep marked it NOT-verified. Tony then answered
the board request `gcp-console-needed-no-gcloud-on-any-flee-53b8a6`
with **"proceed"** (18:44), which re-queued the card.

This run:

1. Re-verified the fleet-wide gcloud gap: `gcloud` absent and no
   `~/.config/gcloud` on **idc03, mn01, con01, tony-omen** (attempt 1
   had checked tony-macbook/tony-dell/idc02). Every fleet host is
   console-blocked — "proceed" cannot mint a key from here; the GCP
   console step remains Tony's.
2. Ported attempt 1's verified findings into this worktree and
   **committed them** (the actual fix for the failed verification):
   - `docs/ssot/infrastructure/ssot.secrets.yml` — `gev-google-maps`
     entry updated: 2026-11-24 verification note (live bundle is
     deliberately keyless, not a silent fallback), the
     tile.googleapis.com OAuth2-only finding, and the new idc02 `.env`
     slot.
   - `docs/ssot/jobs/gev/2026-11-24-gev-google-maps-key-verify.yml` —
     full findings trail + attempt-2 gcloud re-check.
   - this outcome file.
3. Merged `origin/master` into the dispatch branch first (was 38
   behind) so the checkpoint/single-writer gate passes.

## Findings (unchanged from attempt 1, now committed)

- **Q1 — does GEV render Google layers?** No — and not via silent
  fallback. The live `/apps/gev` bundle (`index-Bd5DfCi5.js`, staged via
  `stacks/web/public/apps/gev`) bakes in
  `googleApiKey: void 0, cesiumToken: void 0`; it runs the documented
  keyless Esri World Imagery + OSM globe by design.
- **Q2 — key renewal:** the AQ.Ab8… key is dead for all Maps Platform
  endpoints, AND `tile.googleapis.com/v1/3dtiles` rejects *every* API
  key (OAuth2-only, upstream `bilawalsidhu/gods-eye-view#59`) — a fresh
  Maps key cannot restore GEV photoreal 3D. For the ada `map_embed`
  lane a fresh restricted key (Embed+Static+Geocode+Routes) still
  helps; that mint is a GCP-console-only step for Tony.
- The dead key still sits in `~/gods-eye-view/.env` on tony-dell AND
  idc02 (idc02 slot now recorded in SSOT); it only feeds server-side
  Places/StreetView calls, which degrade to Nominatim.

## Board state

- Progress + final comms posted to the card.
- Request `gcp-console-needed-…-53b8a6` is already `answered: proceed`.
  Remaining Tony step (console-only): enable Maps Embed + Static +
  Geocode + Routes on a billing-backed GCP project, mint a restricted
  key, drop it into `~/.config/secrets/tony-ha/backend.env` on idc03,
  `systemctl --user restart ada-ha-tony`. GEV photoreal is a separate
  decision (Cesium ion token vs OAuth tiles-token impl vs stay
  keyless) — a plain Maps key will not fix it.

## How to verify

```
# this branch carries the SSOT/jobs trail:
git log --oneline origin/master..HEAD
git show HEAD:docs/ssot/infrastructure/ssot.secrets.yml | grep -n "gev-google-maps" 
python3 -c "import yaml; yaml.safe_load(open('docs/ssot/infrastructure/ssot.secrets.yml'))"
# live bundle still keyless:
ssh idc02 'grep -o "googleApiKey:void 0" ~/web-srv/public/apps/gev/assets/index-Bd5DfCi5.js | head -1'
```

lessons:
- Dispatch checkpoint fails "session produced no commits" when the
  agent leaves deliverables uncommitted in the worktree — commit SSOT/
  outcome files on the dispatch branch before ending, and merge
  origin/master first if the worktree is far behind.
- "proceed" on a board request does not create fleet capability: with
  no gcloud/GCP creds on ANY host, console-gated steps stay Tony's —
  say so plainly instead of re-asking.
- tile.googleapis.com 3D Tiles is OAuth2-only; API-key probes on Maps
  Platform endpoints say nothing about it.
