# Dispatch outcome — ada lanes on deleted ada-pi venv (ADA-0033)

Card: `ada-lanes-run-on-deleted-ada-pi-venv-res-df9c81`
Date: 2026-11-24 ~21:30–21:45 +07 (14:30–14:45 UTC)

## What was done

Restarted every lane process still executing on the deleted
`~/CascadeProjects/ada-pi/.venv`, sequenced one at a time during a
verified zero-established-connections window.

### idc03 — 4 dirty lanes restarted (all verified clean)

| unit | port | old pid | new pid | restart (+07) | ws smoke |
|---|---|---|---|---|---|
| ada-chaba | 8008 | 3723 | 3215397 | 21:34 | PASS |
| ada-kk | 8007 | 5975 | 3217279 | 21:35 | PASS |
| ada-ha-ada | 8006 | 7279 | 3225904 | 21:36 | PASS |
| ada-ha-tony | 8002 | 3878 | 3242571 | 21:40 | PASS |

Per lane: `systemctl --user restart` → `/api/health` 200 → new
`/proc/<pid>/cmdline` argv[0] = `ada-voice/.venv/bin/python` →
1-turn `scenario-live.py` ws smoke PASS → 0 tracebacks/FileNotFoundError
in journal since restart.

### Already clean — no restart needed

- **idc03**: `ada-ai-kraut` (:8003) and `ada-kk-dev` (:8009) were restarted
  post-repair today; all four relays use explicit `python -m` (immune to
  the shebang bug); `ada-bankq-student` uses the open-jev venv;
  `ada-stt` is a compiled binary.
- **mn01**: `ada-ha-tony` and `ada-ha-michael` both started today AFTER
  the shebang repair — cmdline + `/proc/maps` confirm ada-voice site-packages.
  `pgrep -af ada-pi/.venv` = 0 on mn01. The card's mn01 concern was stale.

## Key detection detail

`/proc/<pid>/cmdline` argv[0] is the reliable dirty-check: console-script
shebangs record the interpreter path literally, so dirty processes show
`ada-pi/.venv/bin/python` even though `exe(5)` resolves through the
venv-python symlink to `/usr/bin/python3.12`. `pgrep -af 'ada-pi/.venv'`
is the fleet audit one-liner. `/proc/maps` is NOT reliable (0 hits even
when dirty — no extension modules loaded yet).

## Findings carded

- **ADA-1328** `notebooklm-rest-base-url-points-at-dead-b8ef61` — all lane
  envs point `NOTEBOOKLM_REST_BASE_URL` at tony-dell:3011 where
  `notebooklm-rest.service` is masked+dead. Caused one degraded
  `notebooklm failed: All connection attempts failed` log on ada-chaba
  during smoke (session still passed). Pre-existing drift, unrelated to
  the venv fix; the ExecStartPre gate checks MDDB (:11023), not notebooklm.
- Pre-existing `ada_adobe_stock` tools.d declaration error on chaba/tony —
  unchanged by this work, noted in job doc.

## Trail

- Job doc: `docs/ssot/jobs/ada/2026-11-24-ada-lanes-venv-restart.yml`
- Smoke scenario (throwaway, on idc03): `/tmp/venv-restart-smoke.yaml`

## How to verify

```
ssh idc03 'pgrep -af "ada-pi/.venv"'        # expect: no output
ssh idc03 'systemctl --user is-active ada-chaba ada-kk ada-ha-ada ada-ha-tony'  # all active
ssh idc03 'for p in 8002 8006 8007 8008; do curl -sf localhost:$p/api/health >/dev/null && echo "$p ok"; done'
```

lessons:
- Dirty-venv detection: check `/proc/<pid>/cmdline` argv[0], not `/proc/<pid>/exe` (symlink-resolved) or `/proc/<pid>/maps` (pure-python site-packages never mmap).
- `pgrep -af 'ada-pi/.venv'` is the fleet-wide audit one-liner for stale-shebang processes.
- `ss -tn state established '( sport = :PORT )'` per lane port is a fast low-traffic check before restarting voice lanes.
- `scenario-live.py` + a 1-turn `response_nonempty` yaml is a cheap real-LLM ws smoke that exercises the lazy-import path that killed sessions.
- Lane env `NOTEBOOKLM_REST_BASE_URL` points at a masked-dead service on tony-dell — carded ADA-1328; notebooklm recall is degraded fleet-wide until fixed.
