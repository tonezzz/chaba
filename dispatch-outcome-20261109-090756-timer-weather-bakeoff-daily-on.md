# Dispatch outcome — timer-alert-idc03-weather-bakeoff-daily

## Result: VERIFIED RECOVERED + residual fix applied; card closed

## What was found

`weather-bakeoff-daily.service` on idc03 had failed every 07:40 run since
Nov 1 (plus manual runs Nov 7–8). Two stacked root causes:

1. **Missing env file** — `~/.config/secrets/ada-ai-kraut.env` was moved to
   `~/.config/secrets/_attic-20261023/` during the Oct-23 secrets reorg.
   The script exits 1 on `FileNotFoundError` at `load_env()`.
2. **Unreachable HA endpoint** — the env reconstructed Nov 8 ~13:33 pointed
   `HOME_ASSISTANT_URL` at `michael-ha:8123`; idc03 cannot TCP-reach it
   (asymmetric tailscale — ping OK, TCP timeout) → `URLError timed out`.

The actual fix landed **11-08 15:45** (prior session): env repointed to
`http://127.0.0.1:18123`, backed by new durable user unit
`michael-ha-via-omen-tunnel.service` (`ssh -L` via tony-omen,
`Restart=always`, enabled). Runs Nov 8 15:45 and Nov 9 07:40 both green.

## What this session changed

- **idc03** `~/.config/secrets/ada-ai-kraut.env`: merged back the missing
  GEMINI block (`ADA_GEMINI_REST_BASE_URL=http://100.102.134.91:4000`,
  `ADA_GEMINI_REST_API_KEY`, `ADA_TEXT_MODEL=gemini-3.5-flash-lite`) from
  the `_attic-20261023` backup. Key verified live against idc03 LiteLLM
  before merging. The GEMINI report row had been `n/a` since the rebuild.
- **Repo trail**: `docs/ssot/jobs/monitoring/2026-11-09-weather-bakeoff-daily-timer-alert.yml`
  (findings + lesson: check `_attic-*` dirs before reconstructing secrets).
- **Board**: posted findings, closed `timer-alert-idc03-weather-bakeoff-daily`
  and `timer-alert-idc03-kraut-rain-watch` (same env file, same root cause,
  every 30-min run green since 11-08 15:45).

## Verification

- `systemctl --user start weather-bakeoff-daily.service` at 09:10 ICT 11-09:
  full report rendered, GEMINI row live, PNG + snapshot written,
  `send: {'ok': True}` to chat 8960073266.
- Live `curl http://127.0.0.1:18123/api/config` → 200 in 80 ms (tunnel up).
- Timer next run: Tue 2026-11-10 07:40 +07.

## Still open (carded, not blocking)

`idc03-michael-ha-omen-relay` (SYS-1208): the tunnel is a workaround;
underlying idc03→michael-ha:8123 TCP failure needs HAOS firewall/ACL audit
and the tunnel needs declaring in SSOT.
