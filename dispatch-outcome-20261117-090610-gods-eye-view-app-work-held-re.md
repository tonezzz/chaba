# Dispatch outcome — gev-voice (2026-11-17, tony-omen)

Branch: `dispatch/20261117-090610-gods-eye-view-app-work-held-re`
Commit: `8c3d05b288` — "gev-voice: rebase mute-invariant + playback work onto bundle Bd5DfCi5"

## What happened

The card was already solved once: the 2026-10-06 dispatch produced commit
`0da7f3d8` on `dispatch/20261006-174428-gods-eye-view-app-work-held-re`, but
merge-sweep never landed it ("no served checkout for repo '?'") and the card
later bounced done→doing for missing verify evidence. Meanwhile the vendored
GEV bundle was rebuilt (`index-D8kXv0di` → `index-Bd5DfCi5`), so the old
`-v1` patch no longer applied to the shipped artifact.

This session recovered the prior commit's files and rebased them onto the
current bundle, hardening the tooling against the exact drift the rebuild
caused.

## Changes (per card spec)

1. **Mute-invariant regression test** — `stacks/web/input-bridge/gev-voice-check.mjs`
   (restored + hardened). Extracts the shipped `setMicrophoneEnabled` /
   `onaudioprocess` bodies and drives them through a mock WebAudio graph:
   muted ⇒ zero outbound PCM frames, mid-stream mute flushes only pre-mute
   audio, and a flag-stripped mutation still yields silence — proving the
   GainNode, not the recording flag, carries the invariant. Hardening:
   param names are now captured via signature regexes (the rebuild renamed
   `onaudioprocess`'s param `r`→`s` and crashed the harness), mutation
   regexes generalized.

2. **iOS constraint documented** — `apple-mobile-web-app-capable=no` already
   shipped in `index.html`; now documented in `AGENTS.md` (GEV caveats) and
   `docs/ssot/apps/ssot.apps.gev.yml` (Known Issues) as deliberate — iOS mic
   works in Safari, not standalone PWA; do not flip without a mic fallback.

3. **Playback gap closed (repo-side)** —
   - `stacks/tony-dell/gev-gemini/bridge.py`: `pump_responses` forwards
     `model_turn` `inline_data` as binary ws frames (24 kHz PCM16). Unit
     check `audio-forward-check.py` 7/7 (stubbed genai/websockets).
   - `stacks/web/scripts/gev-patch-dist.mjs`: idempotent post-build patcher;
     the binary-listener patch is now regex-based (minifier renamed the JSON
     temp `s`→`o`, the literal replace silently NOOPed). `resolveBundle`
     prefers highest `-vN` when a dir holds several bundles.
   - `stacks/web/public/apps/gev/assets/index-Bd5DfCi5-v1.js`: patched bundle
     (binary frames → `playGeminiAudio` PCM16→Float32 BufferSource queue on a
     24 kHz ctx, `interrupted` flush, `cleanupSession` ctx close).
   - `index.html` script tag → `-v1`.

4. **Trail** — `docs/ssot/jobs/gev/2026-11-17-gev-voice-mute-playback-rebase.yml`
   (this session) plus the restored `2026-10-06-gev-voice-mute-playback.yml`.

## Verification (run in this session)

- `node stacks/web/input-bridge/gev-voice-check.mjs` → **21/21 PASS** on the
  staged `-v1` (mute invariant behavioral + playback path + bridge + iOS meta).
- `… --bundle=stacks/web/public/apps/gev/assets/index-Bd5DfCi5.js` → **17/21**,
  only the 4 playback checks fail — the check discriminates.
- `python3 stacks/tony-dell/gev-gemini/audio-forward-check.py` → **7/7 PASS**.
- `node stacks/web/scripts/gev-patch-dist.mjs stacks/web/public/apps/gev/assets --check` → rc 0 (idempotent).
- Pre-commit SSOT validation + optimization gate passed.

## NOT done (gated, per dispatch rules)

- **Not pushed, not deployed.** Reaching users needs on tony-dell: chaba pull
  (single-writer path) + `gev-gemini` container rebuild/restart. After that,
  `gev-voice-check.mjs --live` verifies the deployed bundle.
- Tony already approved arming GEV dispatch + deploy on 2026-10-06
  (request `arm-gev-dispatch-approve-deploy-53bf0b` = "approve.") but
  dispatch-repos.conf was never updated — still tracked by `gev-program-design`.
- Card `verify:` criterion is satisfied by the check evidence above; the card
  can be re-closed citing `gev-voice-check 21/21 + audio-forward-check 7/7`.
