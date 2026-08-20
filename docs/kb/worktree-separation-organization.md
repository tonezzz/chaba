---
category: operations
---

# Worktree Organization

### chaba-h3 (Main Worktree)
**Purpose**: Full application ecosystem with all tools and services

**Includes**:
- AI Tools: imagen, imagen2, imagen3, raj, txt2vid
- Race Tools: track, track2, track3, track4, raceman, wind
- Watersports: reefriders, reefriders-01
- System: cams, gpu-queue, docs, overview
- Development: test-splat, shared utilities

**Use Cases**:
- Full-stack development
- Integration testing across applications
- Production deployments
- Complete system monitoring

### chaba-raceman (Race Management)
**Purpose**: Focused race management tools development

**Includes**:
- Race Tools: track2, track3, track4, raceman, wind
- Visualization: map3d
- Testing: test-splat

**Excludes**:
- AI tools (imagen, imagen2, imagen3, raj, txt2vid)
- Watersports (reefriders, reefriders-01)
- System tools (cams, gpu-queue, docs, overview)

**Use Cases**:
- Race simulation development
- Course editor improvements
- Wind forecasting integration
- Race management system features

### chaba-omen (Host-Specific)
**Purpose**: Tony Omen host configuration and tools

**Includes**:
- Host-specific configurations
- MCP servers (playlive, mcp-llama, mcp-gpu)
- Host monitoring and control

**Use Cases**:
- Host-specific development
- MCP server management
- GPU resource management

### chaba-yomi (Application-Specific)
**Purpose**: Yomi LINE conversation viewer development

**Includes**:
- Yomi web interface
- LINE integration
- Conversation management

**Use Cases**:
- Yomi feature development
- LINE API integration
- Conversation analysis

## Benefits of Worktree Separation

### 1. Clear Purpose
Each worktree has a defined scope, reducing confusion about what belongs where.

### 2. Parallel Development
Multiple developers can work on different domains simultaneously without conflicts.

### 3. Reduced Context Switching
Developers stay focused on their domain without navigating unrelated code.

### 4. Faster Builds
Smaller worktrees build faster and use fewer resources.

### 5. Cleaner Testing
E2E tests only run relevant applications, reducing noise and maintenance.

### 6. Better Organization
Related functionality is grouped logically, improving code discoverability.

## Worktree Management

### Creating a Worktree
```bash
# Create worktree from existing branch
git worktree add <branch> <path>

# Example: Create raceman worktree
git worktree add chaba.h3 /home/tony/CascadeProjects/chaba-raceman
```

### Listing Worktrees
```bash
git worktree list
```

### Removing a Worktree
```bash
git worktree remove <path>
```

### Switching Between Worktrees
```bash
cd /home/tony/CascadeProjects/<worktree-name>
```

