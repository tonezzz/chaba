# BUILD.md — Build / Deploy SSOT

→ Back to [ACTION.md](ACTION.md)

---

## Deploy procedure {#deploy-procedure}

> **Deploy only from `C:\chaba`** — see [CHAT_PROTOCOL.md#two-computer-guardrail](CHAT_PROTOCOL.md#two-computer-guardrail).

### Standard flow

```powershell
# 1. Pull latest main on the deploy machine
cd C:\chaba
git pull origin main

# 2. Start all PC1 stacks in dependency order
scripts/pc1-start-all-stacks.ps1

# 3. Verify health (see CONFIG.md for endpoints)
```

### Branch smoke deploy

```powershell
pwsh -File C:\chaba\scripts\deploy-branch.ps1 -Branch <branch-name>
```

---

## Stack start / stop {#stack-start-stop}

See [`docs/pc1-runbook.md`](../../../docs/pc1-runbook.md) for:
- Recommended start order (pc1-db → pc1-gpu → pc1-ai → pc1-devops → pc1-web → pc1-stack → pc1-deka)
- Stop order (reverse)
- Common issues + fixes

### Quick reference

```powershell
# Start all stacks
scripts/pc1-start-all-stacks.ps1

# Stop all stacks
scripts/pc1-stop-all-stacks.ps1

# Stop and remove volumes
scripts/pc1-stop-all-stacks.ps1 -RemoveVolumes
```

---

## Environment files {#env-files}

Each stack expects its own `.env` (copy from `.env.example`):

- `stacks/pc1-db/.env`
- `stacks/pc1-gpu/.env`
- `stacks/pc1-devops/.env`
- `stacks/pc1-web/.env`
- `stacks/pc1-stack/.env` (or `stacks/pc1-stack/.env.local` for local overrides)

Local-only overrides:

```powershell
# Use .env.local for secrets / local overrides (gitignored)
docker compose -f stacks/pc1-stack/docker-compose.yml \
  --env-file stacks/pc1-stack/.env.local \
  --profile mcp-suite up -d
```

---

## CI / CD policy {#ci-cd}

- **CI**: GitHub Actions at `.github/workflows/ci.yml` — runs on PRs to `main` and pushes to `main`.
- **Merge strategy**: Rebase and merge for PRs into `main`.
- **Local deploy policy**: only from `C:\chaba`. Worktrees (`C:\chaba_wt\...`) are for development only.

See [`docs/README.md — CI/CD`](../../../docs/README.md) for full policy.

---

## Reference

- [CONFIG.md](CONFIG.md) — endpoints to verify after deploy
- [CHECKLIST.md#deploy-checklist](CHECKLIST.md#deploy-checklist) — deploy checklist
- [`docs/pc1-runbook.md`](../../../docs/pc1-runbook.md) — full PC1 stack runbook
