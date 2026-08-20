---
category: operations
---

# Best Practices

### Dependency Design

**Be Specific:**
- Use exact improvement labels for dependencies
- Avoid vague or ambiguous references
- Ensure labels match SSOT entries exactly

**Document Reasons:**
- Always explain why dependencies exist
- Use dependency_reason and blocking_reason fields
- Provide context for future reference
- Help others understand the relationship

**Keep It Minimal:**
- Only add necessary dependencies to avoid over-constraining
- Avoid transitive dependencies (let the system infer them)
- Remove dependencies that are no longer needed
- Review dependencies regularly

**Test Independence:**
- Ensure improvements can be verified independently
- Avoid tight coupling between improvements
- Design improvements to be testable in isolation
- Consider rollback scenarios

**Plan Critical Path:**
- Identify dependencies that form the critical path for delivery
- Prioritize work on critical path items
- Monitor critical path progress
- Adjust dependencies if critical path is too long

### Common Patterns

**Linear Chain:** A → B → C
- A must complete before B can start
- B must complete before C can start
- Critical path: A → B → C
- Use for sequential work that must be done in order

**Fan-Out:** A → [B, C, D]
- A must complete before B, C, or D can start
- B, C, D can proceed in parallel after A completes
- A is critical path item
- Use for infrastructure that enables multiple features

**Fan-In:** [A, B, C] → D
- A, B, C must all complete before D can start
- A, B, C can proceed in parallel
- Longest of A, B, C determines critical path
- Use for integration work that requires multiple components

