# NASA stills + 2.5D layer proof v1

Status: private prototype only; not part of the solar-system film master and not cleared for public redistribution.

## Sources

| Scene | NASA ID/title | Source/credit from NASA metadata | Source URL | Local SHA-256 |
|---|---|---|---|---|
| Earth | `GSFC_20171208_Archive_e001016` — Blue Marble, Eastern Hemisphere March 2014 | NASA Goddard; metadata says `AVAIL:Copyright=None` | https://images-assets.nasa.gov/image/GSFC_20171208_Archive_e001016/GSFC_20171208_Archive_e001016~large.jpg | `48ccd32ef57d182662999905841109095d66d68d69e27dba7decc6e134a811a0` |
| Saturn | `PIA06193` — The Greatest Saturn Portrait ...Yet | NASA/JPL/Space Science Institute | https://images-assets.nasa.gov/image/PIA06193/PIA06193~large.jpg | `a38113c9393b9f07a2afbf311498dec051c8d1f9fec33f7459c34215f0e8018c` |
| Pluto | `PIA19857` — Pluto in True Color | NASA/JHUAPL/SWRI | https://images-assets.nasa.gov/image/PIA19857/PIA19857~large.jpg | Not downloaded: HTTP 403; deferred per the approved Earth/Saturn-only proof scope. |

Discovery/metadata sources: https://images.nasa.gov/ and https://science.nasa.gov/photojournal/ .

## Rights and credit handling

NASA says its content is generally usable for educational/informational purposes, but that is not a blanket public-domain grant for every file. Verify each item's caption and rights metadata; third-party material on a NASA page does not automatically inherit NASA's usage permission. Keep the exact source credit in the artifact/manifest, do not use NASA/JPL logos, and do not imply endorsement. Review the NASA media and JPL image-use guidelines before any public release:

- https://www.nasa.gov/nasa-brand-center/images-and-media/
- https://www.jpl.nasa.gov/jpl-image-use-policy/

## Layer recipe

1. Procedural dark starfield background.
2. NASA planet/ring plate keyed against near-black space.
3. Soft tinted glow behind the plate.
4. Slow foreground push-in over the static background (simple 2.5D parallax; no AI video generation).
5. Thai narration/subtitle and a small, exact English image-credit line.

Current preview uses the existing private Thai VO clips for Earth (shot 1) and Saturn (shot 11). It is a technique test, not a finished scene or approved release.

## Prototype output

- `nasa-2p5d-earth-saturn-v1.mp4`: 6.375 s, H.264/AAC, 640×384 at 24 fps, 238,617 bytes.
- SHA-256: `39f81167990e10e7d4a518cc8765fd9f70d56a65f74c44548c518aca7c782914`
- The preview has Thai lower-thirds, exact image credits, a generated starfield background, keyed NASA planet plates, a soft glow layer, and a slow foreground push-in. It uses no AI video generation and no GPU.
- Source scripts: `render_layers.py` and `mix_audio.py`. This proof is intentionally only Earth + Saturn; Pluto was deferred after the HTTP 403.
