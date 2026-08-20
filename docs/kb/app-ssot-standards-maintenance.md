---
category: operations
---

# Maintenance

### When to Update
- New features added to the application
- Architecture changes or refactoring
- Deployment locations or methods change
- New integrations or dependencies added
- Known issues resolved or discovered

### Review Process
- Quarterly review of all app SSOT files
- Check for consistency with template
- Update status classifications as needed
- Remove deprecated apps or move to archive

## Validation

Use the ssot-validate skill to check app SSOT files:

```bash
# Validate specific app SSOT
ssot-validate docs/ssot/apps/ssot.apps.[app-name].yml

# Validate all app SSOT files
ssot-validate docs/ssot/apps/
```

