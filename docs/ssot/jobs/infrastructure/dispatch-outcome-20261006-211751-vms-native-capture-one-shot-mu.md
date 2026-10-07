# dispatch 20261006-211751 — vms-native-composite

## What changed

Ported forward the unmerged prior-run (111612) implementation, hardened it
against live failures found this session, redeployed to mn01, verified.

- `stacks/services/xmeye-vms/vms-snap.py` — new `GET /composite?chs=<csv>
  [&native=1][&layout=4|9][&settle=<s>]` returning `application/zip` of
  `<i>.png` members + `_manifest.json` (per-cam i/q/name/ok/err/w/h).
  Binds each channel to a monitor pane (bindings persist per pane index in
  `_pane_map`, warm refreshes skip attach), verifies each pane shows MOVING
  video (two differing xwd sightings), then captures: per-pane context-menu
  Snapshot -> native BMP (native=1) or one xwd split into tiles (native=0).
  Session hardening vs the prior-run build:
  - `_cap_dialog_open()` modal detector (title-bar gray stripe, y~330) +
    `_dismiss_modal()` polls until verifiably closed — an ORPHANED Capture
    Information modal swallows every later click (tree dblclicks, pane
    right-clicks); observed live as a full-run cascade.
  - `_keep_bmp()` re-verifies Save actually closed the dialog (Cancel
    fallback is safe — bytes already read).
  - BMP-wait clock now starts at the Snapshot click (not the right-click)
    and is 12s — menu polling could eat most of the old 8s window, landing
    the bmp just after the deadline and orphaning its dialog.
  - `COMPOSITE_SETTLE` 40 -> 90s: cold multi-attach serializes at the DVR,
    streams land over ~90-120s.
  - Binds paced ~3s apart (rapid-fire dblclicks drop most attaches).
  - `_pane_map` entries beyond the active layout capacity are dropped —
    shrinking the grid detaches those streams.
  - `_native_capture_pane` gains a blind final attempt (right-click +
    Snapshot-offset click; harmless if no menu opened).
  - `snap()` also opens with `_dismiss_modal()`.
- `scripts/cam-wall/cam-wall-pull.py` — groups a zone's vms cams by DVR
  device and makes one `/composite` call per group within the remaining VMS
  budget; call-level failure or env `CAMWALL_VMS_COMPOSITE=0` falls back to
  the serial `/snap` path (per-channel fallback kept per spec). Partial
  failures mark per-cam `err` without re-pulling (budget protection).
- `stacks/services/xmeye-vms/README.md` — /composite contract + caveats.
- `docs/ssot/jobs/infrastructure/2026-10-06-vms-composite-capture.yml` —
  full findings log (layout pill coordinates, menu/modal detectors, attach
  timing numbers).
- `docs/ssot/ssot.learning.vms-native-snapshot.2026-10-03.yml` — cleared
  the resolved open follow-up.
- Deployed to mn01: `~/.local/share/xmeye-vms-stack/vms-snap.py` updated,
  `vms-snap.service` restarted, verified active.

## Result / verification

- **Verify criterion met**: `GET /composite?chs=<8 noble-club channels>`
  returned 200 zip in ONE capture cycle with per-pane split PNGs at native
  2560x1440; tiles visually confirmed correct (Washing Machines, Swimming
  Pool, etc.). 5/8 panes ok; failures were per-cam manifest errs
  (one offline red-X channel + attach flake), not call failures.
- noble-a 5-ch run earlier: pane 0 produced a 2880x1616 native PNG.
- Serial `/snap` unaffected — verified same evening (2880x1616 in ~23s).
- `python3 -m py_compile` clean on both files; jobs YAML parses.
- tests/camwall: 2 pre-existing failures (`zone_meta` import in
  cam-wall-cms.py — script-dir sys.path assumption, untouched by this diff).

## Known limitations (documented in jobs yml)

- Cold composite of a full zone takes ~3-5min under P2P attach contention —
  the win is steady-state: warm refreshes skip attach entirely. Puller
  calls it within the VMS budget; timeout -> serial fallback next cycle.
- Concurrent P2P attaches remain a per-attach coin flip; repeated test
  cycles can leave zombie DVR streams that starve later runs briefly.
- Pane bindings live in the VMS app, `_pane_map` in shim memory — a shim
  restart is safe (map rebuilds), stale claims are corrected by the verify
  loop.
