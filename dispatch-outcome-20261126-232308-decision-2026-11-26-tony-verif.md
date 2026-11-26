# Dispatch outcome — line-lane-lock-retire (Phase 1 verify)

## What was done
Read-only verification that `chat_send` lane targeting uses
`LINE_LANE_ALLOW` and the last-room fallback as documented. No lock
removal, no routing changes, no sends, no restarts.

## Findings

**Code (verified deployed == upstream):** idc03
`~/CascadeProjects/ada-voice` files `backend/line_relay.py`,
`backend/tool_runner/chat.py`, `backend/tool_runner/common.py`,
`pwa_server.py` are byte-identical to `tonezzz/ada-voice` `origin/main`
@ `0892c82`.

**Targeting chain (relay `/send`, line_relay.py ~2424-2545):**
`to`/`chat_id` explicit → display-name resolution → `_recent_chat[inst]`
(<600s, last-room fallback, in-memory) → `LINE_LANE_DEFAULT[inst]` →
first allowed user → `LINE_LANE_LOCK` rewrite to lane default →
`LINE_LANE_ALLOW` 403 gate → deliver + refresh `_recent_chat[inst]`.
Tool side: empty `to=` resolves the session-bound chat via
`SESSION_CHAT` (`?chat_id=` bound at ws connect); explicit `to=` wins.

**Config locations (live):**
- `idc03:~/.config/secrets/line-bot.env` (ada-line-relay EnvironmentFile):
  `LINE_LANE_LOCK=kk,kk-dev,chaba`; `LINE_LANE_DEFAULT` and
  `LINE_LANE_ALLOW` cover kk, kk-dev, chaba, tony, ada (allow sets are
  `+`-separated). All three locked lanes' defaults sit inside their own
  allow sets — the rewrite cannot self-403.
- `ADA_INSTANCE_ID` per lane env: tony (:8002), kk (:8007), kk-dev
  (:8009), chaba (:8008), dev (:8005), ada (:8006), michael (:8003).
- `ADA_LINE_SEND_URL` unset everywhere → default `127.0.0.1:8912/send`.

**Observed behavior:** journal window Nov 25→26: 68 `/send` deliveries —
67 `inst=-` script pushes to member DMs (ungated by design), 1
`inst=kk-dev→C822` bulk. Zero `lane lock` rewrites, zero `send denied`
403s. LINE quota healthy (126/300). Lane-targeted chat_send traffic is
thin — the lock is verified correct but barely exercised live.

**Nuances flagged for the retirement decision:**
- `_recent_chat` is per-process, 600s TTL; only the chaba lane
  (persona==instance) gets turn-warmed fallback — for other lanes it
  tracks last *push* target, not last conversation.
- `tony` lane allowlist lacks its pinned group Cb75 (latent 403; group
  appears dead — no journal dir).
- `dev`/`michael` instances have no `LINE_LANE_ALLOW` entries → exempt
  from the gate. Omen dev backends can't reach a relay on :8912 anyway.
- First-allowed-user fallback iterates a set — winner can vary per
  relay restart.

## Deliverables
- `docs/ssot/jobs/ada/2026-11-26-line-lane-lock-targeting-verify.yml` —
  full verification report with config values and chain trace.
- Card comms posted on `line-lane-lock-retire` (progress + final).

## How to verify
- Report file above; card comms on the board.
- Spot-check: `ssh tony-omen 'ssh idc03 "grep LINE_LANE ~/.config/secrets/line-bot.env"'`
  and `journalctl --user -u ada-line-relay | grep -E 'lane lock|send denied'`.

## Result
Phase 1 gate input complete: mechanism verified end-to-end. Retirement
of `LINE_LANE_LOCK` remains gated on Tony — suggested per-lane sequence
(kk-dev → kk → chaba) if approved.

lessons:
- idc03 ssh needs nested hop: `ssh tony-omen 'ssh idc03 ...'` — direct ProxyJump session channel is refused.
- idc03 ada-voice checkout shows "ahead 5" vs its stale origin/main ref — byte-diff deployed files against a fresh origin/main clone before trusting git state.
- LINE lane env split: relay config in line-bot.env, per-lane ADA_INSTANCE_ID in each backend's own env file (tony-ha/kk-ha/backend.env etc.) — SSOT lane map lags the env-file reorg.
- lane-lock rewrite and allowlist 403 log to journal only — no ops-events codes; short journal retention (~2d) limits retro evidence.
