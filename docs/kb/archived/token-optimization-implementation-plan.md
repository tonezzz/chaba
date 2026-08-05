# Token Optimization Implementation Plan

## Executive Summary

This plan implements a multi-layered token optimization strategy targeting 60-80% overall token reduction. The approach prioritizes highest-impact, lowest-effort optimizations first, with proper testing and measurement at each phase.

**Expected Overall Impact**: 60-80% token reduction
**Implementation Timeline**: 3-4 sessions
**Risk Level**: Low (all changes are reversible)

## Phase Prioritization

### Phase 1: Quick Wins (Immediate) - 30-40% Savings
**Priority**: CRITICAL
**Effort**: LOW
**Risk**: MINIMAL
**Duration**: 1 session

This phase focuses on Devin configuration changes and MCP server cleanup that can be implemented immediately with minimal risk.

#### 1.1 Enable Adaptive Model
- **Action**: Set Adaptive as default model in Devin Desktop settings
- **Expected Savings**: 20-40%
- **Implementation**: 
  1. Open Devin Desktop Settings
  2. Navigate to Model Selection
  3. Set "Adaptive" as default model
  4. Test with a simple task to verify functionality
- **Rollback**: Revert to previous model selection
- **Testing**: Run 3-5 typical tasks and compare token usage vs baseline

#### 1.2 Use Free Models for Routine Tasks
- **Action**: Use SWE-1.6 for routine code changes, debugging, file operations
- **Expected Savings**: 100% for routine tasks
- **Implementation**:
  1. Identify routine task patterns (file edits, simple debugging)
  2. Select SWE-1.6 model for these tasks
  3. Reserve frontier models for complex tasks
- **Rollback**: Use frontier models for all tasks
- **Testing**: Verify SWE-1.6 handles typical routine tasks effectively

#### 1.3 MCP Server Cleanup
- **Action**: Audit and disable unused MCP servers
- **Expected Savings**: 30-50% (MCP-related)
- **Implementation**:
  1. List all configured MCP servers
  2. Identify servers not used in current workflow
  3. Disable unused servers in Devin configuration
  4. Verify remaining servers function correctly
- **Rollback**: Re-enable disabled MCP servers
- **Testing**: Test each remaining MCP server functionality

#### 1.4 Rules Optimization
- **Action**: Convert `always_on` rules to `glob` or `model_decision` where possible
- **Expected Savings**: 15-25%
- **Implementation**:
  1. Audit `.windsurfrules` for `always_on` rules
  2. Identify rules that can be conditional
  3. Convert to `glob` patterns or `model_decision`
  4. Test rule functionality after conversion
- **Rollback**: Revert to `always_on` for problematic rules
- **Testing**: Verify rules still apply when expected

### Phase 2: MCP Filtering (High Impact) - 50-70% MCP Savings
**Priority**: HIGH
**Effort**: LOW-MEDIUM
**Risk**: LOW
**Duration**: 1-2 sessions
**Dependencies**: Phase 1 complete

This phase implements mcp-filter for high-usage MCP servers to dramatically reduce tool schema overhead.

#### 2.1 Install mcp-filter
- **Action**: Install mcp-filter package
- **Expected Savings**: Foundation for MCP filtering
- **Implementation**:
  ```bash
  pip install mcp-filter
  ```
- **Rollback**: Uninstall mcp-filter
- **Testing**: Verify installation with `mcp-filter --help`

#### 2.2 Configure Yomi MCP Server Filtering
- **Action**: Filter Yomi to essential tools only
- **Expected Savings**: 70-80% (Yomi-related)
- **Implementation**:
  1. Identify essential Yomi tools: `list_conversations`, `get_chat_messages`, `get_insight`
  2. Create mcp-filter configuration for Yomi
  3. Update Devin MCP configuration to use filtered proxy
  4. Test filtered Yomi functionality
- **Rollback**: Revert to direct Yomi connection
- **Testing**: Test all essential Yomi functions work correctly

#### 2.3 Configure PostgreSQL MCP Server Filtering
- **Action**: Filter PostgreSQL to CRUD operations only
- **Expected Savings**: 60-70% (PostgreSQL-related)
- **Implementation**:
  1. Identify essential PostgreSQL tools: `query`, `execute`, `insert`, `update`, `delete`
  2. Create mcp-filter configuration for PostgreSQL
  3. Update Devin MCP configuration to use filtered proxy
  4. Test filtered PostgreSQL functionality
- **Rollback**: Revert to direct PostgreSQL connection
- **Testing**: Test database operations with filtered tools

#### 2.4 Configure GitHub MCP Server Filtering
- **Action**: Filter GitHub to core workflow tools
- **Expected Savings**: 65-75% (GitHub-related)
- **Implementation**:
  1. Identify essential GitHub tools: issues, PRs, commits
  2. Create mcp-filter configuration for GitHub
  3. Update Devin MCP configuration to use filtered proxy
  4. Test filtered GitHub functionality
- **Rollback**: Revert to direct GitHub connection
- **Testing**: Test git workflow operations with filtered tools

### Phase 3: Compression Layer (Maximum Impact) - 30-50% Data Savings
**Priority**: HIGH
**Effort**: LOW
**Risk**: LOW-MEDIUM
**Duration**: 1 session
**Dependencies**: Phase 1 complete

This phase installs Headroom proxy for maximum compression of data-heavy operations.

#### 3.1 Install Headroom Proxy
- **Action**: Install Headroom with Python 3.13
- **Expected Savings**: Foundation for compression
- **Implementation**:
  ```bash
  uv tool install --python 3.13 "headroom-ai[all]"
  ```
- **Rollback**: Uninstall Headroom
- **Testing**: Verify installation with `headroom proxy --help`

#### 3.2 Configure Headroom for Devin Desktop
- **Action**: Set up Headroom proxy and configure Devin to use it
- **Expected Savings**: 30-50% (data operations)
- **Implementation**:
  1. Start Headroom proxy: `headroom proxy --port 8787`
  2. Configure Devin Desktop to use proxy endpoint
  3. Set environment variables if needed
  4. Test Devin functionality through proxy
- **Rollback**: Remove proxy configuration from Devin
- **Testing**: Run typical Devin tasks and verify functionality

#### 3.3 Test Compression Effectiveness
- **Action**: Measure token reduction with Headroom enabled
- **Expected Savings**: 30-50%
- **Implementation**:
  1. Run baseline tasks without proxy
  2. Run same tasks with proxy
  3. Compare token usage
  4. Document compression ratios
- **Rollback**: Disable proxy if compression is ineffective
- **Testing**: Verify no functionality loss with compression

### Phase 4: Advanced Optimization (Optional) - 10-20% Additional Savings
**Priority**: MEDIUM
**Effort**: MEDIUM
**Risk**: LOW-MEDIUM
**Duration**: 1-2 sessions
**Dependencies**: Phases 2 & 3 complete

This phase evaluates TokenShift for governance and cross-agent optimization.

#### 4.1 Evaluate TokenShift for Current Setup
- **Action**: Assess TokenShift value for single-user environment
- **Expected Savings**: 10-20% (additional)
- **Implementation**:
  1. Review TokenShift features and pricing
  2. Assess governance value for current setup
  3. Evaluate cross-agent needs (Devin Desktop only)
  4. Make go/no-go decision
- **Rollback**: Not applicable (evaluation phase)
- **Testing**: N/A

#### 4.2 Pilot TokenShift (If Approved)
- **Action**: Install TokenShift on single endpoint
- **Expected Savings**: 10-20%
- **Implementation**:
  1. Install TokenShift binary
  2. Configure for Devin Desktop
  3. Test functionality
  4. Measure token reduction
- **Rollback**: Uninstall TokenShift
- **Testing**: Verify Devin functionality through TokenShift

## Testing Strategy

### Pre-Implementation Baseline
1. **Token Usage Measurement**
   - Record daily token consumption for 3 days
   - Measure per-session token usage for typical tasks
   - Document MCP server token overhead
   - Track model-specific costs

2. **Functionality Baseline**
   - Test all MCP servers function correctly
   - Verify Devin workflows work as expected
   - Document typical task completion times
   - Establish performance baseline

### Phase Testing
Each phase includes:
- **Functionality Testing**: Verify all features work correctly
- **Token Measurement**: Compare vs baseline
- **Performance Testing**: Check for latency impact
- **Rollback Testing**: Verify rollback procedures work

### Post-Implementation Monitoring
1. **Token Usage Tracking**
   - Daily token consumption
   - Per-session token usage
   - MCP server overhead reduction
   - Model-specific cost changes

2. **Performance Monitoring**
   - Task completion times
   - Proxy latency (if applicable)
   - Error rates
   - User satisfaction

## Risk Management

### Low Risk Items
- Devin configuration changes (easily reversible)
- MCP server cleanup (can re-enable)
- Rules optimization (can revert)

### Medium Risk Items
- MCP filtering (adds proxy layer)
- Headroom proxy (adds compression layer)

### Mitigation Strategies
- All changes are reversible
- Test in non-critical workflows first
- Maintain rollback documentation
- Monitor for errors or performance issues

## Success Criteria

### Quantitative Metrics
- **Overall Token Reduction**: 60-80%
- **MCP Token Reduction**: 50-70%
- **Data Operation Reduction**: 30-50%
- **Cost Savings**: Proportional to token reduction

### Qualitative Metrics
- No functionality loss
- Minimal performance impact
- Improved operational efficiency
- Better cost visibility

## Implementation Timeline

| Phase | Duration | Dependencies | Expected Savings |
|-------|----------|--------------|------------------|
| Phase 1 | 1 session | None | 30-40% |
| Phase 2 | 1-2 sessions | Phase 1 | 50-70% (MCP) |
| Phase 3 | 1 session | Phase 1 | 30-50% (data) |
| Phase 4 | 1-2 sessions | Phase 2,3 | 10-20% (additional) |

**Total Duration**: 3-4 sessions
**Cumulative Savings**: 60-80%

## Next Steps

1. **Immediate**: Start Phase 1 implementation
2. **Baseline**: Establish token usage baseline
3. **Monitor**: Track savings after each phase
4. **Adjust**: Modify approach based on results

## Documentation

- SSOT: `ssot.token-optimization.yml`
- Implementation Plan: This document
- Runbooks: To be created during implementation
- KB Entries: To be created for each optimization technique
