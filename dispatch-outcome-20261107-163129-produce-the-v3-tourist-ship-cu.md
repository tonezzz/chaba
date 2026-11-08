# dispatch-outcome — produce the v3 tourist-ship cut (doc-pilot-v3-tourist-cut)

## Result

Produced **v3-static-final-v1**, the complete private static cut of the
approved v3 tourist-ship solar-system doc for KK:

- https://drive.google.com/file/d/12BbrvSDURkUxzmvx6orXqJIeayXfYI6Q/view
- `gdrive:ada-nest/doc-pilot/review/v3-static-final-v1.mp4` — 65.728 s,
  640x384@24, H.264/AAC + mov_text Thai soft-subs
- `v3-static-final-v1-report.md` and
  `subtitles-th-v3-static-final-v1.srt` alongside; sha256
  `182dd336e7d810c4b23539b65f8dc42fec1378f94555187c5c643103454a2662`

Every shot now carries a rights-checked NASA plate or a deliberate
schematic — **no placeholder planets remain**, which was the main gap
in the previous review cut v2.

## What was done (vs the card's remaining steps)

1. **VO verified**: all 18 wavs in `doc-pilot/vo-v3/` re-checked on
   idc02 — finite, non-silent (peaks 0.53-0.74), durations 1.91-4.52 s,
   `fails: none`.
2. **Storyboard/manifest**: `visual-manifest-v3-draft.yml` updated on
   Drive (r14): `static_final_v1` section + per-shot asset_status now
   records exact asset IDs/credits for all 18 shots.
3. **NASA asset+rights**: resolved the open items — Moon PIA00405
   (natural-color Galileo, replaced misleading false-color PIA00075),
   Sun PIA26681 (SDO), Venus PIA23791 (Mariner 10, right-disk crop),
   Mars GSFC_e000332 (Hubble portrait, replaced polar mosaic PIA02992),
   Jupiter PIA04866 (Cassini), GRS PIA21772 (JunoCam/J.Major, enhanced-
   color labeled). Pluto stays PIA20291 (PIA19857 403 excluded). All
   SHA-256 + credits recorded in `v3-assets/nasa/asset-manifest.md`.
4. **Renders**: CPU 2.5D done here on idc02 (GPU not required for
   stills). No live GPU lane existed — Colab queue heartbeat stale since
   ~Oct 29 (Tony-attached runner); KK-Mac last check Nov 2 blocked by
   owner app. Shots 8/9 use the **approved static fallback** NASA plates;
   their LTX prompts remain in the storyboard for a T4/clear Mac window.
5. **Assembly**: rebuilt the lost 2.5D compositor from scratch (prior
   versions died in unmerged dispatch worktrees) — now durable at
   `scripts/colab/packs/doc-static-final-v3/` (build script + pack.yml).
   Holds matched to measured VO; Thai burned-subs + mov_text + SRT;
   fact callouts baked per shot; recurring ship silhouette; cockpit
   window on POV shots 1/17; Kuiper digit tofu fixed; Pale Blue Dot
   lifted with an approximate-position marker (labeled as such).
6. **QC (flow-assessment-v1)**: full decode clean, 1577 frames =
   65.7 s, audio mean -21.7 dB / peak -2.6 dB, all 18 SRT cue starts
   match measured VO offsets, fact callouts verified verbatim vs the
   approved script object table.
7. **Education post 2157** (`lesson-1fa6858c7a4d`) updated in place —
   v3 status section appended EN+TH; post stays private.

## Constraints honored

- Shipped v6 cut and v0/v1 script assets untouched.
- No push to remotes; committed only on the dispatch branch.
- No public release — everything remains private review material.

## Still open (for the next session / Tony)

- LTX dynamic renders for shots 8/9: needs Colab T4 (Tony attaches the
  runner) or a clear KK-Mac window (staged packs remain; owner-app gate
  was doing its job on Nov 2).
- Tony/KK viewing + acceptance; music bed; EN subs (deferred, ADA-0510);
  per-asset public-rights pass before any release.

## Verify

- Play the Drive link above; compare shots 3/4/6/7/8/9/15/17 against
  `v3-static-review-cut-v2.mp4` — placeholders and tofu are gone.
- `ffprobe` the mp4: h264 + aac + mov_text, 65.728 s.
- Rebuild locally: stage inputs per `pack.yml`, run
  `build_v3_static_final.py`.
- Job note: `docs/ssot/jobs/nest/2026-11-07-docpilot-v3-static-final.yml`.
