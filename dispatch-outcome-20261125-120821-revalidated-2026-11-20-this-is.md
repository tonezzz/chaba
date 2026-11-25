# Dispatch outcome — notebooklm-rest-unreachable-from-idc03-k-c38158

Date: 2026-11-25 · Host: mn01 · Card: OPS-0732 revalidation

## Result

**Card scope already resolved — verified live, no change needed on idc03.**
The morning dispatch (card `notebooklm-rest-base-url-points-at-dead-b8ef61`)
had already repointed every idc03 lane env and restarted the lanes. This run
re-verified by surface, not memory:

- `~/.config/secrets/michael-ha/backend.env` on idc03: `NOTEBOOKLM_REST_BASE_URL=http://100.123.163.11:3011/v1` (idc02).
- `ada-ai-kraut.service` active since 14:51 +07; `/proc/<pid>/environ` carries the idc02 URL.
- All 7 live lane envs on idc03 point at idc02 :3011/v1; zero live files retain the dead dell URL (only `.bak`/`_attic`).
- From idc03: `GET http://100.123.163.11:3011/health/auth` → HTTP 200 `{ok:true,auth:ok}`; dell endpoint still 000.
- Consumer proof: `GET /v1/notebooks` with the michael scoped key (`X-API-Key` header) from idc03 → HTTP 200.
- `journalctl -u ada-ai-kraut` since restart: 0 notebooklm/connect errors.

## Out-of-scope finding fixed (same drift class)

Fleet re-sweep found **idc02 `~/.config/secrets/ada-lab.env` still pointed at
dead tony-dell :3011** — the morning sweep covered idc03/tony-omen/mn01 envs
but not idc02 consumer envs. Fixed:

- Repointed env (backup `ada-lab.env.bak-nlmrepoint-20261125`), restarted `ada-lab.service`.
- Restart exposed a **pre-existing broken venv**: `~/CascadeProjects/ada-voice/.venv`
  was created under the old `ada-pi` path, so all 20 console-script shebangs
  (`uvicorn`, `pip`, `pytest`, …) referenced a nonexistent interpreter →
  `203/EXEC`. The old running process had masked it for ~30h.
- Repaired shebangs in `.venv/bin/*` (`ada-pi/.venv` → `ada-voice/.venv`);
  mn01 and idc03 venvs verified already clean.
- Verified: service active, `/proc` environ has idc02 URL, `:8012` HTTP 200,
  scoped `/v1/notebooks` → 200 (5 notebooks), no new errors (only a
  pre-existing unrelated `ada_adobe_stock` tool-loader warning).

## Notes / follow-ups

- ada-lab logs recurring `ha.events` connect failures to `100.68.142.13:8123`
  (Home Assistant on dell) — separate drift, not touched; card if it matters.
- con01 was unreachable via ssh (publickey denied) — env state unchecked there.
- notebooklm-rest auth is `X-API-Key`, not `Authorization: Bearer` (Bearer → 401).
- Trail: `docs/ssot/jobs/ada/2026-11-25-notebooklm-idc02-lab-repoint-venv-fix.yml`

## How to verify

```bash
ssh idc03 'grep NOTEBOOKLM_REST_BASE_URL ~/.config/secrets/michael-ha/backend.env;
  systemctl --user is-active ada-ai-kraut.service;
  curl -s http://100.123.163.11:3011/health/auth | head -c 60'
ssh idc02 'systemctl --user is-active ada-lab.service;
  curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8012/'
```

lessons:
- Morning fleet sweep missed idc02 *consumer* envs (idc02 was only audited as the REST host) — sweep `~/.config/secrets` on every host that runs an Ada lane, including the REST host itself.
- Long-running processes mask broken venv shebangs: a checkout rename (`ada-pi`→`ada-voice`) left 20 console scripts pointing at a dead interpreter; only a restart exposed it. After host checkout renames, grep `.venv/bin/*` shebangs.
- notebooklm-rest auth is the `X-API-Key` header — `Authorization: Bearer` returns 401 even with a valid scoped key.
- `.bak`/`_attic` files retain old URLs by design; when grepping secrets for stale endpoints always exclude `\.bak|_attic` or you'll chase ghosts.
