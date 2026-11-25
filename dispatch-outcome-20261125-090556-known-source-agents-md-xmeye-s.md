# Dispatch outcome — remove-device-credentials-from-agent-rules

Card: `remove-device-credentials-from-agent-rules` (SEC-1297), lane codemod.

## What changed

- `AGENTS.md` — XMEye VMS section (~lines 323–324): removed plaintext
  authentication material and replaced with references:
  - VMS app login: was printed as a plaintext default-ish password plus its
    saved hash, duplicated across two lines. Now points to the saved hash in
    on-host `vms-runtime/config.ini` `[Login]` `password` and to the existing
    deviation record in `docs/ssot/infrastructure/ssot.security.devices.yml`
    (`xmeye-dvrs`). The hash value itself was also dropped (it is a crackable
    artifact and lives in config.ini anyway).
  - Device/DVR test password: was printed in plaintext. Now a single line
    points to `~/.config/secrets/xmeye-dvr.env` (registered as `xmeye-dvr` in
    `ssot.secrets.yml`), marked out-of-band / never commit values.
  - DVR cloud IDs and usernames (`noble-club`, `noble-a`) kept — identifiers,
    not secrets; the security register classes cloud IDs as public-ip exposure
    with credentials as the control.
- `docs/ssot/jobs/security/2026-11-25-xmeye-agents-md-credential-scrub.yml` —
  trail doc recording scope, exposure finding, and the rotation escalation.

## Result

- Diff: `AGENTS.md` only, +2/−3, plus the new jobs SSOT file. No other files
  touched — review stayed inside the known section per spec; no harvest or
  bulk credential search performed.
- Verified: post-edit grep of AGENTS.md finds no trace of the removed
  password pattern or hash prefix; section reads coherently.
- No values appear in this doc, card comms, or the jobs SSOT file.

## Exposure / follow-up (needs Tony)

- The removed password entered git history in commit `989b557d`
  (2026-10-13) and is an ancestor of `origin/master`
  (github.com:tonezzz/chaba). Editing HEAD does not purge history.
- Validity is unverified (card brief: do not quote or test). Rotation was
  NOT performed — the card authorizes no device login, rotation, or service
  change.
- Raised board request on the card with options: (a) rotate + audit
  `xmeye-dvr.env` consumers via a follow-up card (recommended — the creds
  also guard XMEye cloud P2P, classed public-ip in the security register),
  (b) declare dead/low-value and accept history exposure, (c) other.
- Observation (out of scope, not changed): `ssot.security.devices.yml`
  `xmeye-dvrs.deviations` still names the VMS app default-ish login — that
  file's job is recording deviations; flagging in case the same scrub
  standard should apply there.

## How to verify

- `git diff AGENTS.md` in the dispatch worktree — XMEye section now contains
  only references (`config.ini` saved hash, `~/.config/secrets/xmeye-dvr.env`,
  `ssot.secrets.yml`/`ssot.security.devices.yml` pointers).
- `grep -nE 'F360C0DD|amc[0-9]{3,}' AGENTS.md` → no matches.
- Board request `agents-md-scrub-is-done-...-ce8798` on the card awaits the
  rotation decision.

lessons:
- AGENTS.md edits that remove secrets still leave them in git history — always check `git merge-base --is-ancestor <exposing-commit> origin/master` and escalate rotation as an owner decision, never silently.
- Dropping a password hash alongside the plaintext is worthwhile: a saved hash in agent rules is still offline-crackable material; the on-host config.ini is the canonical store.
- `ssot.secrets.yml` slot entries (var names, not values) are the right citation when replacing inline credentials — verify the registration exists before writing the reference.
