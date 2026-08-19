---
title: "KB backup plan"
category: operations
date: 2026-07-21
tags: [meta, backup]
status: backlog
---

> **Deferred to future work.** The plan and commands are ready; a remote URL is needed before setup.

# KB Backup Plan

## Current state

- **Primary sync:** Google Drive mirrors the `Tony AI/KB` folder across PCs.
- **Local version control:** Git history lives inside the same folder, so GDrive also syncs commit history.
- **Risk:** If GDrive corrupts the folder, deletes files, or produces unresolvable conflicts, the only copy of the KB is inside GDrive.

## Goal

Add an independent, off-site git remote so the KB history survives even if GDrive fails.

## Recommended setup

1. Create a **private** repository on GitHub, GitLab, or a self-hosted git server.
2. Add it as the `origin` remote inside the KB folder:

   ```bash
   cd "/home/tony/GoogleDrive/Tony AI/KB"
   git remote add origin https://github.com/<your-username>/<repo>.git
   # or via SSH:
   # git remote add origin git@github.com:<your-username>/<repo>.git
   ```

3. Push the current history:

   ```bash
   git branch -M main
   git push -u origin main
   ```

4. After every `kb-end.sh` commit, also push:

   ```bash
   bash ./kb-end.sh "kb: summary"
   git push
   ```

   This can be added to `kb-end.sh` later so it pushes automatically if a remote is configured.

## Alternative: local secondary copy

If you do not want a cloud remote, keep a periodic copy outside GDrive:

```bash
rsync -av --delete "/home/tony/GoogleDrive/Tony AI/KB" "/media/backup/Tony-KB-$(date +%F)"
```

Replace `/media/backup` with your USB or external drive path.

## Todo

- [ ] Decide: cloud private repo, self-hosted repo, or USB copy.
- [ ] Add the remote and perform the first push.
- [ ] Optionally update `kb-end.sh` to push automatically when a remote exists.
