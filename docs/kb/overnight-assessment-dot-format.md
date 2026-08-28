---
category: operations
---

# DOT format (for Graphviz)
node scripts/dependency-graph.mjs dot
```

**Output Formats:**
- **Text:** Human-readable dependency tree with status indicators
- **Mermaid:** Markdown-compatible graph syntax for documentation
- **DOT:** Graphviz format for visual diagrams (can generate PNG)

**Text Format Features:**
- Status indicators (✅ completed, 🚀 ready, 🔒 blocked, 📋 planned)
- Dependency chains shown with arrows
- Blocking relationships displayed
- Critical path analysis (longest dependency chain)
- Grouped by status (completed, pending, planned)

**Example Output:**
```
🔒 Memory Usage Optimization (medium)
   ↳ Depends on: GPU Queue Job History Verification
   ↳ Blocks: System Load Analysis, GPU Process Management
```

### Automatic Dependency Resolution

**Resolution Script:** `scripts/dependency-resolver.mjs`

**Usage:**
```bash
node scripts/dependency-resolver.mjs
```

**Analysis Categories:**
- **Ready to Start:** Dependencies met, can begin implementation
- **Blocked:** Dependencies not completed, must wait
- **Suggested Dependencies:** Category-based dependency suggestions
- **Priority Conflicts:** Priority inconsistencies to resolve
- **Orphan Improvements:** No dependencies or dependents, may need relationships

**Smart Suggestions:**
- Category-based dependency recommendations (GPU → Performance, Monitoring → Configuration)
- Priority conflict detection and resolution suggestions
- Orphan improvement identification for relationship building
- Ready-to-start work prioritized by priority

**Example Output:**
```
=== 🚀 Ready to Start (Dependencies Met) ===
✅ Docker Compose Configuration Fix (high)
   Category: configuration
   Effort: 5 minutes
   Suggested action: Start implementation

=== 💡 Suggested Dependencies to Add ===
💡 GPU Temperature Elevated should depend on Memory Usage Optimization
   Reason: GPU work should be optimized after general performance analysis
```

### Dependency Management Workflow

**Complete Dependency Lifecycle:**

1. **Planning Phase:**
   ```bash
   # Analyze current dependencies
   node scripts/dependency-resolver.mjs
   
   # Generate dependency graph
   node scripts/dependency-graph.mjs text
   ```

2. **Implementation Phase:**
   - Start with ready-to-start improvements (no incomplete dependencies)
   - Complete dependencies before starting dependent work
   - Update SSOT status as work progresses

3. **Validation Phase:**
   - Overnight assessment automatically validates dependencies
   - Check for circular dependencies and missing references
   - Review blocked improvements and resolve dependencies

4. **Completion Phase:**
   - Mark improvements as completed in SSOT
   - Dependent improvements become ready to start
   - Re-run dependency resolver to update recommendations

**Best Practices:**
- **Be Specific:** Use exact improvement labels for dependencies
- **Document Reasons:** Always explain why dependencies exist
- **Keep It Minimal:** Only add necessary dependencies to avoid over-constraining
- **Review Regularly:** Remove dependencies that are no longer needed
- **Test Independence:** Ensure improvements can be verified independently
- **Plan Critical Path:** Identify dependencies that form the critical path for delivery

### Integration with Feedback Loop

**Dependency-Aware Auto-Creation:**
- Auto-created improvements check for existing dependencies
- Suggests dependencies based on category patterns
- Validates priority consistency with existing improvements

**Dependency-Aware Verification:**
- Verification checks if dependencies are completed
- Blocks verification if dependencies not met
- Provides clear dependency status in verification results

**Git Integration with Dependencies:**
- Git commits linked to improvements include dependency context
- Dependency completion tracked alongside code changes
- Historical analysis of dependency patterns

### Benefits of Dependency Management

**Planning Benefits:**
- Clear understanding of work sequence
- Accurate timeline estimation
- Critical path identification
- Resource allocation optimization

**Quality Benefits:**
- Prevents starting work without prerequisites
- Ensures proper sequence of changes
- Reduces integration issues
- Improves success rate

**Communication Benefits:**
- Clear dependency visualization
- Stakeholder understanding of constraints
- Progress tracking against dependencies
- Blocker identification and resolution

**Automation Benefits:**
- Automatic dependency validation
- Smart resolution suggestions
- Graph generation for documentation
- Integration with existing feedback loop

