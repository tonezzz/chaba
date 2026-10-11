---
description: Codeword "scalecheck" — standard procedure for wrong Chrome/display scaling on GNOME/Ubuntu hosts (HiDPI laptop + external monitors). Diagnose then apply safe fixes.
---

# scalecheck — display/Chrome scaling procedure

Codeword: **whenever Tony types `scalecheck`** (or complains that Chrome/text/UI is the wrong size on a monitor), run this procedure on the local host.

## The procedure

1. Run the diagnostic: `display-scale-check` (installed at `~/.local/bin/`; source `scripts/devin/display-scale-check.sh`). It reports:
   - session type (Wayland/X11), GNOME scaling state (`text-scaling-factor`, mutter fractional-scaling features)
   - per-monitor logical layout: connector, mode, scale, position, primary — plus connected-but-disabled monitors
   - recent kernel link errors (MST payload, EDID, link training)
   - Chrome's ozone platform and flag overrides
2. Read the FINDINGS section. Standard anomalies → standard fixes:

   | Finding | Fix |
   |---|---|
   | monitor connected but DISABLED | `display-scale-check --enable <CONN> [--right-of <CONN>]` |
   | wrong logical scale | `display-scale-check --scale <CONN> <N>` (pick from offered list) |
   | mutter features missing | `display-scale-check --fix` |
   | Chrome not on wayland | `display-scale-check --fix` writes `~/.config/chrome-flags.conf`, then restart Chrome |
   | `text-scaling-factor` ≠ 1.0 | ASK before changing — it's a deliberate-taste knob (GNOME Tweaks → Fonts → Scaling Factor) and does NOT affect Chrome web content; fix with `--set-text-scale 1.0` only if Tony confirms |
   | MST payload / link errors | hardware path: replug, other USB-C port, better cable/dock; this host's dock has known MST flakiness (amdgpu Polaris) |

   Layout profiles (replug-safe — keyed by EDID vendor/product/serial, not connector):
   - `display-scale-check --save NAME` — snapshot current layout (position, scale, primary, mode per monitor + text-scaling-factor) to `~/.config/scalecheck/NAME.json`
   - `display-scale-check --restore NAME` — re-apply; matches monitors by EDID so MST connector renumbering after replug doesn't matter; skips absent monitors with a warning
   - `display-scale-check --profiles` — list saved
   - Saved: `docked-home` = Dell@1.5 + Philips@1.5 + eDP@3.0 (2026-10-11)

3. Re-run the diagnostic to verify the fix stuck (mutter can silently roll back a mode set — check the logical monitor list, not just "applied" output).
4. Report final layout + anything left for Tony's eyes (scale taste, text-scaling).

## Notes

- `text-scaling-factor` does NOT affect Chrome rendering — it only scales GTK app fonts. Chrome scale issues are monitor logical scale, ozone platform, or `--force-device-scale-factor`.
- On tony-macbook (MacBookPro13,3): external displays route through the amdgpu dGPU over one MST link from the USB-C dock; multi-monitor enable can intermittently fail at kernel level (`MST payload` errors). Retry or replug before concluding the config is wrong.
- Lid closed → eDP-1 suspended, shown as inactive builtin (normal, not a finding).
- `gdctl` (GNOME ≥48) is the apply backend; `--enable` keeps existing logicals and adds the new one right of the anchor, `--persistent` writes `~/.config/monitors.xml`.
