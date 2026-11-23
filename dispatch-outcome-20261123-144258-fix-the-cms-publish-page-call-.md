# Dispatch outcome — fix-the-cms-publish-page-call (2026-11-23 14:42)

Card: `fix-cms-publish-page-slug-argument-missi-96152a` (KNB-0624)
Attempt: 3 (attempts 1–2 died on dispatch infra — rate-limit /
INVALIDARGUMENT exit before any work ran).

## What was wrong

`cms_publish_page`'s tool declaration required `slug`, but the model
calls it with `title`+`content` only — the lazy-schema gate answered
`SchemaError: missing required 'slug'` and the publish died before the
confirm handshake. A prior session (2026-10-27) had already written the
fix as chaba-staged Drop 16
(`integrations/ada-voice/backend/cms-slug-derivation.patch`), but it was
never applied to the ada-voice repo — `origin/main` @ b006cb6 still had
`slug: str` required and no `_cms_slugify`.

## What changed

- **ada-voice** (the CMS tool repository): created worktree
  `~/CascadeProjects/tony-chaba-dell/worktrees/ada-voice/dispatch-20261123-cms-slug`
  on branch `dispatch/20261123-144258-fix-cms-publish-page-slug` off
  `origin/main` @ b006cb6 and applied the staged patch — commit `85faa77`.
  The patch makes `slug=` optional (`_cms_slugify(title)` derives it),
  keys the pending-confirm slot by the same derivation, and removes
  `slug` from the schema's `required` list. The live checkout
  (`~/CascadeProjects/ada-voice`, on `ada-consult-pr12-edit`) was left
  untouched — it carries someone else's dirty feature work.
- **chaba** (this worktree): updated
  `docs/ssot/jobs/ada/2026-10-27-cms-publish-slug-derivation.yml` —
  status `staged-not-deployed` → `landed-branch-not-deployed`, verify
  block now records this run's results — commit `379c66f820c` on
  `dispatch/20261123-144258-fix-the-cms-publish-page-call-`.

## Verification (done-condition)

- `tests/test_cms_slug_derivation.py` (added by the patch, ada-voice
  venv): **7/7 pass** — including `test_no_slug_derives_from_title`
  (register+confirm with no slug → `status: published`, slug
  `pool-notes`) and `test_thai_title_without_slug_errors_plainly`.
  No missing-argument errors for slug.
- Full ada-voice suite `.venv/bin/python -m pytest tests/ -x -q`:
  **1891 passed, 4 skipped** — no regressions from the signature change.
- `python3 scripts/tool-lint.py`: clean (60 warnings, all pre-existing
  debt counts).
- chaba-side `tests/ada/test_cms_slug_derivation_drop.py`: 6/6 pass;
  patch state vs live checkout = "applies" (still pending upstream —
  expected until the branch merges).

## Not done (explicitly out of scope for this run)

- **Push/merge**: dispatch rails say no push. The ada-voice branch
  `dispatch/20261123-144258-fix-cms-publish-page-slug` @ `85faa77` is
  ready for merge to `origin/main`.
- **Deploy**: after merge, `deploy-ada.sh` on tony-dell runs the same
  gates (tool-lint + pytest) that already pass, then restarts the idc03
  lanes. Tony approved "deploy-now" on 2026-10-29; the fix is one merge
  + one deploy away from live.
- **Runner-agent drift**: tony-dell verified clean (sha256 of
  `~/.local/bin/runner-agent` == repo copy — self-healed). Other hosts
  (idc02/idc03/mn01/tony-omen/tony-macbook) still report drift; needs
  `scp scripts/board/runner-agent.py <host>:~/.local/bin/runner-agent`
  or a sync-runner-tools run — infra task, not worktree work.

## Verify it yourself

```
cd ~/CascadeProjects/tony-chaba-dell/worktrees/ada-voice/dispatch-20261123-cms-slug
~/CascadeProjects/ada-voice/.venv/bin/python -m pytest tests/test_cms_slug_derivation.py -q
git log --oneline -1   # 85faa77
```

lessons:
- When a card says "fix X in repo Y" and chaba already holds a staged drop patch for it, the remaining work is applying the patch to the target repo — check `git apply --check`/`-R --check` tri-state before rewriting the fix.
- The live `~/CascadeProjects/ada-voice` checkout may sit on someone else's feature branch with dirty files — use `git worktree add -b dispatch/... <dir> origin/main` under `~/CascadeProjects/tony-chaba-dell/worktrees/ada-voice/` instead of touching it.
- ada-voice dispatch branches under `dispatch/*` are the established landing path — the merge-sweep picks them up like chaba branches; no push needed from the session.
- The repo's `.venv` (`~/CascadeProjects/ada-voice/.venv/bin/python`) runs any ada-voice worktree's tests — the worktree itself needs no venv.
