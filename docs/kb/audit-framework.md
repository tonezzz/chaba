---
title: Chaba Audit Framework
description: Consolidated weekly and monthly audit runner for KB, SSOT, security-scan, and security-audit
tags: [audit, ssot, kb, security, operations, systemd]
created: '2026-08-19'
updated: '2026-08-19'
category: operations
status: active
related:
  - docs/ssot/infrastructure/ssot.audit.yml
  - scripts/audits/run.mjs
---

# Chaba Audit Framework

## What it is

A single SSOT-driven runner that executes all project audits and writes a normalized report. The framework replaces ad-hoc manual checks with scheduled, repeatable runs.

## Audits

| Audit | Script | Schedule | Notes |
|-------|--------|----------|-------|
| kb | `scripts/kb-audit.mjs --json` | weekly | KB coverage, freshness, and section quality |
| ssot | `scripts/ssot-validate-all.mjs` | weekly | SSOT YAML syntax and cross-reference validation |
| security-scan | `scripts/security-scan.mjs --json` | weekly | Credential and secret scan across the repo |
| security-audit | `scripts/security-audit.sh` | monthly | System-level review; runs only with `--full` |

## Running it

```bash
# Weekly default set (kb, ssot, security-scan)
node scripts/audits/run.mjs

# Monthly full set, including security-audit
node scripts/audits/run.mjs --full
```

## Outputs

After a run, `reports/audits/` contains:

- `summary.json` — machine-readable result with per-audit exit codes, durations, and output
- `summary.md` — human-readable markdown report

`reports/` is in `.gitignore`; generated reports are not committed.

## Schedule

Systemd user timers on `tony-dell`:

- `chaba-audit.timer` — weekly, default set
- `chaba-audit-full.timer` — monthly on the first Sunday at 03:00

## Verification

A test run on `tony-dell` completed successfully:

```
Running audit: kb        -> ok in 622ms
Running audit: ssot      -> ok in 5574ms
Running audit: security-scan -> ok in 51545ms
All audits passed.
```

## Related documentation

- `docs/ssot/infrastructure/ssot.audit.yml`
- `scripts/audits/run.mjs`
