# Solar-system v3 private NASA stills

Status: downloaded for the private storyboard/animatic only. The NASA Images API metadata provided a source credit but no explicit `AVAIL:Copyright` field for these records. Do not treat this as blanket public-release clearance; recheck each asset policy and credit before publication.

Storage: `gdrive:ada-nest/doc-pilot/review/v3-assets/nasa/`

| Shot | NASA ID / title | Credit | Source page | Image rendition | SHA-256 | Notes |
|---|---|---|---|---|---|---|
| 3 | PIA00075 — Moon Color Visualizations | NASA/JPL | https://www.jpl.nasa.gov/images/pia00075-moon-color-visualizations/ | `~small.jpg`, 640×344 | `c11ab767a31d552143a4e09ed1f059e33e7fe642dcc62565584d601744e9143e` | Enhanced spectral/false color; keep that distinction visible. |
| 5 | PIA18108 — The New Three-Color Mosaic | NASA/Johns Hopkins University Applied Physics Laboratory/Carnegie Institution of Washington | https://www.jpl.nasa.gov/images/pia18108-the-new-three-color-mosaic/ | `~small.jpg`, 640×639 | `4b3399a6e9c86187be4f5bfd96d686af46010a80c154032b5479d9dbbff44b30` | Surface mosaic/detail, not a natural-color full-globe photograph. |
| 7 | PIA02992 — Mars Digital Image Mosaic Globe | NASA/JPL/USGS | https://www.jpl.nasa.gov/images/pia02992-mars-digital-image-mosaic-globe/ | `~small.jpg`, 640×314 | `fafb6bff32a87a024864b20d746fc50993e011328d0fb504ec532ced40747fba` | Processed global mosaic; use as a mapped plate. |
| 12 | PIA18182 — Uranus as seen by NASA Voyager 2 | NASA/JPL-Caltech | https://www.jpl.nasa.gov/images/pia18182-uranus-as-seen-by-nasas-voyager-2/ | `~small.jpg`, 640×640 | `6f5a9fcb08831b48bc09d2c9f322d72a138f938ab9a91bf3c04e4b328d01b3cc` | Full-disk planetary view. |
| 13 | PIA00046 — Neptune Full Disk | NASA/JPL | https://photojournal.jpl.nasa.gov/catalog/PIA00046 | `~small.jpg`, 640×640 | `c454c1ab307b1424f5d3d6ed5a6ce84d3b745d3ab42edcc64d1f193951be3a5f` | Processed Voyager image; retain the source credit. |
| 14 | PIA20291 — Color Image of Pluto | NASA/Johns Hopkins University Applied Physics Laboratory/Southwest Research Institute | https://photojournal.jpl.nasa.gov/catalog/PIA20291 | `~small.jpg`, 640×640 | `5e898313022eef8068bb7d3dee3fe4b49996698de8a57d68c29b0082f08c21ae` | New Horizons color view; use as an illustrative plate. |
| 17 | PIA00452 — Earth as “Pale Blue Dot” | NASA/JPL | https://photojournal.jpl.nasa.gov/catalog/PIA00452 | thumbnail, 453×614 | `9b174ed0b288632dd82679080b517a1e4f6154746486eddffbb53f055f0b271c` | Preserve its original scattered-light context; do not imply it is unprocessed. |

## Added 2026-11-07 for v3-static-final-v1

| Shot | NASA ID / title | Credit | Source page | Image rendition | SHA-256 | Notes |
|---|---|---|---|---|---|---|
| 3 | PIA00405 — Earth Moon | NASA/JPL/USGS | https://images.nasa.gov/details-PIA00405 | `~medium.jpg`, 1280×1280 | `d5c9dad5406471cef07fa5f4803eda951b4385b96dd54b789d295e0f68183666` | Natural-color Galileo disk; replaces misleading PIA00075 false-color. |
| 4 | PIA26681 — Image of Sun From NASA's Solar Dynamics Observatory | NASA/GSFC/Solar Dynamics Observatory | https://images.nasa.gov/details-PIA26681 | `~small.jpg`, 640×640 | `966c829b12368d422e15da13c35962b13c3537dc013dcb6e99a3e61a7f92df60` | SDO/AIA 171 Å view 2025-09-10; embedded timestamp retained. |
| 6 | PIA23791 — Venus from Mariner 10 | NASA/JPL-Caltech | https://images.nasa.gov/details-PIA23791 | `~small.jpg`, 640×312 | `5a610bff7ad5620a638eb6a43ca8338708647859c02502eb5de649f4248d1a80` | Stereo-pair source; right disk cropped for the shot. Cloud view, correct for the sulfuric-cloud line. |
| 7 | GSFC_20171208_Archive_e000332 — Hubble Takes Mars Portrait Near Close Approach | NASA, ESA/Hubble | https://images.nasa.gov/details-GSFC_20171208_Archive_e000332 | `~medium.jpg`, 1280×1280 | `6d1bc44bf4cf8a33c741111aa141314b440cc0955a5c88be261295487e4e0381` | Natural globe; replaces PIA02992 polar mosaic that did not read as a planet. |
| 8 | PIA04866 — Cassini Jupiter Portrait | NASA/JPL/Space Science Institute | https://images.nasa.gov/details-PIA04866 | `~medium.jpg`, 1024×1280 | `a216412344ca04d1d7df728b4b2b66ce41e3dcd4f5f9d3596047a9776619788c` | Storyboard's reference plate; static fallback while LTX shot 8 waits for GPU. |
| 9 | PIA21772 — Close-up of Jupiter's Great Red Spot | NASA/JPL-Caltech/SwRI/MSSS/Jason Major | https://images.nasa.gov/details-PIA21772 | `~small.jpg`, 640×468 | `797f22b2da6e011c3f251fc6ee6d925767132b93a54ceb557cf0739e85b7bc3f` | Enhanced-color JunoCam; citizen-scientist processing credited. Static fallback for LTX shot 9. |

Superseded for v3-static-final (files retained for history): PIA00075
(shot 3, false-color), PIA02992 (shot 7, polar mosaic layout).

Evaluated but not used (files kept in this folder for history): PIA01509
(Jupiter, max rendition 400 px — too soft; PIA04866 used instead),
PIA00071 (Venus Galileo — delivered as a 4-panel grayscale grid),
PIA00072 (Venus — blue false-color, misleading for the audience).
PIA23791 chosen for Venus instead.

## Not downloaded

- Venus PIA00270 is a radar-derived surface visualization, not a view through Venus’s clouds. Keep it as an optional inset/reference; use a separate cloud illustration for the main shot.
- The Kuiper Belt candidate diagram credits NASA and A. Feild (STScI); instead of republishing that diagram, build an original schematic map from the approved 30–50 AU facts.
- Jupiter/Great Red Spot: resolved 2026-11-07 — PIA04866/PIA21772 used as the approved static fallback; LTX dynamic renders remain pending the GPU gate.
- PIA19857 remains excluded after its earlier HTTP 403; PIA20291 is the reachable Pluto alternative.
