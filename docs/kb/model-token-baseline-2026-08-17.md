# Model Token Baseline — 2026-08-17

**Purpose**: Baseline snapshot for comparing GLM-5.2 vs SWE-1.7 Medium token usage and internal thinking length. Re-measure after 100+ GLM-5.2 messages.

**Source**: `~/.local/share/devin/cli/sessions.db` — `sessions.metadata` JSON column, `response_dimensions` array.

## Measurement Method

Each session's `metadata.response_dimensions` contains `CumulativeMetric` objects keyed by `uid`:
- `agent_messages` — turn count
- `input_tokens` — cumulative input tokens
- `output_tokens` — cumulative output tokens (includes internal thinking/reasoning)
- `cached_input_tokens` — cumulative cached prefix tokens

Derived metrics:
- `output_tokens/msg` — proxy for internal thinking length (lower = shorter thinking)
- `input_tokens/msg` — context overhead per turn
- `cached_input_tokens/msg` — prefix cache growth rate
- `cache/input ratio` — `cached_input_tokens / input_tokens`

## GLM-5.2 Baseline (session: tide-krypton)

| Metric | Value |
|---|---|
| model | GLM-5.2 High |
| agent_messages | 20 |
| input_tokens | 93,050 |
| output_tokens | 10,028 |
| cached_input_tokens | 605,953 |
| input_tokens/msg | 4,653 |
| output_tokens/msg | 501 |
| cached_input_tokens/msg | 30,298 |
| cache/input ratio | 6.51 |

**Notes**: First session after switching default to `glm-5-2` in `~/.config/devin/config.json`. Only 20 messages — `cached_per_msg` will grow in longer sessions.

## SWE-1.7 Medium Baseline (historical sessions)

| Session | msgs | input_tokens | output_tokens | cached_input_tokens | input/msg | output/msg | cached/msg | cache/input |
|---|---|---|---|---|---|---|---|---|
| quilted-sneezeweed | 1803 | 8,984,672 | 1,010,946 | 262,344,770 | 4,983 | 561 | 145,505 | 29.20 |
| juvenile-umbra | 1224 | 7,224,598 | 678,794 | 163,429,060 | 5,902 | 555 | 133,520 | 22.62 |
| great-consonant | 306 | 2,132,714 | 219,410 | 39,122,430 | 6,969 | 717 | 127,851 | 18.34 |
| amazing-viola | 260 | 1,748,539 | 177,768 | 35,611,070 | 6,725 | 684 | 136,966 | 20.37 |

## Comparison (GLM-5.2 vs SWE-1.7 Medium)

| Metric | GLM-5.2 (20 msgs) | SWE-1.7 (260-1803 msgs) | Delta |
|---|---|---|---|
| output_tokens/msg | 501 | 561-717 | -11% to -30% (shorter thinking) |
| input_tokens/msg | 4,653 | 4,983-6,969 | -7% to -33% (lower context overhead) |
| cached_input_tokens/msg | 30,298 | 127,851-145,505 | too early to compare (session length effect) |

## Findings

1. **GLM-5.2 supports prompt caching** through Cognition's proxy — resolves pending test in `ssot.token-optimization.yml`.
2. **GLM-5.2 has shorter internal thinking** — 11-30% fewer output tokens per message vs SWE-1.7 Medium.
3. **GLM-5.2 has lower context overhead** — 7-33% fewer input tokens per message.
4. **Caveat**: GLM-5.2 sample is only 20 messages; need re-measurement after 100+ messages to confirm output/msg stays low.

## Pending Re-measurement

After GLM-5.2 session reaches 100+ messages, re-run:
```bash
sqlite3 ~/.local/share/devin/cli/sessions.db "SELECT metadata FROM sessions WHERE id='<glm-session-id>';" | python3 -m json.tool
```

Compare against this baseline. If `output_tokens/msg` stays below 560, GLM-5.2 confirms shorter internal thinking at scale.

## Related

- SSOT: `docs/ssot/ssot.token-optimization.yml` — `Prompt Caching Model Selection` item
- Config: `~/.config/devin/config.json` — `agent.model: "glm-5-2"`
