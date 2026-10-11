# Dispatch outcome — persona-tool-profiles (2026-10-11)

**Card:** `persona-tool-profiles` · **Runner:** tony-macbook
**Repos touched:** `~/CascadeProjects/ada-pi` (edit point — uncommitted on `main`), this chaba dispatch worktree (committed on dispatch branch), `idc03:~/.config/secrets/ada-kk.env` (live env).

## What changed

### ada-pi (`~/CascadeProjects/ada-pi`, uncommitted on main)

- **`backend/realtime_provider.py`** — new `ADA_INCLUDED_TOOLS` env (comma keep-list). When set, every declared tool name NOT listed is folded into the effective `excluded` set at the existing strip point (former ~L4585), so declaration stripping, family instruction-paragraph removal (`CALENDAR_/CMS_/DEVIN_/DOC_/DRIVE_/HABIT_INSTRUCTIONS`), the `ada_camera_snapshot` append gate, `tools.d` declaration filtering, and the agenda prefetch in `_session_context_tail` all behave as if the names were hand-listed. A second late-merge pass re-applies the keep-list after `tools.d`/chaba guest declarations merge. Both vars set → intersection wins.
- **`tests/test_tool_include_list.py` (new)** — 4 tests: keep-list filters builtin+tools.d; family instructions stripped; `EXCLUDED`∩`INCLUDED` intersection; late-merged declarations (camera append, tools.d) still filtered.

### chaba (dispatch worktree — commit `8e7b4c53b`)

- **`docs/ssot/apps/ssot.apps.ada-persons.yml`** — `persons.<key>.tools` profile (`instance` / `env_file` / `host` / `include` / `exclude`) plus a `tool_profiles:` doc section. `kk` gets the card's 17-tool keep-list (`capture_frame` rendered as its declared seat `vcast_snapshot`) and a 30-name explicit drop-list covering the rest of the 47-declared surface.
- **`scripts/ada/render-tool-profiles.py` (new)** — renders profiles into a managed block (`>>> chaba-rendered: ada-tool-profile … <<<`) inside `~/.config/secrets/<env_file>`; retires hand-written `ADA_*_TOOLS` lines into comments; `--apply`/`--check`/`--lint`/`--local` modes; diffs redact secret-looking values. Lint warns on (a) declared tools in NEITHER list — the merge/rename tripwire — and (b) names absent from the declared surface/alias table (stale), with a hint naming the declared seat for aliases.
- **`scripts/deploy-ada.sh`** — per-host `render-tool-profiles.py --apply` (block drift forces restart, same pattern as memory-banks.json); **added `ada-kk.service` to the idc03 service map (:8007)** — it was never in the restart list, so deploys never restarted it.
- **`docs/ssot/apps/ssot.apps.ada_ha.yml`**, **`docs/ssot/infrastructure/ssot.ada.howto.yml`** — `ADA_INCLUDED_TOOLS` documented; `add_ada_tool` runbook now states a new tool is a per-persona keep/drop decision enforced by the deploy lint.
- **`docs/ssot/jobs/ada/2026-10-11-persona-tool-profiles.yml`** — durable job trail.

### Live (idc03)

- `~/.config/secrets/ada-kk.env` — managed block written; the stale pre-merge `ADA_EXCLUDED_TOOLS` line (still naming `ada_ha_get_state`, `control_cover`, `get_habit_status`, …) retired to a comment.
- `ada-kk.service` **restarted** — process env verified: `ADA_INCLUDED_TOOLS` (17 tools) + `ADA_EXCLUDED_TOOLS` (30). HTTP 200 on `:8007/api/auth/status`. Tony-lane lures (`calendar_*`, `plan_day`, `tasks`, `devin*`, `yt`, `kanban`, `docs`, `drive`, `home_*`, `ha_confidence`, `percussion`, `track/member/device_acl`, cast/vcast screens, `ada_look`) are now stripped from ada-kk's declared surface — the cross-lane leak is closed.

## Results

- New tests: **4/4 pass** (run on idc03 venv against the patched tree — this runner has no ada-pi venv).
- `test_calendar_providers.py` (full file incl. existing excluded-tools test) + provider/memory suites: **pass** on merged upstream + patch.
- `scripts/tool-lint.py`: **clean** (47 declared: 37 builtin + 10 tools.d).
- `render-tool-profiles.py --lint`: clean — 47 declared = 17 include + 30 exclude, all names resolve.
- `--host idc03 --check`: UNCHANGED (env in sync).
- `node scripts/ssot-validate-all.mjs`: 2063/2063 valid.
- **Dogfooded the lint:** the local ada-pi checkout lagged `origin/main`, so the first census missed `percussion` (declared on prod). After ff-pulling the checkout the lint caught it and it joined the drop-list — exactly the rot pattern the card targets.

## How to verify

```bash
# chaba worktree
python3 scripts/ada/render-tool-profiles.py --lint            # clean
python3 scripts/ada/render-tool-profiles.py --host idc03 --check   # UNCHANGED

# ada-pi (edit point — uncommitted)
cd ~/CascadeProjects/ada-pi && git diff backend/realtime_provider.py

# live ada-kk
ssh idc03 'tr "\0" "\n" < /proc/$(systemctl --user show -p MainPID --value ada-kk)/environ | grep ADA_INCLUDED_TOOLS'
ssh idc03 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8007/api/auth/status'   # 200
```

## Not done / follow-up

- ada-pi changes are **uncommitted on the edit-point `main`** — ship via normal commit+push+`deploy-ada.sh` flow (dispatch does not push). Note: ada-kk's surface is already the 17-tool keep-list **today** — the deployed code predates `ADA_INCLUDED_TOOLS`, but the managed `ADA_EXCLUDED_TOOLS` (30 names = every non-kept declared tool) strips them under existing excluded-mode. The allowlist engages when the code lands and adds the anti-rot guarantee for future merges.
- Shared instances (ada-ha-tony/michael/dev) intentionally keep the full surface.
- `render-memory-banks.py` and this renderer both live under `scripts/ada/`; if env rendering grows, consider unifying.
