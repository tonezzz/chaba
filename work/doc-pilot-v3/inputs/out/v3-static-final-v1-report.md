# v3-static-final-v1 — build + QC report

Date: 2026-11-07 (idc02 dispatch, card doc-pilot-v3-tourist-cut / OPS-0904)
Cut: `v3-static-final-v1.mp4` — 65.728 s, 640×384 @ 24 fps, H.264/AAC +
mov_text Thai soft-subs; sidecar `subtitles-th-v3-static-final-v1.srt`.
Status: **private review only** — not for public release.

## What changed vs v3-static-review-cut-v2

Every shot now uses a real rights-checked NASA plate or a deliberate
schematic — no procedural placeholder planets remain:

- Shot 3 Moon: PIA00075 false-color mosaic replaced with natural-color
  Galileo PIA00405 (was misleading for KK).
- Shot 4 Sun: schematic disk replaced with SDO PIA26681.
- Shot 6 Venus: procedural sphere replaced with Mariner 10 cloud view
  PIA23791 (right-disk crop; correct sulfuric-cloud framing).
- Shot 7 Mars: PIA02992 polar mosaic replaced with Hubble portrait
  GSFC_20171208_Archive_e000332 (reads as a planet, not petals).
- Shots 8/9 Jupiter + Great Red Spot: schematic placeholders replaced
  with Cassini PIA04866 and JunoCam PIA21772 (approved static fallback;
  LTX dynamic renders still pending a safe GPU lane).
- Shot 15 Kuiper: digit/Latin tofu glyphs fixed ("30-50 AU" now renders).
- Shot 17 Pale Blue Dot: source lifted for band visibility + marker ring
  and arrow at the Earth speck (approximate position, labeled as such).

## Per-shot manifest

| shot | dur_s | method | plate |
|---|---|---|---|
| 1 | 3.67 | cpu-composite | starfield + ship + cockpit window |
| 2 | 3.67 | NASA full-bleed | Blue Marble GSFC_20171208_Archive_e001016 (NASA Goddard) |
| 3 | 2.87 | NASA keyed disk | PIA00405 (NASA/JPL/USGS, Galileo) |
| 4 | 3.88 | NASA keyed disk | PIA26681 (NASA/GSFC/SDO) |
| 5 | 2.34 | NASA full-bleed | PIA18108 (NASA/JHUAPL/CIW) |
| 6 | 4.52 | NASA keyed disk | PIA23791 (NASA/JPL-Caltech, Mariner 10) |
| 7 | 3.24 | NASA keyed disk | GSFC_e000332 (NASA, ESA/Hubble) |
| 8 | 2.98 | NASA keyed disk | PIA04866 (NASA/JPL/SSI, Cassini) — static fallback for LTX |
| 9 | 3.40 | NASA full-bleed | PIA21772 (NASA/JPL-Caltech/SwRI/MSSS/J. Major) — static fallback for LTX |
| 10 | 1.91 | NASA keyed disk | PIA06193 (NASA/JPL/SSI) |
| 11 | 3.46 | NASA full-bleed | PIA06193 ring-plane crop (NASA/JPL/SSI) |
| 12 | 3.35 | NASA keyed disk | PIA18182 (NASA/JPL-Caltech, Voyager 2) |
| 13 | 3.35 | NASA keyed disk | PIA00046 (NASA/JPL, Voyager 2) |
| 14 | 3.56 | NASA keyed disk | PIA20291 (NASA/JHUAPL/SwRI, New Horizons) |
| 15 | 3.51 | schematic | original Kuiper-region map (30-50 AU band) |
| 16 | 4.20 | schematic | original scale map, explicitly not to scale |
| 17 | 3.83 | NASA still + marker | PIA00452 (NASA/JPL, Voyager 1) |
| 18 | 3.99 | NASA full-bleed | Blue Marble reuse + warm return tint |

## QC — flow-assessment-v1 rubric

- [x] All 18 VO clips decode, finite, non-silent (re-verified this
  session: peaks 0.53-0.74, durations 1.91-4.52 s, `fails: none`).
- [x] Shot holds = measured VO durations; no frozen-tail padding
  (1,577 video packets = 65.7 s @ 24 fps; every shot animates via
  2.5D zoom).
- [x] Subtitles = burned bar + mov_text track + SRT sidecar; all 18 cue
  starts verified against measured VO offsets (±0.05 s).
- [x] Fact callouts match the approved script table verbatim
  (AU/million-km/diameter per object; Moon distance from Earth; Kuiper
  30-50 AU region; scale-map disclaimer present).
- [x] Credits recorded per plate on screen and in the asset manifest;
  enhanced/processed imagery labeled (Mercury mosaic, JunoCam GRS).
- [x] Ship layer consistent, logo-free; cockpit window on POV shots
  1 and 17.
- [x] Full-file decode clean (`ffmpeg -f null` zero errors); audio
  mean -21.7 dB / peak -2.6 dB.
- [ ] Human review: Tony/KK acceptance — pending (private review).
- [ ] LTX dynamic upgrade for shots 8/9 — pending a safe GPU lane
  (Colab T4 or cleared KK-Mac window).

## Known limitations

- 640×384 review master, not presentation quality.
- Voyager/Hubble plates show their vintage processing; credits on screen.
- PIA00452 marker position is approximate (dot is ~2 px in source);
  labeled "(วงกลมชี้ตำแหน่งโดยประมาณ)".
- No music bed or EN subtitles (Thai-only lane per ADA-0510).
