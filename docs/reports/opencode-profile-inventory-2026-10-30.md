---
title: Opencode Profile Inventory
report_id: opencode-profile-inventory-2026-10-30
status: complete
task_classes: [inventory, verification]
artifact_mode: write
artifact_format: markdown
enabled_tools: [read, grep, write, edit, skill, todowrite]
verifier_type: chaba-admin
rollback_kind: ssot-research

## Opencode Profile Inventory

| Profile Name       | Status  | Task Classes       | Artifact Mode | Artifact Format | Enabled Tools                          | Verifier Type | Rollback Kind     |
|--------------------|---------|--------------------|---------------|------------------|----------------------------------------|---------------|-------------------|
| ops-readonly       | active  | [ops, research]    | read          | yaml             | read, grep, skill                      | ssot          | ssot-research     |
| doc-draft          | active  | [documentation]    | draft         | markdown         | read, write, edit, skill               | chaba-admin   | mddb-sequence     |
| artifact-write     | active  | [artwork]          | write         | markdown         | read, grep, write, edit, skill         | chaba-admin   | storage-dryrun    |
| ssot-research      | active  | [ssot, analysis]   | read          | yaml             | read, grep, skill                      | ssot          | ssot-research     |
| mddb-sequence      | active  | [mddb, sequence]   | read          | yaml             | read, grep, skill                      | mddb          | mddb-sequence     |
| storage-dryrun     | active  | [storage, testing] | read          | yaml             | read, grep, skill                      | storage       | storage-dryrun    |
| branch-code        | disabled| [branch, code]     | read          | yaml             | read, grep, skill                      | branch        | branch-code       |
|