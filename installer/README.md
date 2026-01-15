# Distributed Service Installer

Node.js CLI for deploying and managing services across multiple remote servers over SSH. Designed to pair with the AI project in this repo for automated rollout of training/inference services.

## Features

- 🔐 **Secure SSH orchestration** via per-target credentials or key files
- ⚙️ **Config-driven deployments** (YAML) describing targets, services, and lifecycle hooks
- 🧪 **Dry-run support** to preview commands without touching servers
- 🧾 **Structured logging** with timestamps and per-target context
- 🧰 **Extensible task runners** so you can add new workflows (e.g., rollback, health checks)

## Directory layout

```
installer/
├── package.json         # Node metadata and scripts
├── README.md            # This file
├── configs/
│   └── targets.example.yaml
└── src/
    ├── cli/             # CLI entrypoint + command wiring
    ├── config/          # Config loaders + validation
    └── core/            # Business logic (SSH, logging, tasks)
        └── tasks/
```

## Getting started

1. **Install dependencies**
   ```bash
   cd installer
   npm install
   ```

2. **Copy and edit the sample config**
   ```bash
   cp configs/targets.example.yaml configs/production.yaml
   ```
   - Fill in `targets` (host, username, privateKey/password) and `services` (commands).

3. **Run a deployment**
   ```bash
   node src/cli/index.js deploy my-service --config configs/production.yaml
   ```
   Add `--dry-run` to preview commands.

4. **Check status**
   ```bash
   node src/cli/index.js status my-service --config configs/production.yaml
   ```

## Config structure (abridged)

```yaml
targets:
  - name: gpu-east
    host: 10.0.0.12
    username: deployer
    privateKey: C:\\Users\\me\\.ssh\\id_rsa
    preCommands:
      - 'sudo systemctl stop my-service'
services:
  my-service:
    artifact: s3://bucket/build.tar.gz
    setup:
      - 'tar -xf build.tar.gz'
      - 'npm install --production'
    start:
      - 'sudo systemctl restart my-service'
    status:
      - 'systemctl status my-service --no-pager'
```

## Extending tasks

Add new task modules under `src/core/tasks/` and register them in `runner.js`. Each task receives `{ config, service, dryRun, logger }`.

## Security & operations

- Prefer SSH keys with passphrases managed by an agent.
- Store secrets (e.g., passwords) via environment variables or secret managers; the CLI loads `.env` automatically.
- Couple this CLI with CI/CD (GitHub Actions, Jenkins) to trigger deployments after artifact builds.
- Consider adding monitoring hooks (Prometheus, Loki) and push logs to your central platform.
