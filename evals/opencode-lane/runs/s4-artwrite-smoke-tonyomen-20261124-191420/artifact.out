# OpenCode Lane Profiles and Write-Capacitance Summary

This note summarizes the OpenCode lane profiles discovered within the repository checkout under `evals/opencode-lane/profiles/`, detailing their intended agent tiers, execution restrictions, tool configurations, and write capabilities.

## Overview of Lane Profiles

The repository defines several distinct lane profiles tailored for specific operational stages, ranging from lightweight inspection to bounded writing and advanced code modification. Based on inspection of the profile definitions (such as `artifact-write/profile.yml` and `ops-readonly/profile.yml`), profiles enforce strict tool and permission boundaries.

### 1. Read-Only and Inspection Profiles
- **ops-readonly**: Designed for read-only host and MCP ops reports. It permits bounded inspect-only commands via an explicit bash allowlist (`hostname`, `uname`, `uptime`, `free`, `df`, `systemctl status`, etc.) and read-only MCP servers (`mcp_debug`, `mcp_health`, `mcp_read_ssot`, etc.), while denying all file writing and editing (`write: false`, `edit: false`).
- **ops-remote-read**: Remote operational read profile.
- **info-find**: Unified information-finding profile across project documentation and SSOT.
- **storage-dryrun**: Dry-run storage verification profile.

### 2. Write-Capable and Artifact-Producing Profiles
- **artifact-write**: A bounded file-write agent profile operating at stage S4. It permits the `write: true` and `edit: true` tools strictly confined to designated output roots (`evals/opencode-lane/out/`, `reports/`, `docs/reports/`), while disabling interactive shell execution (`bash: false`, `patch: false`). It serves as an evidence rung between read-only inspection and full branch-level code changes.
- **branch-code** and **branch-code-supervised-pilot**: Advanced development profiles equipped for full branch creation, code modification, and PR workflows under supervision or standard developer gates.
- **doc-draft**: Documentation drafting profile.
- **mddb-sequence**, **ssot-research**, and **gs-capture-eval**: Specialized research, SSOT querying, and evaluation capture profiles.

## Summary of Write-Capable Status

Out of the inspected lane configurations:
- **ops-readonly** represents the strictest non-mutating inspection tier, enforcing zero filesystem modification.
- **artifact-write** provides bounded, schema-validated artifact generation within isolated worktrees.
- Full code mutation and branch operations are restricted to dedicated developer profiles like **branch-code**.
