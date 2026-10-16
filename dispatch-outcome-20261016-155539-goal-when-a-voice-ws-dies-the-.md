# Dispatch outcome — ada-voice error observability (attempt 2)

Card: `ada-voice-error-observability-surface-up-489f64`
Goal: when a voice ws dies, the card shows WHAT failed — not a bare
reconnect loop or a cryptic code.

## What the prior run already shipped (verified, not redone)

- chaba `35c7d2532` is on master: all three `ada-voice-card.js` copies
  (tony-ha, ada-ha, kk-ha — still byte-identical) render
  `{type:error, stage:provider_connect}` as "Upstream provider refused:
  …", keep the line visible after teardown (`_state="error"` survives
  `_teardown`), `avcLog("ws", "close code=… reason=…")` on every close,
  and show "Disconnected (code N — reason)" on abnormal closes.
- ada-pi `2430f7a` (separate repo, outside this worktree): pwa_server
  sends the sanitized provider_connect error frame before close(1011)
  and `pwa/app.js` logs close codes. Per card comms: deployed to all 8
  lanes, 1390 tests green. No chaba-side worktree copy exists —
  `integrations/ada-voice/` holds only patches, and staging a patch for
  code already committed upstream would break the drop flow.

## What this run added (the remaining spec gaps)

- `stacks/tony-dell/{ada-ha,tony-ha}/www/ada-chat-card.js` — mirrored
  the voice-card behavior: `console.info` on every ws close
  code+reason; abnormal closes (≠1000, outside the mint-retry/locked
  paths) now write `ws close code=N reason=…` into the transcript and
  set the status line to `Disconnected (code N — reason)` with the
  error state preserved through `_teardown`. `provider_connect` error
  frames render as "Upstream provider refused: …". Both copies
  byte-identical; `node --check` clean.
- `scripts/ada/gemini-wallet-watch.py` — `--key-var` is now repeatable
  (default unchanged: `GEMINI_API_KEY_PAID`). Per-key probe → per-key
  state file (`{"keys": {VAR: …}}`, legacy `{status:…}` auto-migrates
  to PAID so no re-alert), lane-labelled alert text, kk group paged
  (Thai) only when `GEMINI_API_KEY_KK` is down. Exit 1 while ANY
  probed key is `credit`.
- `stacks/services/ada-live-canary/gemini-wallet-watch.service` —
  ExecStart now probes `PAID + TONY + KK + MICHAEL`; `TimeoutStartSec`
  60→120 (4 sequential ≤20s probes). This closes the spec's
  wallet-watch item: the incident key `GEMINI_API_KEY_TONY`
  (ada-ha-tony + ada-pi-pwa lane) was NOT in the probe list — the
  PAID-only probe stayed green while the lane died.
- `stacks/services/ada-live-canary/README.md` +
  `docs/ssot/infrastructure/ssot.audit.hosts.yml` — updated to
  document per-key coverage.
- `tests/ada/test_gemini_wallet_watch.py` — 11 tests pinning the
  incident scenario (TONY depleted while PAID green → alert + exit 1),
  kk-scoped Thai alerts, transition-only alerting, legacy state
  migration, default var, no-key handling.

`GEMINI_API_KEY_FREE` is deliberately NOT probed — free tier is
20 req/day and hourly probes would both exhaust it and spam alerts.

## Result / how to verify

- `python3 -m pytest tests/ada tests/board -x -q` → 306 passed, 1
  skipped (this worktree).
- `node --check` clean on both edited card files; chat-card copies
  md5-identical.
- Wallet watch dry-run check once the unit is synced:
  `gemini-wallet-watch.py --env-file ~/.config/secrets/gemini-keys.env
  --key-var GEMINI_API_KEY_PAID --key-var GEMINI_API_KEY_TONY … --dry-run`
  prints one verdict line per key.
- Live verify (needs lane sync, outside this dispatch): bad Gemini key
  on ada-dev → voice card shows "Upstream provider refused: …";
  chat card transcript shows "· ws close code=1011 reason=…" + status
  "Disconnected (code 1011 …)". The code path is identical to the
  already-deployed voice-card change.
- Deploy note: the edited `stacks/*/www/*.js` are stack sources — they
  reach HA lanes on the next www sync (prior run deployed via the same
  files). The updated `.service` reaches idc03 on the next
  `install.sh` run; the timer keeps working against the old ExecStart
  meanwhile (backwards-compatible).

lessons:
  - Check card comms first on re-dispatch — attempt 2's job was the
    residual (chat card + wallet-watch coverage), not a redo.
  - ada-pi / ada-voice checkout lives OUTSIDE the chaba worktree;
    pwa_server.py + pwa/app.js changes can't be made from a chaba
    dispatch — stage a drop patch under integrations/ada-voice/ instead.
  - Probing GEMINI_API_KEY_FREE hourly would eat its 20/day quota —
    only paid keys belong on the wallet-watch probe list.
  - State files that change shape need a migration path; the legacy
    {status} → {keys:{PAID:…}} wrap prevents a spurious re-alert.
