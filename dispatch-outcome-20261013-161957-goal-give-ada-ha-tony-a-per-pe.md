# Dispatch outcome — tony-lane-tool-profile (OPS-0583)

## What changed

- `docs/ssot/apps/ssot.apps.ada-persons.yml`: added `persons.tony.tools`
  {instance: tony, env_file: ada-ha-tony.env, host: idc03} —
  **usage-evidenced, not kk-parity**. include = 49 declared seats
  (kk-parity core minus stale `conv_journal`, plus the 7d-evidenced
  tony-lane additions, plus `vcast_gesture` which smoke-tier
  `tool_merge_display` calls hourly on this lane). exclude = the
  complement: `home_status`, `home_history` (get_home_state/home_search
  are the fallbacks). Also removed the stale `conv_journal` entry from
  `persons.kk` + both bench_profiles — the tools.d module exists but was
  never manifest-enabled (b776e81) so it was never declared at runtime.
- `docs/ssot/ssot.tokens.policy.yml`: baseline-discipline rule updated
  with measured per-lane floors (~27.8k tony / ~17k kk; ~0.5k per
  declared seat; aliases emit nothing; cap corrected 109 -> 112).
- `docs/ssot/jobs/ada/2026-10-13-tony-lane-tool-profile.yml`: trail doc.
- LIVE on idc03: managed block written into
  `~/.config/secrets/ada-ha-tony.env` (ADA_INCLUDED_TOOLS=49 names,
  ADA_EXCLUDED_TOOLS=home_status,home_history), `ada-ha-tony` restarted,
  49 tools verified in the running process env.

## Result

- **Lint:** `render-tool-profiles.py --lint` → 0 warnings (51 declared
  tools all covered; kk's stale `conv_journal` warning cleared).
- **Measure:** fresh-ws first `usage turn in=`: **28874 → 27828/27859
  (~27.8k, -1.0k/turn, -3.6%)**. The card's <=~23k target rested on a
  "~110 declared tools" premise — the real emitted surface is ~51
  declared seats at ~0.5k tok each (aliases are dispatch-time
  `_ALIASES`, emitting no declaration; the ~110 traces to the stale
  count_cap comment "103 builtin + 9 tools.d"). The usage-evidenced
  keep-list only had 2 seats to drop. Deeper cuts are a
  capability-vs-spend decision — board request raised with options
  A(keep 49)/B(drop ~6 low-value seats -> ~24.5-26k)/C(aggressive,
  breaks ~50 weekly-tier scenario cases).
- **Smoke:** PASS — cast_to_screen (screen list), control_entity
  (no-op set on input_boolean.cast_powered_by_us), ada_memory_search
  recall all resolve with sane payloads.
- **context_growth.yaml:** ceiling PASS every turn (all turns < 55k);
  floor FAIL twice identically — turn 11 delegates the planted-code
  recall to `ada_session_recall` (instruction ~L1138 routes recall
  questions to memory tools) and parrots a past-sessions summary.
  **Exonerated as pre-existing:** control run on ada-ha-michael (full
  surface, no keep-list) fails the same turn — the model there flatly
  claims no code was given. Lane-general instruction-routing bug, carded
  OPS-0585.

## Follow-ups filed

- OPS-0584 `conv-journal-manifest-gap` — tools.d dead code.
- OPS-0585 `context-recall-floor-delegation` — floor bug + per-lane
  window trigger/target finding (32k/24k vs 27.8k floor = ~1.15x,
  policy wants >=1.7x).
- Board request on `tony-lane-tool-profile` — deeper-cut decision
  (options A★/B/C, recommendation A).

## How to verify

- `journalctl --user -u ada-ha-tony` → `usage turn in=` ~27.8k on fresh
  sessions (was ~28.9k).
- `grep -A3 chaba-rendered ~/.config/secrets/ada-ha-tony.env` → managed
  block with 49-tool include.
- `python3 scripts/ada/render-tool-profiles.py --lint` → no output.
- `systemctl --user status ada-ha-tony` → active.
