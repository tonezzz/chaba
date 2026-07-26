---
description: Build and deploy chaba.h3 to origin
---
1. In `/home/tony/CascadeProjects/chaba-h3`, run `git status` to see which builders need to run.
2. If `scripts/reefriders/pages/` or `public/apps/reefriders/` changed, run `just -f /home/tony/CascadeProjects/chaba-h3/Justfile build-reefriders`.
3. If `scripts/reefriders-01/pages/` or `public/apps/reefriders-01/` changed, run `just -f /home/tony/CascadeProjects/chaba-h3/Justfile build-reefriders-01`.
4. If `src/tailwind.css` or `tailwind.config.cjs` changed, run `just -f /home/tony/CascadeProjects/chaba-h3/Justfile build-css`.
5. Show the resulting `git diff --stat` and ask the user which files to stage.
6. Commit with a one-line message in the format `prefix: description` (prefix from the workspace commit-message rule).
7. Push the `chaba.h3` branch to origin.
8. Report the commit SHA and push result.
