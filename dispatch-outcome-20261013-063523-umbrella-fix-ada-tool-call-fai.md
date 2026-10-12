# Dispatch outcome — umbrella-fix-ada-tool-call-failure-surfa-48054d (ADA-0525)

## What the task was
Fix the Ada tool-call failure surface behind 18 `audit-fail-*` kanban cards —
ONE pass, per the 2026-10-12 backlog triage.

## What was found
Root cause is layered, confirming the earlier triage
(`docs/ssot/jobs/ada/2026-10-10-audit-fail-cluster.yml`):

1. **Audit pipeline amplified one bad day into 18 cards.** In
   `scripts/ada/session-audit.py` every failed tool result was severity=high
   and storm-carded at ≥3 occurrences — so the 2026-10-10 gemini-quota +
   provider-drop + deploy-restart day filed a card per tool. Owner-gate
   denials ("Only the session owner…") and model arg-rejections
   ("invalid action 'list'") were misclassified as tool failures.
2. **Real bugs did exist inside the flood:** `cctv_wall` TypeError (schema
   doesn't require `action`, the signature did), `set_facial_expression`
   fell through to the runner as `Unknown tool`, `home_status` rejected a
   VALID `what='dashboard'` with a message listing it as valid (provider
   fast-path when the HA client is absent), `devin_read`'s review path is
   pinned to dead `gemini-2.5-flash`, `web_search` rejected provider
   `'google'` with no alias/enum.
3. **Three signatures are obsolete:** `percussion`, `kanban`,
   `ada_member_keys` are no longer on the ada-pi tool surface at all.

## What changed
**This repo (committed on the dispatch branch, 112657f2):**
- `scripts/ada/session-audit.py`:
  - `RE_ACL` now covers owner-gate/guest-gate/`blocked:<guard>` denials →
    `acl` (info; never cards — correct-by-design friction).
  - New `usage` class (medium) for model arg rejections (invalid
    action/what/lang/provider, unknown page/card/camera/entity, /api/states
    404) — still surfaces for schema/desc fixes, but a same-day burst can't
    storm-card.
  - Storm collapse: ≥3 same-day high-sev signatures file ONE
    `audit-storm-<day>` card listing all members; multi-day recurrences keep
    individual deduped cards.
  - Selftest fixture updated; `--selftest` PASS.
- `docs/ssot/jobs/ada/2026-10-13-ada-tool-call-failure-surface.yml` — full
  per-signature verdict table + trail.
- `docs/kb/patches/ada-pi-tool-call-failure-surface-20261013.patch` — the
  ada-pi fix as a `git am`-able patch (reports/ is gitignored; docs/kb/
  patches/ is the versioned convention).

**ada-pi (NOT pushed — edit point is tony-dell, deploy needs approval):**
local branch `dispatch/20261013-ada-tool-call-failure-surface` @ `bbb90f1`
in idc02's ada-pi clone, plus the patch file above. Fixes: cctv_wall action
default `'start'`, set_facial_expression unknown-name error (no runner
fallthrough), home_status "unavailable — no backend" for valid what with no
client, get_home_state 404 → home_search hint, media_player verb aliases,
web_search provider aliases + decl enum, cms_get_page `did_you_mean`
close-matches, ada_enroll_speaker `who='guest'` stripped on non-CHABA_MEMORY
instances, `gemini-2.5-flash` → `gemini-3.5-flash-lite` in devteam /
decision_check / document_check / web_search defaults.

**Board:** all 18 audit-fail children got per-card verdict comments; 3
obsolete (tool removed) → done, the rest → review pending deploy + next
audit run. Umbrella stays `doing` with a `requests:` gate asking approval
to land+deploy the ada-pi patch.

## Verification done
- `session-audit.py --selftest` PASS; every card's real evidence string
  re-run through `classify_result` — acl/usage/fail split verified correct
  (real bugs like the cctv_wall TypeError stay `fail`).
- ada-pi: `py_compile` clean on all 9 touched files; `tool-lint` clean with
  unchanged warning count; `test_tool_runner` (207 tests) failures identical
  to unmodified main (5 pre-existing env-dependent calendar errors); an
  initial signature-reorder regression in `cctv_wall` positional callers was
  caught by tests and corrected.

## Still open
- Landing the ada-pi patch (`git am` on tony-dell, push, `deploy-ada.sh` on
  idc03) — gated on Tony's answer to the board request.
- `chat_send` photos picker 501 needs `GPHOTO_REFRESH_TOKEN` configured on
  idc03 — config, not code (already-done card).
- After deploy + one clean audit day, verify none of the 18 signatures
  refile.
