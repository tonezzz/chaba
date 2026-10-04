# Dispatch outcome — barrier-image-copy

**Result: implemented and verified.** Option B (extend clip-sync to image payloads), as Tony picked on the card.

## What changed

The existing `clip-sync-dell.service` on tony-omen was functionally dead — it
ssh'd to dell's stale IP `192.168.1.42` (dell is `192.168.2.67` now) and ran
remote `xclip` with no `DISPLAY`/`XAUTHORITY`. Replaced with a shared,
bidirectional design:

- `scripts/barrier/clip-sync.sh` — generic one-way clipboard poller
  (remote ssh+xclip → local xclip). Polls TARGETS every 1s; when an `image/*`
  target is offered it uses remote TIMESTAMP (sha256 of raw bytes) as a cheap
  change trigger, then remote-hashes the payload and only pulls/writes bytes
  when the content hash differs. Content-keyed, so the pair converges after at
  most one redundant pull per copy (a pure timestamp key would ping-pong —
  every `xclip -in` gets a fresh timestamp).
- `systemd/clip-sync-dell.service` — omen unit, dell→omen (updated: new
  ExecStart + remote env, waits for X0 socket).
- `systemd/clip-sync-omen.service` — new dell unit, omen→dell on seat :1.

Deployed: `~/.local/bin/clip-sync` + units on both hosts; both `active`.
Omen's stale `~/bin/clip-sync-dell` is now a shim exec'ing the new script.
Barrier seats were not touched.

## Verified

- dell→omen image: 16×16 PNG byte-identical (sha256 `5503ff8f…`).
- omen→dell image: byte-identical (sha256 `02face63…`) — the originally
  reported direction.
- Text both ways; journals quiet in steady state (no ping-pong, no errors).
- SSOT validator: 1016 files, 0 errors.

## Caveat worth knowing

Barrier grabs each clipboard on content change and on screen crossing and
caches text only — an image can be transiently clobbered; the opposite poller
restores it within ~1s while either side holds the bytes. Copy→cross in under
~1s can beat the poller — just copy again after the pointer settles.

## Trail

- Runbook/decision: `docs/ssot/jobs/infrastructure/2026-10-04-barrier-image-clipboard.yml`
- SSOT updated: `ssot.mysystem.home.yml` (Input Sharing), `ssot.registry.infrastructure.yml` (clip-sync assets), `ssot.audit.hosts.yml` (expected services on both hosts)
- Commit `c2b07340` on `dispatch/20261004-202634-implement-a-workaround-for-bar` (not pushed)
