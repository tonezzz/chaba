# How to merge a PR in Chaba

This guide covers the full lifecycle of merging a feature or fix branch into `main`.

---

## Quick summary

| Step | Action |
|------|--------|
| 1 | Open a Pull Request targeting `main` |
| 2 | Wait for CI (`ci.yml`) to pass |
| 3 | Merge with **Rebase and merge** |
| 4 | Delete the source branch |
| 5 | Deploy from `C:\chaba` |

---

## 1. Preferred workflow — GitHub UI

1. **Push your branch** and open a Pull Request against `main`.
2. Wait for the **CI** status check (`ci.yml`) to turn green.
3. On the PR page, click the **"Rebase and merge"** button.
   - If you see a dropdown arrow next to the button, make sure to select
     *Rebase and merge* — **not** *Merge commit* or *Squash and merge*.
4. Confirm the merge.
5. Click **"Delete branch"** to keep the branch list tidy.

> **Why Rebase and merge?**
> It keeps a clean, linear history on `main` without extra merge-commit noise. The repo's GitHub settings should have *Allow merge commits* and *Allow squash merging* **disabled** so that Rebase and merge is the only option.

---

## 2. Local Git CLI (Windows / PowerShell)

Use this when you need to merge locally before pushing, e.g. to resolve conflicts first.

```powershell
# Fetch latest from origin
git fetch origin

# Rebase your branch onto the current main
git rebase origin/main

# If there are conflicts, resolve them, then:
git add <resolved-files>
git rebase --continue

# Push your rebased branch (force-push is safe here because you own the branch)
git push --force-with-lease origin <your-branch>

# Then open / update the PR on GitHub and merge via the UI (step 1 above)
```

### Merging directly into main (only while branch protection is disabled)

```powershell
# Switch to main and pull latest
git checkout main
git pull --rebase origin main

# Rebase your feature branch onto main (if not already done)
git checkout <your-branch>
git rebase main

# Switch back to main and fast-forward
git checkout main
git merge --ff-only <your-branch>

# Push
git push origin main

# Clean up local branch
git branch -d <your-branch>
git push origin --delete <your-branch>
```

> **Note:** Direct pushes to `main` are only allowed while branch protection is temporarily off (repo stabilization). Once branch protection is enabled, use the PR flow only.

---

## 3. Avoiding common pitfalls

### PowerShell stash refs
```powershell
# Always quote stash refs to avoid PowerShell brace expansion
git stash pop "stash@{0}"
git stash show -p "stash@{0}"
```

### Suppressing the merge commit editor
```powershell
git merge --no-edit <branch>
```

### Line-ending warnings (LF → CRLF)
If `git add` prints LF/CRLF warnings, align your config:
```powershell
git config --global core.autocrlf true
```

### Concurrent worktree builds
> **Never** run `docker compose up --build` for the same stack from two worktrees at the same time — port/volume conflicts will result.

---

## 4. After merging — deploy from `C:\chaba`

The deploy must run from the single authorized working copy on pc1.

```powershell
# Pull latest main into C:\chaba
cd C:\chaba
git pull --rebase origin main

# Sync secrets and restart affected stacks
pwsh ./scripts/pc1-sync-prefixed-env.ps1 -SourcePath C:\chaba\.secrets\pc1.env -Restart
```

Or trigger the self-hosted deploy workflow from GitHub → **Actions → deploy-self-hosted → Run workflow**.

### Optional: smoke deploy a branch before merging

```powershell
pwsh -File C:\chaba\scripts\deploy-branch.ps1 -Branch <branch-name>
```

---

## 5. CI checks that must pass before merge

The `ci.yml` workflow validates:

| Check | What it does |
|-------|-------------|
| Secret guard | Fails if `.env`, `.secrets/` or similar files were accidentally committed |
| Python syntax | `python -m compileall mcp` |
| Docker Compose validation | Validates `docker-compose.yml` for `pc1-stack`, `pc2-stack`, `idc1-stack` |

If any check is red, fix the issue in your branch and push again — CI will re-run automatically.

---

## See also

- `docs/README.md` — CI/CD overview, local deploy policy, secrets management
- `docs/stacks.md` — per-stack operational reference
- `.github/workflows/ci.yml` — CI workflow definition
- `.github/workflows/deploy-self-hosted.yml` — self-hosted deploy workflow
