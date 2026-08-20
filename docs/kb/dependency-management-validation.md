---
category: operations
---

# Dependency Validation

### Automated Validation Rules

**Circular Dependencies**
- Not allowed - flagged during validation
- Example: A depends on B, B depends on A
- Detected by overnight assessment script
- Reported as critical issue

**Missing Dependencies**
- Referenced improvements must exist in SSOT
- Checked against all improvement labels
- Reported as medium issue
- Must be resolved before dependency tracking works

**Self Dependencies**
- An improvement cannot depend on itself
- Trivial validation check
- Reported as medium issue

**Status Validation**
- Dependencies should be in 'completed' status before starting work
- Checks if dependencies are pending or planned
- Reports blocked improvements
- Helps identify ready-to-start work

**Priority Consistency**
- Higher priority items shouldn't depend on lower priority
- Example: high priority depends on low priority
- Reported as medium issue
- Suggests priority adjustment

### Validation Implementation

**File:** `scripts/overnight-assessment.mjs`

**Validation Function:**
```javascript
function validateDependencies(improvements) {
  const issues = [];

  // Check for circular dependencies
  // Check for missing dependencies
  // Check for self dependencies
  // Check priority consistency
  // Identify blocked improvements

  return issues;
}
```

**Assessment Report Integration:**
- Dependency validation results included in assessment reports
- Blocked improvements listed with their dependencies
- Blocking improvements identified with downstream impact
- Critical and medium priority issues for dependency problems

## Dependency Graph Generation

### Graph Generation Script

**File:** `scripts/dependency-graph.mjs`

### Usage

```bash
# Text format (console output)
node scripts/dependency-graph.mjs text

# Mermaid format (for documentation)
node scripts/dependency-graph.mjs mermaid

# DOT format (for Graphviz)
node scripts/dependency-graph.mjs dot
```

### Output Formats

**Text Format:**
- Human-readable dependency tree
- Status indicators (✅ completed, 🚀 ready, 🔒 blocked, 📋 planned)
- Dependency chains shown with arrows
- Blocking relationships displayed
- Critical path analysis (longest dependency chain)
- Grouped by status (completed, pending, planned)

**Example Text Output:**
```
🔒 Memory Usage Optimization (medium)
   ↳ Depends on: GPU Queue Job History Verification
   ↳ Blocks: System Load Analysis, GPU Process Management

✅ GPU Queue Job History Verification (high)
   ↳ Status: completed
   ↳ Blocks: Memory Usage Optimization
```

**Mermaid Format:**
- Markdown-compatible graph syntax
- Can be rendered in GitHub, GitLab, etc.
- Suitable for documentation
- Visual representation of dependencies

**DOT Format:**
- Graphviz format for visual diagrams
- Can generate PNG, SVG, PDF
- Professional diagram generation
- Customizable styling

