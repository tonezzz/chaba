# Dispatch outcome — confirm-token-retry-expiry

**Card:** confirm-token-retry-expiry — "Confirm tokens expire between dispatch retries — double-prompt churn"
**Result:** fixed (option B — re-issue a fresh bound token in infra-class error payloads), committed on ada-pi branch `dispatch/20261010-091652-confirm-token-retry-expiry` in worktree `/home/tony/CascadeProjects/dispatch-wt-20261010-091652-confirm-token-ada` (commit `d4037a5`). Not pushed — merge guard handles promotion.

## What was wrong

The confirm gate lives in ada-pi, not chaba (`backend/tool_runner`). Sequence observed in sessions 38b18589b0 + 7a74536b32:

1. `devin` dispatch call → `_check_devin_confirmed` denies, mints `cfm-*` token (300s TTL).
2. User says yes → model replays `confirmed=true` (or the token) → gate grants and **consumes/burns** the grant → `devin_dispatch` runs → SSH to tony-dell times out → `{ok: false, error}`.
3. Model retries the identical call → the token is spent, `pending_confirm()` finds nothing live, the provider strips the self-asserted `confirmed=true` (no fresh voice affirmation) → fresh denial → Ada asks the user again ("โทเค็นหมดอายุ อีกแล้ว").

A downstream infra failure is not a new confirmation question — the grant was already given for that exact call.

## Fix

`_rearm_confirm_on_infra_failure()` in `backend/tool_runner/__init__.py`: after a gated tool returns `ok:false`, if the call carried a confirmation grant and the error is transport-class (`_INFRA_ERROR_RE` / `_INFRA_ERROR_TYPES` in `common.py` — timeout, connection refused/reset, unreachable, DNS, EOF, 502/503…), the runner mints a **fresh token bound to the same tool+args fingerprint** and attaches it to the result plus a `retry_hint` telling the model to replay the identical call and NOT re-ask.

- The retry executes with either spelling (`confirm_token=…` or `confirmed=true`, which rides `pending_confirm()`).
- Semantic failures (bad args, remote CLI errors), playbook refusals (`gate=` key), embedded denials (`NOT EXECUTED` / "requires confirmation"), unconfirmed calls, and ungated tools never re-arm.
- Applies to the whole confirm-gated surface (`CONFIRM_GATED_TOOLS` + tools.d `policy=confirmed`), not just `devin`.
- Audit: `_audit_confirmation("rearmed", …)` + `confirm_rearm` session event.
- TTL left at 300s — option A couldn't work: the grant is consumed before the tool runs, so no TTL covers a post-execution retry.
- Job trail: `ada-pi/docs/ssot/jobs/ada/2026-10-10-confirm-token-infra-rearm.yml`.

## Verification

- `ADA_INSTANCE_ID=test .venv/bin/python -m unittest tests.test_tool_runner tests.test_devin_dispatch` → **273 tests OK** (6 new `ConfirmRearmOnInfraFailureTests` cases cover rearm+retry, arg binding, `confirmed=true` resend, semantic failure, unconfirmed, ungated tool).
- Note: without `ADA_INSTANCE_ID` set, 5 `CalendarPlanMergeAliasTests` fail on `main` too — pre-existing env requirement, unrelated.
- Deploy to idc03/idc02 is a separate step (`deploy-ada.sh`) and was not done — dispatch policy.
