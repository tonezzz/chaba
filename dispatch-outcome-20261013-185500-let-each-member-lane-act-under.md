# Dispatch outcome — member-own-google-account (2026-10-13)

## What changed (committed on this worktree branch, not pushed)

- **`scripts/ada/google-calendar-auth.py`** — piece 1+3.
  New `--manual` paste-back mode: prints the consent URL with
  `redirect_uri=http://localhost` (unregistered loopback allowed for
  installed/desktop clients); the member opens it on her phone, signs in
  as herself, Google redirects to a dead localhost page, and she sends
  back the address-bar URL — the script accepts the full URL or a bare
  `code=`, handles `error=` (access_denied), and exchanges with the same
  redirect_uri. Device flow documented as unusable: Google's device
  authorization endpoint rejects Calendar/Tasks scopes.
  New `--member`/`--service` derive the token filename convention
  `ada-google-<svc>-token[-<member>].json` (chmod 600); the memberless
  file keeps the existing shared/tony name. `--host` scp now uses the
  output basename, so `--manual --member kk --host idc03` lands
  `ada-google-calendar-token-kk.json` on the right path.
- **`scripts/ada/render-calendar-providers.py`** — piece 4 plumbing.
  New `--instance <lane>`: filters `providers:` to entries whose
  `instances:` names the lane, resolves `write:` from the new
  `calendar.lanes` map, writes `~/.config/ada/calendar-<instance>.json`
  (or the lane's declared `file:`). `lanes` is a render-time key stripped
  from output; a lane with no providers or a dangling `write:` fails
  loudly instead of writing a broken registry.
- **`docs/ssot/apps/ssot.apps.ada-calendar.yml`** — piece 4+6.
  `calendar.lanes` {tony, kk} (+ kk-dev comment: stays hand-maintained
  until a `google-kk-dev` test-calendar provider is declared).
  Providers: `google-kk` (kk's own token
  `ada-google-calendar-token-kk.json`, `status: planned` until minted,
  `tasks: true`, `calendars: [primary]`) and `google-household`
  (`status: active`, `read_only: true`, Tony's token, household + Family
  + Thai-holiday calids — the hybrid second read-provider keeping the
  shared layer on member lanes). Auth-model prose updated: per-member
  token naming, manual-paste onboarding, Testing-mode 7-day expiry +
  test-user whitelist (Error 403), and `GEMINI_API_KEY_<member>` as
  optional quota/billing credential — never identity (piece 5;
  `GEMINI_API_KEY_KK` already live per card kk-gemini-key).
- **`docs/ssot/infrastructure/ssot.ada.howto.yml`** — piece 6.
  New `member_google_onboard` runbook: publish consent screen →
  `--manual --member` mint → `--check` → declare providers → render
  lane file → `calendar-smoke.py` verify. `google_calendar_reauth`
  notes `--manual` for no-browser reauth.
- **`docs/ssot/jobs/ada/2026-10-13-member-google-identity.yml`** —
  trail doc with the ordered Tony actions.

## Verified (in-worktree)

- `py_compile` both scripts; `_token_path` naming unit checks.
- `_consent_manual` exercised with mocked exchange: full redirect URL,
  URL-encoded code, bare code, and `error=access_denied` all handled;
  exchange form sends `redirect_uri=http://localhost`.
- `--instance kk` render → 2 providers (`google-kk` planned +
  `google-household` active), `write: google-kk`, `lanes` stripped.
- `--instance tony` → `google` only; default render → all 5 providers,
  `lanes` stripped, `write: google` (back-compat).
- `--instance kk-dev` fails loudly (no providers declare it).
- All three edited/created YAML files `yaml.safe_load` clean.

## Pending Tony (board request `code-ssot-done-worktree-branch-your-part-942708` raised)

1. Publish OAuth consent screen on gen-lang-client-0694401188 (Testing =
   7-day expiry + member 403 without whitelist).
2. With Kaewta's phone: `google-calendar-auth.py --manual --member kk
   --host idc03`, LINE her the URL, paste back the redirect.
3. `--check --member kk` → confirm calids (`1c408592…` may not be
   `primary`), flip `google-kk` to `active`,
   `render-calendar-providers.py --instance kk --host idc03`.
4. Verify: `ADA_CALENDAR_FILE=~/.config/ada/calendar-kk.json
   ADA_INSTANCE_ID=kk python3 scripts/ada/calendar-smoke.py` then a live
   `calendar_read`/`calendar_write` from ada-kk. Gemini untouched —
   OAuth is identity, the API key stays project billing.

## Caveats / follow-ups

- `read_only: true` on `google-household` is declared intent — explicit
  `google-household:<calid>` write targeting still routes until ada-pi
  enforces the flag (ada-pi-side follow-up).
- `google-kk.calendars: [primary]` is best-guess — `--check --member kk`
  output should drive the final list.
- Live verification (kk lane reading via her token, kk-ha) is by
  definition post-mint; this session verified code + render + config
  shape only.
