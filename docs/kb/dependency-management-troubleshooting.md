---
category: operations
---

# Troubleshooting

### Common Issues

**Circular Dependency Detected:**
- **Symptom**: Assessment reports circular dependency
- **Cause**: A depends on B, B depends on A
- **Resolution**: Remove one direction of dependency
- **Prevention**: Review dependency graph before adding

**Missing Dependency Reference:**
- **Symptom**: Assessment reports missing dependency
- **Cause**: Referenced improvement doesn't exist in SSOT
- **Resolution**: Add missing improvement or fix reference
- **Prevention**: Use exact labels from SSOT

**Priority Conflict:**
- **Symptom**: High priority depends on low priority
- **Cause**: Priority levels don't match dependency direction
- **Resolution**: Elevate priority of dependency or adjust relationship
- **Prevention**: Review priority when adding dependencies

**Too Many Blocked Improvements:**
- **Symptom**: Many improvements blocked by single item
- **Cause**: Over-constraining dependencies
- **Resolution**: Remove unnecessary dependencies
- **Prevention**: Keep dependencies minimal

### Validation Errors

**Assessment Fails:**
- Check SSOT file syntax (YAML validation)
- Verify all improvement labels are unique
- Ensure all referenced improvements exist
- Review circular dependency detection logic

**Graph Generation Fails:**
- Check for circular dependencies
- Verify improvement labels are consistent
- Ensure all dependencies reference valid improvements
- Review graph generation script logs

