# ACTION

## Jump list

- [2-computer workflow (anti-drift mechanism)](#2-computer-workflow-anti-drift-mechanism)

---

## 2-computer workflow (anti-drift mechanism)

### When to use

Use this workflow whenever you are editing docs, configs, or service files on the
`idc1-assistance` branch from **more than one machine** (e.g., a laptop and a
webtop/remote desktop). Without it, concurrent edits drift apart and pushes to the
deploy branch happen by accident.

### Per-machine branch model

| Machine | Branch |
|---------|--------|
| pc1 (laptop) | `work/idc1-assistance/pc1` |
| idc1 (remote/webtop) | `work/idc1-assistance/idc1` |

**Rule:** never commit directly to `idc1-assistance`. Merge to `idc1-assistance`
via PR only when you intend to deploy.

### Step-by-step procedure

1. **Confirm which machine you are on** before typing anything:
   ```bash
   git branch --show-current
   git status -sb
   ```
   Expected: the output shows the correct per-machine branch
   (`work/idc1-assistance/pc1` or `work/idc1-assistance/idc1`), not `idc1-assistance`.

2. **Pull the latest state** of your per-machine branch:
   ```bash
   git fetch origin
   git pull --rebase origin work/idc1-assistance/<machine>
   ```

3. **Make your changes**, then record a "session stamp" at the top of any file you
   edited:
   - timestamp (ISO-8601): e.g. `2026-03-26T11:00:00Z`
   - stack version or image tag touched
   - endpoint or service affected

4. **Commit on your per-machine branch**:
   ```bash
   git add <files>
   git commit -m "docs(idc1-assistance/<machine>): <short description>"
   git push origin work/idc1-assistance/<machine>
   ```

5. **Hand off to the other machine** (if continuing work elsewhere):
   - Note the last commit SHA in your session notes or in the PR description.
   - On the other machine, pull before touching anything (see step 2).

6. **Merge to `idc1-assistance` only for deploy**:
   - Open a PR from `work/idc1-assistance/<machine>` → `idc1-assistance`.
   - Squash or rebase cleanly so the history stays linear.
   - Merge only when both machines are idle on that branch.

### Post-change verification checklist

Run these commands after every change session, on every machine that was active:

- [ ] `git branch --show-current` — confirms you are on the right per-machine branch
- [ ] `git status -sb` — no uncommitted changes remain
- [ ] `git log --oneline -5` — last 5 commits look correct (no accidental merges)
- [ ] `git fetch origin && git log HEAD..origin/idc1-assistance --oneline` — your
      branch is not behind `idc1-assistance` unexpectedly

### Drift indicators

The following are signs that drift has already occurred. If you notice any of them,
stop and say **`action`** to re-orient before continuing.

- `git branch --show-current` returns `idc1-assistance` instead of a per-machine branch
- `git status -sb` shows files modified that you did not intentionally touch
- `git log --oneline` shows a merge commit you did not create
- A deploy triggered without an explicit PR merge (accidental push to `idc1-assistance`)
- Two machines have conflicting edits to the same file with no PR between them
- Timestamps in edited files are out of order relative to the expected edit sequence
- Stack version or endpoint recorded in a file does not match what is actually running
