---
category: operations
---

# Cutover Criteria

### Technical Criteria
- ✅ All KB content migrated to MDDB
- ✅ Semantic search working with Ollama
- ✅ Web UI stable and performant
- ✅ MCP integration functional
- ✅ Backup and restore procedures tested
- ✅ Google Drive sync operational
- ✅ No critical bugs or performance issues

### User Acceptance Criteria
- Team trained on MDDB interface
- Quick reference guides available
- Feedback collected and addressed
- No major usability concerns
- Team comfortable with MDDB workflow

### Operational Criteria
- Monitoring and alerting configured
- Disaster recovery procedures documented
- Support procedures established
- Performance benchmarks met
- Security configuration reviewed

## Rollback Procedures

### Phase 1 Rollback
**Trigger**: Critical bugs or usability issues with MDDB

**Actions**:
- Continue using old KB as primary
- Address MDDB issues
- Re-evaluate migration timeline
- Consider alternative solutions

### Phase 2 Rollback
**Trigger**: Workflow integration issues or team resistance

**Actions**:
- Revert documentation references to old KB
- Continue parallel operation
- Address integration issues
- Provide additional training

### Phase 3 Rollback
**Trigger**: Performance issues or critical bugs in production

**Actions**:
- Switch primary usage back to old KB
- Keep MDDB as secondary system
- Address production issues
- Re-evaluate cutover timeline

### Phase 4 Rollback
**Trigger**: Critical failure after hard cutover

**Actions**:
- Restore old KB from archive
- Revert all workflow changes
- Investigate failure root cause
- Plan alternative migration approach

