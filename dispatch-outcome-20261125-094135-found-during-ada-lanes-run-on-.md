# Dispatch outcome — notebooklm-rest-base-url-points-at-dead-b8ef61

## Verdict

**Fixed live.** The card's premise was half-wrong: notebooklm-rest was NOT
retired — it migrated tony-dell → idc02 on 2026-10-17 (OPS-0725) and is
healthy there (`notebooklm-rest.service` active, listening
127.0.0.1:3011 + 100.123.163.11:3011, `/health/auth` → ok, keepalive fresh).
`ssot.services.yml` already declared the correct `tailnet_url`; the stale
"retired" claim lived in `ssot.values.yml` `mcp_host_note` and propagated
into `ssot.jobs.yml` + `transcript-archive.py` docstrings. Every Ada lane
env still pointed at dead `http://100.68.142.13:3011/v1` → all
NotebooklmClient calls ConnectError'd (degraded memory recall only).

## What changed (live, outside worktree)

`NOTEBOOKLM_REST_BASE_URL` repointed `100.68.142.13:3011` →
`100.123.163.11:3011` in **11 env files** (each with
`.bak-nlmrepoint-20261125` backup):

- **idc03** ×7: `michael-ha/backend.env` (ada-ai-kraut:8003),
  `ada-chaba.env` (:8008), `ada-ha/backend.env` (:8006),
  `tony-ha/backend.env` (:8002), `kk-ha/backend.env` (:8007),
  `ada-dev.env`, `ada-kk-dev.env` (last two inactive)
- **tony-omen** ×2: `ada-dev.env`, `ada-kk-dev.env` — the dev lanes
  migrated idc03→omen 2026-11-18 and were missed by the card spec
- **mn01** ×2: `ada-ha-tony.env`, `ada-ha-michael.env` (disabled-but-running
  standby lanes)

Restarted all **9 running units**; verified `/proc/<pid>/environ` carries
the new URL on every one, 0 journal errors post-restart, and
idc03→`100.123.163.11:3011/health` = HTTP 200. Scoped-key auth verified
end-to-end (ada-michael key → 200 + exactly its 5 allowlisted notebooks).
Fleet sweep: tony-dell/con01/tony-macbook clean, idc01 offline.

## Repo changes (commit `96ed01fae7`, dispatch branch, not pushed)

- `docs/ssot/infrastructure/ssot.values.yml` — `mcp_host_note` corrected:
  REST lives on idc02, not retired
- `docs/ssot/infrastructure/ssot.jobs.yml` — ada-transcript-archive note
  corrected
- `scripts/ada/transcript-archive.py` — docstring corrected (no behaviour
  change; it uploads via `ssh mn01 podman exec notebooklm-mcp nlm`, never
  REST)
- `docs/ssot/jobs/ada/2026-11-25-notebooklm-rest-repoint.yml` — job trail

## ada-transcript-archive.timer

Healthy, no change needed: active/waiting on idc03, next Sun 2026-11-29
05:15 +07, last run 2026-11-22 uploaded 100 / 0 failed. Target = mn01
notebooklm-mcp container (Up 5 weeks).

## Follow-ups

- Sibling card `notebooklm-rest-unreachable-from-idc03-k-c38158` (OPS-0732)
  is resolved by this work — comms posted there.
- New card **ADA-1369** `ada-lane-health-gate-misses-notebooklm-dep`:
  ExecStartPre gate on kraut/tony curls MDDB :11023, not notebooklm — the
  dependency is ungated on all lanes.

## Verify

```
ssh idc03 'systemctl --user show ada-ai-kraut -p MainPID --value | xargs -I{} sh -c "tr \"\\0\" \"\\n\" < /proc/{}/environ | grep NOTEBOOKLM_REST_BASE_URL"'
# -> NOTEBOOKLM_REST_BASE_URL=http://100.123.163.11:3011/v1
curl -s http://100.123.163.11:3011/health   # from any tailnet host -> ok
```

Rollback: restore `<env>.bak-nlmrepoint-20261125` + `systemctl --user
restart <unit>`.

lessons:
- "notebooklm-rest retired" in ssot.values.yml was wrong — REST migrated to idc02; only the MCP/nlm path lives on mn01. Check ssot.services.yml host field before believing a retirement note.
- Dev lanes moved idc03→tony-omen on 2026-11-18 — card specs listing only idc03 env paths miss live consumers; always `systemctl --user list-units` + EnvironmentFiles per host.
- mn01 ada-ha-* units are disabled-but-running standby — they still consume env files and need restarts too.
- `sed -i.bak-<tag>-<date>` is the house backup convention for secrets edits; archives/attic .bak files should keep the old value intentionally.
- /proc/<pid>/environ grep is the reliable post-restart verification for EnvironmentFile changes.
