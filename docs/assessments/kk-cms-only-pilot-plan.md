# Kaewta CMS-only memory — production pilot plan

**Status:** **APPROVED + APPLIED 2026-11-26.** KK accepted and Tony
approved (board request `kk-do-you-accept-a-reversible-3-7-day-cm-d8c11e`,
answer "approve — KK accepts, proceed with pilot"). Prod profile declared
in `persons.kk.tools` (+ new `env_knobs` support in
`render-tool-profiles.py`), applied to `kk-ha/backend.env` on idc03,
`ada-kk.service` restarted, health green. Apply evidence + pending items:
`docs/ssot/jobs/ada/2026-11-26-kk-cms-only-pilot-apply.yml`. Pilot window:
2026-11-26 → ~2026-11-29/12-03, daily checks below, then keep-or-revert.

## Goal

Decide whether the `ada-kk` production lane should answer from CMS reports
(plus `conv_journal`) without the memory-bank tools and `web_search`. The
bench now proves the read-side properties twice (1.0 on 2026-11-24 21:04
and 21:06): covered recall from a CMS page after a fresh session, honest
miss on uncovered questions, and no bank-tool leak. It does not prove that
this is better for KK in daily use.

## Preconditions

1. KK understands and accepts that she will no longer search the web or
   recall bank facts; uncovered questions get an honest "I don't have
   that". Public writes stay on `wp_*`/`cpt_post` — unchanged.
2. The branch `bench/kk-cms-only-seed-20261124` in ada-voice and
   `bench/kk-cms-only-memory-20261124` in chaba land through the normal
   review/deploy path. Do not rely on the uncommitted idc03 checkout;
   the preserved patch is `docs/assessments/ada-voice-kk-cms-only-seed.patch`.
3. Embedding/indexing health is stable (`get_indexing_status` backlog
   draining), since CMS publish fidelity depends on MDDB writes.
4. ~~A prod-specific profile is declared and reviewed.~~ **Done
   2026-11-26:** the prod profile IS `persons.kk.tools` — the five tools
   moved to `exclude:`, and `tools.env_knobs` (new
   `render-tool-profiles.py` support; `kk-bench-env.py` remains
   dev-only) carries `ADA_SESSION_PRIME=1` + `ADA_PRIME_SKIP_HISTORY=1`.
   Applied via `render-tool-profiles.py --host idc03 --apply` after the
   board approval, not via the bench toggle.

## What the pilot actually changes (plain language)

Kaewta keeps her normal persona, LINE lane, calendar/tasks and the ability
to write to KK's WordPress/boards (`wp_post`, `cpt_post`). What changes is
where she is allowed to *recall* from: the memory-bank tools
(`ada_memory_search`, `ada_remember`, `ada_forget`, `ada_session_recall`),
`web_search` and stale session history are withheld. Her recall surface is
her own CMS pages (`cms_read`, `conv_journal`) plus live calendar/tasks.

Session-start context is also tuned: `ADA_SESSION_PRIME=1` stays on (it
carries identity and the CMS page catalog), while
`ADA_PRIME_SKIP_HISTORY=1` drops recent-session summaries, channel tails,
headlines and prime-flagged facts. This is what makes "CMS-only" true — a
full prime-off removes the CMS catalog too and the model stops looking at
pages (measured 0.5 on the bench).

## Apply (only after approval)

1. Snapshot `~/.config/secrets/kk-ha/backend.env` (or the rendered prod
   env) and the output of `/api/tools` on `ada-kk` (`:8007`).
2. Render the approved prod tool block, keeping everything else in the env
   untouched. Confirm the diff contains only the declared tool changes.
3. Restart `ada-kk.service`; poll `/api/health` until 200.
4. Verify the live tool declarations: memory tools and `web_search`
   absent; `cms_read`, `conv_journal`, `wp_post`, `cpt_post` present.
5. Post one LINE message in the kk-ha group and confirm a sane tagged
   reply (the webhook cannot be synthesized).

## Pilot window and daily checks

- Duration: 3–7 days, or until any stop condition fires.
- Daily: `/api/health`, one covered recall question from a real CMS page,
  one deliberately uncovered question (must produce an honest miss), and
  a review of session-audit events for fabrication / tool-denied storms.
- Keep the dev lane on the bench profile; re-run `kk_memory_cms` twice
  after any ada-voice or prompt change — it must stay 3/3.

## What happens when CMS has no covering information

```text
user asks something
  -> she may list/read CMS (cms_read / cms_list_pages / cms_verify_page)
  -> NO covering report found
  -> honest miss: "I don't have a report about that" / "ไม่มีข้อมูลในรายงาน"
     + no invented page, no made-up URL, no silent bank recall, no web search
     + she may offer to ask Tony to create a report (wp_post/cpt_post path)
  -> the gap is visible; nothing is fabricated to fill it
```

This is the property the bench measures as `honest_miss`. If a stripped
tool is attempted anyway, the provider refuses it at dispatch with a
`tool_denied` (lane_excluded) event; the bench counts only successful calls.
Live state (calendar/tasks) is still allowed — that is not memory recall.

## Stop / rollback conditions

Revert immediately if: fabrication or invented URLs appear, KK reports a
worse experience, `tool_denied` events spike, CMS writes fail, or either
bench scenario regresses after a deploy.

Rollback: restore the env snapshot (or re-render `persons.kk.tools` with
`render-tool-profiles.py --apply`), restart `ada-kk.service`, poll
`/api/health`, re-verify `/api/tools`, LINE smoke test. Rollback should
take minutes and does not touch data — banks, CMS and calendars are
lane-scoped and unchanged by a profile flip.

## Decision at the end

Keep only if the daily checks are clean, KK prefers the answers, and the
bench stays green. Otherwise revert and record the finding in the
assessment doc. A green bench is a prerequisite, not the decision.
