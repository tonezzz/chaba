---
category: operations
---

# Prioritize improvements by impact
node scripts/impact-scoring.mjs prioritize
```

**Features:**
- **Analyze Mode:** Detailed impact analysis by category and status
- **Score Mode:** Calculate overall impact scores and suggest priorities
- **Prioritize Mode:** Sort improvements by impact and identify priority mismatches

**Example Output:**
```
1. 🟡 MEDIUM 7/10 - Memory Usage Optimization
   Business: 6, Technical: 8, UX: 7, Cost: 5
   Current priority: medium, Effort: 2-3 hours
```

### SSOT Integration

**SSOT Fields:**
```yaml
- label: Memory Usage Optimization
  business_impact: 6
  technical_impact: 8
  user_experience_impact: 7
  cost_savings_impact: 5
  impact_summary: Reduces infrastructure costs and improves system performance
```

**Assessment Integration:**
- Impact scores automatically analyzed during overnight assessments
- High impact improvements (≥8/10) highlighted in reports
- Impact distribution by category included in assessment results
- Priority mismatches between manual and impact-based prioritization identified

### Impact Analysis in Assessment Reports

**High Impact Improvements Section:**
- Lists all improvements with overall impact ≥ 8/10
- Shows individual impact scores and summaries
- Helps identify most valuable work to prioritize

**Impact Distribution:**
- High Impact (≥8): Count of high-value improvements
- Medium Impact (5-7): Count of moderate-value improvements
- Low Impact (<5): Count of low-value improvements

**Category Impact Averages:**
- Average impact score by category
- Identifies which categories have highest expected value
- Helps with resource allocation and category prioritization

### Impact-Based Prioritization Benefits

**Data-Driven Decisions:**
- Quantitative basis for improvement selection
- Reduces bias in prioritization decisions
- Enables comparison across different improvement types

**Resource Allocation:**
- Focus effort on highest-impact improvements
- Align resources with expected business value
- Optimize return on investment for improvement work

**Transparency:**
- Clear rationale for prioritization decisions
- Stakeholder understanding of improvement value
- Historical tracking of impact predictions vs actual results

**Continuous Improvement:**
- Track impact accuracy over time
- Refine impact scoring based on actual outcomes
- Learn which impact categories are most predictive

### Impact Scoring Integration (2026-08-05)
- **Integration**: Overnight assessment now uses shared `parseImprovements` from `impact-scoring.mjs`
- **Fix**: Resolved YAML parsing issues by importing shared parser instead of maintaining separate complex parser
- **Module Changes**:
  - `impact-scoring.mjs`: Exported `parseImprovements` and `calculateOverallImpact` functions
  - Added conditional execution guard to prevent running when imported as module
  - `overnight-assessment.mjs`: Imported shared parser, removed duplicate parsing logic
- **Results**:
  - High Impact (≥8/10): 1 (Security & Dependency Checking - 8.2/10)
  - Medium Impact (5-7/10): 15
  - Low Impact (<5/10): 2
  - Total improvements parsed: 28 (up from 18)
- **Benefits**:
  - Consistent parsing logic across scripts
  - Reduced code duplication
  - Better maintenance with single source of truth
  - Correct dependency tracking in overnight assessment

### Best Practices for Impact Scoring

**Scoring Guidelines:**
- **Be Realistic:** Avoid overestimating impact - conservative scoring is better
- **Consider Effort:** High impact with low effort should be prioritized
- **Think Long-term:** Consider both immediate and future impact
- **Be Specific:** Use impact summaries to explain scoring rationale
- **Review Regularly:** Update impact scores as understanding improves

**Priority Alignment:**
- Use impact scores to validate manual priority assignments
- Address priority mismatches (manual vs impact-based)
- Consider both impact and dependencies when planning
- Adjust manual priority if impact analysis suggests different prioritization

**Category Considerations:**
- Different categories naturally have different impact profiles
- Technical improvements may have high technical impact but low business impact
- Monitoring improvements often have high business impact through risk reduction
- Documentation improvements typically have lower immediate impact

### Integration with Existing Features

**Dependency Management:**
- Impact scores complement dependency analysis
- High impact improvements may justify breaking dependency rules
- Dependency chains can be prioritized by cumulative impact

**Git Integration:**
- Impact scores included in improvement metadata
- Track impact predictions vs actual outcomes via git history
- Link impact changes to specific commits

**Verification Loop:**
- Verify impact predictions during improvement completion
- Update impact scores based on actual results
- Learn from impact prediction accuracy

**Documentation:** See `docs/kb/dependency-management.md` for comprehensive dependency management documentation.

### Dependency Fields and Structure

**SSOT Dependency Fields:**
- **depends_on:** List of improvements that must be completed first (array or single string)
- **dependency_reason:** Explanation of why dependency exists
- **blocks:** List of improvements that cannot start until this one completes (array or single string)
- **blocking_reason:** Explanation of why this improvement blocks others

**Example SSOT Structure:**
```yaml
- label: Memory Usage Optimization
  status: pending
  priority: medium
  depends_on: GPU Queue Job History Verification
  dependency_reason: Memory analysis requires understanding GPU memory usage patterns
  blocks: System Load Analysis, GPU Process Management
  blocking_reason: Memory optimization baseline needed for load and GPU analysis
```

### Dependency Validation

**Automated Validation in Assessment:**
- Checks for missing dependencies (referenced improvements don't exist)
- Detects circular dependencies (A depends on B, B depends on A)
- Validates self-dependencies (improvement cannot depend on itself)
- Checks priority consistency (high priority shouldn't depend on low priority)
- Identifies blocked improvements (dependencies not completed)
- Reports blocking improvements (preventing others from starting)

**Validation Rules:**
- **Circular Dependencies:** Not allowed - flagged during validation
- **Missing Dependencies:** Referenced improvements must exist in SSOT
- **Self Dependencies:** An improvement cannot depend on itself
- **Status Validation:** Dependencies should be in 'completed' status before starting work
- **Priority Consistency:** Higher priority items shouldn't depend on lower priority

**Assessment Report Integration:**
- Dependency validation results included in assessment reports
- Blocked improvements listed with their dependencies
- Blocking improvements identified with downstream impact
- Critical and medium priority issues for dependency problems

**Enhanced Assessment Reports:**
- Blocked improvements identification section
- Blocking improvements reporting section
- Dependency validation results summary
- Dependency graph generation recommendations

### Dependency Graph Generation

**Graph Generation Script:** `scripts/dependency-graph.mjs`

**Usage:**
```bash
# Text format (console output)
node scripts/dependency-graph.mjs text

# Mermaid format (for documentation)
node scripts/dependency-graph.mjs mermaid

