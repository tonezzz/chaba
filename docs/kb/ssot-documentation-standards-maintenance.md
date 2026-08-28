---
category: operations
---

# Synchronization Process

### Consistency Check Process
1. Compare SSOT files across all three locations
2. Identify diverged files using content comparison
3. Sync from primary source (docs/ssot/) to downstream locations
4. Verify missing files and add to all locations
5. Validate critical documentation cross-location consistency

### Synchronization Strategy
- **Primary Source**: `docs/ssot/` is always the authoritative source
- **Downstream Sync**: Changes propagate to public and web locations
- **Validation**: Cross-location verification for critical documentation
- **Archive Policy**: Completed implementation plans moved to archived/

### Cross-File Consistency
- SSOT files in `docs/ssot/` are the source of truth
- Served copies in `stacks/web/public/` should match
- Public copies in `public/docs/overview/` should match
- Run validation to check for differences

## Maintenance Workflow

### Before Making Changes
1. **Run validation**: `bash scripts/validate-configs.sh`
2. **Check for duplicates**: Review existing similar entries
3. **Consider impact**: Which files/deps will be affected?
4. **Backup current**: Ensure you can revert if needed

### Making Changes
1. **Update SSOT file**: Make your changes following the structure
2. **Run validation**: Ensure no new validation errors
3. **Test affected systems**: Run related scripts/tools
4. **Update related files**: Update documentation, configs, etc.

### After Making Changes
1. **Run full validation**: `bash scripts/validate-configs.sh`
2. **Commit with clear message**: Use conventional commit format
3. **Update served copies**: If applicable, sync to public/served directories
4. **Document changes**: Update relevant documentation

