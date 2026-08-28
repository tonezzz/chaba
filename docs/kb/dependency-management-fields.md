---
category: operations
---

# Dependency Fields

### SSOT Field Structure

**depends_on**
- **Type**: Array of strings or single string
- **Purpose**: List of improvements that must be completed first
- **Format**: Exact improvement labels from SSOT
- **Example**: `depends_on: [Docker Compose Configuration Fix]` or `depends_on: Docker Compose Configuration Fix`

**dependency_reason**
- **Type**: String
- **Purpose**: Explanation of why dependency exists
- **Format**: Human-readable description
- **Example**: `dependency_reason: Yomi services depend on Docker compose configuration`

**blocks**
- **Type**: Array of strings or single string
- **Purpose**: List of improvements that cannot start until this one completes
- **Format**: Exact improvement labels from SSOT
- **Example**: `blocks: [System Load Analysis, GPU Process Management]`

**blocking_reason**
- **Type**: String
- **Purpose**: Explanation of why this improvement blocks others
- **Format**: Human-readable description
- **Example**: `blocking_reason: Memory optimization baseline needed for load analysis`

### Example SSOT Entry

```yaml
- label: Memory Usage Optimization
  status: pending
  priority: medium
  depends_on: GPU Queue Job History Verification
  dependency_reason: Memory analysis requires understanding GPU memory usage patterns
  blocks: System Load Analysis, GPU Process Management
  blocking_reason: Memory optimization baseline needed for load and GPU analysis
```

