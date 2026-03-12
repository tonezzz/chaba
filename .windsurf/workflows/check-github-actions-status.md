---
description: Check GitHub Actions build status (local gh CLI)
---

# Goal
Check the latest GitHub Actions workflow run status for `tonezzz/chaba` from your local IDE machine.

# Preconditions
- `gh` is installed on your local machine.
- You are authenticated:
  - `gh auth login`
  - or set a PAT in an environment variable and login once: `echo "$GITHUB_TOKEN" | gh auth login --with-token`

# Step 1: Verify auth + API access
Run:

```bash
gh auth status
```

If auth is missing, login:

```bash
gh auth login
```

# Step 2: List latest runs for the repo
```bash
gh run list --repo tonezzz/chaba --limit 15
```

# Step 3: Filter by workflow (Publish idc1-assistance)
```bash
gh run list --repo tonezzz/chaba --workflow "Publish (idc1-assistance)" --limit 15
```

# Step 4: View details for a specific run
Replace `<RUN_ID>` with the ID from the list.

```bash
gh run view <RUN_ID> --repo tonezzz/chaba
```

# Step 5: View jobs + their conclusions (JSON)
```bash
gh run view <RUN_ID> --repo tonezzz/chaba --json status,conclusion,createdAt,updatedAt,headSha,headBranch,event,jobs
```

# Step 6: Watch live until completion
```bash
gh run watch <RUN_ID> --repo tonezzz/chaba
```

# Step 7: Show the failing logs (if any)
```bash
gh run view <RUN_ID> --repo tonezzz/chaba --log-failed
```
