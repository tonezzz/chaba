# Cloud handoff baseline — 2026-11-26

## Launched session

| Field | Value |
|---|---|
| Card | ADA-0062 (validated spec `ada-0062`, source_hash `699114b14e12`) |
| Session id | `d8e3e0fc8d9b479bb382d8561030a68a` |
| URL | https://app.devin.ai/sessions/d8e3e0fc8d9b479bb382d8561030a68a |
| Mode | `lite` — `swe-2-medium` was rejected by the v3 API for this account (available: normal, fast, fusion, lite, ultra, fast-ultra) |
| Repo | chaba |
| Origin | api (Bearer token from `~/.local/share/devin/credentials.toml`, no secret printed) |
| Launch status | `claimed` → polled once: `running` / `working`, `acus_consumed=0.0` |
| Full response | `devin-cloud-session-baseline-2026-11-26.json` |

Scope note appended to the validated prompt: fixture mining, writing, validator/test and a runnable bench command only; do NOT attempt to run qwen3:8b / deepseek-v3.2 / fable locally (host-side models); leave the model run and first-filter decision to Tony.

## Measure after it finishes

```bash
cd /home/tony/CascadeProjects/chaba-wt-devin-handoff-proposer
python3 scripts/devnest/devin_cloud_runner.py --poll d8e3e0fc8d9b479bb382d8561030a68a
```

Latest poll: still `running / working`, `acus_consumed=0.0`, `on_demand_usage=null`, and **PR opened** — https://github.com/tonezzz/chaba/pull/240 (open).

## Second handoff (launched after 4%-used meter reading)

| Field | Value |
|---|---|
| Card / spec | DEV-1209 / `dev-1209` (validated, source_hash `1480d7bbea8f`) |
| Session | `6c6a00dd37e840be8b2ab1fbe5d3530a` |
| URL | https://app.devin.ai/sessions/6c6a00dd37e840be8b2ab1fbe5d3530a |
| Mode | `lite` |
| Gate | `--remaining-pct 96` (meter reported 4% used) |
| Launched at | 2026-11-26T12:47:25Z |

Poll it with `python3 scripts/devnest/devin_cloud_runner.py --poll 6c6a00dd37e840be8b2ab1fbe5d3530a`. Launch state is recorded in `~/.local/state/devnest/devin-cloud-runner-state.json` so neither spec will be relaunched within 24h.

Record:

1. `acus_consumed` — per-session cost signal (was 0.0 at launch).
2. `on_demand_usage` — `null` on Pro; if it ever becomes a number, paid overage was spent.
3. `pull_requests` / `status_detail` — did the quota buy a reviewable PR, or an incomplete run?
4. Daily remaining at `https://app.devin.ai/settings/usage` before/after — the authoritative quota delta (consumption API is Enterprise-only and returns 403 on Pro).

Then divide: `daily quota delta ÷ verified PRs` = real cost per useful task, which sets the daily handoff cap for the broker.
