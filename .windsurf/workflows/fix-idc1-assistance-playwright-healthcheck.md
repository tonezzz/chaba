---
description: Fix idc1-assistance Playwright healthcheck (PR+merge+verify)
---

1. Create a new branch off the latest `idc1-assistance`:
   - `git fetch origin`
   - `git checkout -b fix/idc1-assistance-playwright-healthcheck origin/idc1-assistance`

2. Edit `stacks/idc1-assistance/docker-compose.yml`:
   - In service `mcp-playwright`, change healthcheck from `nc -z 127.0.0.1 3050 ...` to:
     - `curl -sS http://127.0.0.1:3050/ | grep -q 'Invalid request' || exit 1`

3. Commit and push:
   - `git add stacks/idc1-assistance/docker-compose.yml`
   - `git commit -m "fix(idc1-assistance): playwright healthcheck without nc"`
   - `git push -u origin fix/idc1-assistance-playwright-healthcheck`

4. Open PR and merge into `idc1-assistance` (requires GitHub CLI auth):
   - `gh pr create --base idc1-assistance --head fix/idc1-assistance-playwright-healthcheck --title "fix(idc1-assistance): playwright healthcheck" --body "Fix mcp-playwright healthcheck: nc is missing in Playwright image; use curl+grep probe."`
   - `gh pr merge --merge --delete-branch`

5. Trigger Portainer redeploy of the `idc1-assistance` stack (git-backed). Wait for redeploy to finish.

6. Verify on idc1:
   - `ssh -i C:\Users\hp\.ssh\chaba_ed25519 chaba@idc1.surf-thailand.com "docker inspect idc1-assistance-mcp-playwright-1 --format '{{json .Config.Healthcheck}}'"`
   - `ssh -i C:\Users\hp\.ssh\chaba_ed25519 chaba@idc1.surf-thailand.com "docker inspect idc1-assistance-mcp-playwright-1 --format '{{.State.Health.Status}} {{.State.Health.FailingStreak}}'"`
