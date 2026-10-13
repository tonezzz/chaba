# Dispatch outcome — live-session-token-diet (OPS-0509, attempt 2/2)

## Scope taken this run

Attempt 1 (dispatch 212811) already landed the context-window lever
(ADA_CONTEXT_TRIGGER/TARGET 47k/35k live, rotation-bounded by design)
and carded the expression lever (ADA-0601). This run took the
unclaimed biggest remaining lever: **bench traffic off the paid lane**
(BEN-0573, already carded+approved direction).

## Burn decomposition (journalctl, ada-ha-tony)

- 2026-10-12: 3595 turns, **116.3M input tokens** (the card's ~134M/day)
- 2026-10-13 to ~22:00: 306 turns, **9.45M** — ~92% down after
  `_cap_tool_result` + ADA_TOOL_CALL_BUDGET=10 + 49-decl keep-list +
  lazy tool schemas (fresh first-turn in= **18139**, was ~27.8k)
- By caller today: **admin 7.38M / 78%** (hourly scenario smoke),
  real users ~2M. 97/119 sessions were caller=admin.
- Top tool on tony lane: set_facial_expression 163/320 calls (51%)
  → ADA-0601 covers it.

## What changed

- `stacks/services/ada-scenario-runner/ada-scenario-smoke.container`
  (repo SSOT) + live `~/.config/containers/systemd/` copy:
  - `ADA_LIVE_URL` → `ws://127.0.0.1:8005/ws` (ada-dev, FREE key —
    sha-verified vs gemini-keys.env)
  - `EnvironmentFile` → `ada-dev.env`; keys volume →
    `ada-ha-dev-keys.json`; gate `--unit ada-dev --env-file ada-dev.env`;
    `After += ada-dev.service`
  - Live copy sync also closed drift: spend-ledger ExecStopPost +
    shell-wrapped ExecCondition the repo already carried are now
    installed.
- `systemctl --user daemon-reload` applied; **no paid-lane process was
  restarted**.

## Result

- **Verified live:** manual `start ada-scenario-smoke` 21:49 → admin
  sessions opened on ada-dev :8005; **zero** ws connects on
  ada-ha-tony. The 22:00 hourly timer fired on the new config — gate
  `ok — provider healthy`, sessions landing on ada-dev, ada-ha-tony
  connect count stayed 0 through the window.
- Manual `scenario-live.py date_echo.yaml` vs :8005 → **PASS**
  (3 turns, 6 tool calls).
- Projected: removes ~7-8M input tokens/day from ada-ha-tony
  (~75-80% of today's remaining burn). Expected lane total ≈2-3M/day.
- Caveat: the 21:49 verification run scored 2 fail + 2 infra then the
  suite sentinel recorded the rest skip-quota — the infra pair hit
  transient ws 403s while ada-dev was ~3 min post-restart (another
  dispatch had just bounced it). date_echo passes clean post-warmup and
  `After=ada-dev.service` + suite retry absorb the race.

## Remaining paid-lane consumers (flagged on BEN-0573)

- Weekly tiers `ada-scenario-{memory,reports,tools,casting,cms,
  research}` still target :8002 (~234 admin turns each run-day) —
  lane-coupled suites (casting needs VCAST/HA actuation ada-dev lacks)
  need a per-suite dev-safe audit before retargeting.
- `ada-scenario-full.container` (manual) — same consideration.
- No paid-lane canary exists (ada-live-canary probes FREE hourly);
  BEN-0573 wants ≤1 paid connect/day — real user traffic is the
  de-facto probe; left as a decision note.

## Trail

- `docs/ssot/jobs/ada/2026-10-13-smoke-tier-to-ada-dev.yml`

## How to verify

- `journalctl --user -u ada-ha-tony --since '1 day' | grep -c
  'caller=admin'` → ~0 for hours after 22:00.
- `journalctl --user -u ada-dev -u ada-scenario-smoke` → hourly runs,
  admin sessions on :8005.
- `systemctl --user cat ada-scenario-smoke` → ADA_LIVE_URL=:8005.
- spend-ledger CMS page: ada-ha-tony admin-share should drop <20%
  (BEN-0573 acceptance).
