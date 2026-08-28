---
name: ssot-validate
description: Validate SSOT YAML files for syntax and structure
allowed-tools:
  - read
  - exec
triggers:
  - user
  - model
---

Validate all SSOT YAML files in docs/ssot/:

1. Find all SSOT YAML files:
   - Look for files matching pattern: docs/ssot/**/*.yml
   - Exclude template file: template.yml

2. For each SSOT file, validate:
   - YAML syntax is valid (can be parsed)
   - Required top-level fields exist: title (except for config-type SSOT files)
   - If sections exist, validate each section has:
     * title field
     * icon field
     * layout field (list, grid, or timeline)
     * items array (if layout requires it)
   - Check for duplicate section titles within the same file
   - Check for duplicate item labels within the same section
   - Allow flexible structures for config-type files (ssot.health.yml, ssot.gpu.yml, etc.)

3. Report results:
   - List all files checked
   - Show any errors found with specific file and line numbers
   - Show any warnings (missing optional but recommended fields)
   - Summary: X files checked, Y errors, Z warnings

4. If errors found, suggest fixes:
   - For syntax errors: Check YAML indentation and quoting
   - For missing fields: Add the required field
   - For duplicates: Rename or consolidate entries

5. Exit with summary:
   - If all valid: "All SSOT files are valid"
   - If issues found: "X SSOT files have validation issues"
