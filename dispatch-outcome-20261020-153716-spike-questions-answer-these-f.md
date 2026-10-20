# Dispatch outcome — lab-ada-session-boundaries spike (2026-10-20)

**Card:** `lab-ada-session-boundaries` (ADA-0177) — **retired → done** (hypothesis dead).
**Runner:** tony-omen · **Evidence host:** idc03 (live ada-voice@a67bea0) + local read of `~/CascadeProjects/ada-pi` (= tonezzz/ada-voice).

## Spike answers (posted to card comms)

**Q1 — What is a session boundary today?**
A session = one `/ws` connect on `pwa_server` (fresh `session_id`, provider, `ConversationMemory`). Messaging chats already reset per connect AND via a 600s idle reaper in both relays (`LINE_IDLE_SESSION_S` / `TELEGRAM_IDLE_SESSION_S` — 34 idle closes on LINE in 7d). Memory **does** re-snapshot every connect: `_prime_session` injects recent-sessions summary + top memories + shared channel tail + reconnect tail (79 primes on ada-ha-tony in 7d, including mid-WS provider rotates). Context is not unbounded: Live uses Gemini sliding-window compression (32k→24k) plus a token-budget **context-rotate** that drops the live session at idle. Text-mode `_turns` is unbounded in principle but capped by the 600s idle close — measured real sessions ≤577s over 7 days (p50=57s). The only >10min sessions were idle HA-panel WS holds (0 responses, 0 tokens). Note: the legacy `main.py` `LiveSessionManager` (`session_id="persistent"`, resumption handles) IS the never-ending session the card hypothesized — but no live unit serves it; all run `pwa_server`.

**Q2 — Compaction cost now?**
No separate compaction job or cost line exists. In-session compression is Gemini's server-side sliding window (cost inside per-turn input tokens); session-end costs ~3–6 small REST calls on a ≤8k-char transcript — bounded per session, never re-processing growing history. journal-report over 7d (tony+pwa+dev): ~77M input tokens, dominated by the Oct 13–14 ada-dev benchmark storm (554 sessions/day on dev); steady voice use ~4.4M/day Oct 17, ~0 since. **Measurement gap found:** LINE text-mode turns never reach `usage.jsonl`/`journal-report` — the main messaging lane is unmetered client-side (carded as ADA-0752).

**Q3 — Where would a boundary go?**
Already present at the relay layer (env-tunable idle reaper) and provider layer (context-rotate + sliding window). The only missing slots: no server-side idle reaper on `pwa_server /ws` (browser/HA-panel sessions idle 8h+, harmless today) and no `_turns` cap in `OpenRouterTextProvider`. `LINE_IDLE_SESSION_S_NIGHT=120` is set in secrets but dead — no code reads it.

## What changed
- Card `lab-ada-session-boundaries` moved `lab → done` with full spike findings in comms.
- New card `ada-text-lane-metering-gap` (ADA-0752, backlog/low): text-path usage recording, dead env var, `_turns` cap.
- Job trail: `docs/ssot/jobs/ada/2026-10-20-session-boundaries-spike.yml`.

## How to verify
```bash
python3 scripts/ada/journal-report.py --host idc03 \
  --units ada-ha-tony,ada-pi-pwa,ada-dev --since "7 days ago"
ssh idc03 'journalctl --user -u ada-line-relay --since "7 days ago" -o cat | grep -c "idle close"'   # 34
ssh idc03 'journalctl --user -u ada-ha-tony --since "7 days ago" -o cat | grep -c "prime injected"'  # 79
```
