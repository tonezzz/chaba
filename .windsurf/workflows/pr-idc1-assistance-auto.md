---
description: Create PR to idc1-assistance with auto-merge + tidy up
---

1. Ensure your keyboard/IME is in EN for terminal commands (avoid stray characters in commands).

2. Sync base branch and create a feature branch:

   - `git fetch`
   - `git checkout idc1-assistance`
   - `git pull`
   - `git checkout -b <branch>`

3. Commit your changes:

   - `git add -A`
   - `git commit -m "<message>"`
   - `git push -u origin <branch>`

4. Create a PR targeting `idc1-assistance`:

   - `gh pr create --fill --base idc1-assistance --head <branch>`

5. Enable auto-merge (and delete branch after merge):

   - `gh pr merge --auto --squash --delete-branch`

6. Tidy up locally after the PR merges:

   - `git checkout idc1-assistance`
   - `git pull`
   - `git branch -D <branch>`
