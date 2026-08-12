# Worktree Separation Strategy

## What it is

Git worktree separation strategy for organizing the chaba project into focused worktrees based on functional domains, enabling parallel development while maintaining clear project boundaries.
## Context/Background

Created 2026-08-05 as part of Chaba infrastructure documentation.


## Context

The chaba project uses Git worktrees to separate concerns:
- **chaba-h3**: Main worktree with full application ecosystem
- **chaba-raceman**: Race management tools (Track2/3/4, Raceman, Wind, Map3D)
- **chaba-omen**: Tony Omen host-specific configuration
- **chaba-yomi**: Yomi LINE conversation viewer
- **master**: Main development branch

## Worktree Organization

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

## Branch Strategy

### Remote Branches
- **origin/master**: Main development branch
- **origin/chaba.h3**: Main worktree branch
- **origin/raceman**: Race management worktree branch
- **origin/chaba-omen**: Host-specific worktree branch
- **origin/yomi**: Yomi worktree branch

### Local Branches
Each worktree has its own local branch that tracks the corresponding remote branch.

### Integration Workflow
1. Develop in focused worktree (e.g., raceman)
2. Commit to worktree branch (e.g., raceman)
3. Push to remote worktree branch (e.g., origin/raceman)
4. Merge to main branch when ready (e.g., chaba.h3 → master)

## Domain Assignment Guidelines

### When to Create a New Worktree
Create a new worktree when:
- A functional domain has clear boundaries
- Multiple developers need to work on the domain simultaneously
- The domain has distinct deployment requirements
- The domain benefits from isolated testing

### When to Use Main Worktree
Use chaba-h3 main worktree when:
- Working on cross-domain features
- Performing integration testing
- Deploying to production
- No clear domain separation exists

### Domain Boundary Criteria
Consider these factors when defining worktree scope:
- **Functional relatedness**: Apps that work together
- **Deployment requirements**: Different ports, containers, services
- **Team structure**: Different developers/teams
- **Testing requirements**: Different E2E test suites
- **Resource requirements**: Different hardware/infrastructure needs

## Common Patterns

### Application Domain
Group related applications by function:
- Race management: track2, track3, track4, raceman, wind
- AI tools: imagen, imagen2, imagen3, raj, txt2vid
- Watersports: reefriders, reefriders-01

### Host Domain
Group by deployment target:
- chaba-omen: Tony Omen specific tools
- chaba-dell: Tony Dell specific tools

### Application Domain
Group by specific application:
- chaba-yomi: Yomi LINE viewer

## Best Practices

### 1. Maintain Clear Boundaries
- Don't add unrelated applications to a focused worktree
- When in doubt, use the main worktree (chaba-h3)
- Document the purpose in the worktree's README

### 2. Minimize Cross-Worktree Dependencies
- Avoid hard dependencies between worktrees
- Use shared libraries for common functionality
- Document any necessary cross-worktree integration

### 3. Keep Worktrees in Sync
- Regularly merge main branch changes into worktrees
- Resolve conflicts promptly
- Test integration before merging back to main

### 4. Use Descriptive Names
- Name worktrees after their primary domain
- Avoid generic names like "dev" or "test"
- Include purpose in worktree documentation

### 5. Clean Up Unused Worktrees
- Remove worktrees that are no longer needed
- Archive worktrees for completed projects
- Keep worktree list manageable

## Troubleshooting

### Worktree Not Found
```bash
# List all worktrees
git worktree list

# Prune missing worktrees
git worktree prune
```

### Branch Tracking Issues
```bash
# Set upstream branch
git branch --set-upstream-to=origin/<branch> <branch>
```

### Merge Conflicts
```bash
# Fetch latest changes
git fetch origin

# Merge main branch
git merge origin/chaba.h3

# Resolve conflicts
# (manual resolution)

# Commit merge
git commit -m "Merge origin/chaba.h3 into raceman"
```

### Container Conflicts
Different worktrees may use the same ports. Configure different ports in docker-compose.yml:
- chaba-h3: 8080, 8081
- chaba-raceman: 8083
- chaba-omen: varies by service

## Related Documentation

- `docs/kb/raceman-worktree-scope.md` - Raceman worktree specific scope
- `docs/kb/git-worktree-management.md` - Git worktree technical details
- `docs/overview/ssot.apps.yml` - Application inventory across worktrees

## Tags

- **docker**: docker
- **containers**: containers
- **containerization**: containerization
- **gpu**: gpu
- **nvidia**: nvidia
- **cuda**: cuda
- **ml**: ml
- **ai**: ai
- **yomi**: yomi
- **line**: line
- **messaging**: messaging
- **conversations**: conversations
- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **monitoring**: monitoring
- **health**: health
- **metrics**: metrics
- **logging**: logging
- **deployment**: deployment
- **ci**: ci
- **cd**: cd
- **testing**: testing
- **e2e**: e2e
- **automation**: automation
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **workflow**: workflow
- **mcp**: mcp
- **h3**: h3
- **gizmo**: gizmo
- **thailand**: thailand
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **worktree**: worktree
- **git**: git
- **branching**: branching
- **raceman**: raceman
- **php**: php
- **playlive**: playlive
- **browser**: browser
- **2026**: 2026
