---
category: operations
---

# Common Patterns

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

