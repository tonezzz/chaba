---
category: operations
---

# Branch Strategy

### Remote Branches
- **origin/master**: Main development branch
- **origin/chaba.h3**: Main worktree branch
- **origin/raceman**: Race management worktree branch
- **origin/chaba-omen**: stale/broken; no current branch (directory exists but .git worktree pointer is missing)
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

