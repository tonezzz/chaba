# LLM credit/quota outage — lane-down procedure

For `1011 prepayment credits depleted`, `1011 quota`, provider-wide 4xx
storms on a prod lane. Live sessions die mid-turn; the relay returns an
error line to the room. First seen 2026-10-12 (Gemini paid balance → 0,
ada-kk fully down ~30 min).

## Ladder — in order

1. **Identify the dead leg** — `journalctl -u ada-<lane> | grep -E "1011|429|403"`
   - `1011 credits depleted` → billing empty (AI Studio prepay = 0)
   - `1011 quota` → free-tier daily cap
   - `401 key expired` → OR rotation produced a dead key (SEC-0505 shape)

2. **Check the fallback is armed** — prod lanes declare
   `OPENROUTER_API_KEY` for degraded mode; verify it's *set and valid*
   in `~/.config/secrets/ada-<lane>.env` — on 2026-10-12 it was absent
   from `ada-kk.env`, so the declared fallback never existed.

3. **Restore** — in order of preference:
   - **Top up** at `ai.studio/projects` (TONY GATE — billing action,
     always his). Restores everything instantly.
   - **OR degraded** — requires a live `OPENROUTER_API_KEY`; text-only,
     no Live voice but the lane answers.
   - **Free key** — CANNOT carry Live sessions (~5 kills/3d on free
     tier); only useful for side-tool REST traffic, never the session.

4. **After recovery** — note the incident + duration in
   `ssot.llm-gateway.yml`, check what burned (see below), and confirm
   the fallback path stayed armed.

## Burn investigation (do this BEFORE blaming volume)

Per-session `usage summary` lines in `journalctl -u ada-<lane>` carry
input/output tokens by modality. Aggregate them:

```bash
journalctl --user -u ada-<lane> --since "24h" | grep "usage summary"
```

Watch for:
- **Text-input mega-sessions** (>500k input) — AFC tool loops re-bill
  the full context each round; `cms_read`/`memory_search` returning big
  docs inflates every subsequent turn.
- **Session count × prime size** — every turn re-sends prime + tool
  defs; a chatty room makes hundreds of sessions/day.
- Baseline found 2026-10-12: ada-ha-tony ~134M text-in/day,
  ada-kk ~8M/day at Live text-in pricing (~$0.50/1M) ≈ $70/day.

## Hardening notes

- Live-session kills and quota errors should emit ops events like
  `web_search_quota` does — an outage shouldn't need a user to notice.
- `OPENROUTER_API_KEY` belongs in every prod lane env even while OR is
  the degraded tier — an absent key converts an outage into silence.
