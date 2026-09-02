---
category: operations
---

# Worktree Separation Strategy

## What it is

Git worktree separation strategy for organizing the chaba project into focused worktrees based on functional domains, enabling parallel development while maintaining clear project boundaries.
## Context/Background

Created 2026-08-05 as part of Chaba infrastructure documentation.


## Context

The chaba project uses Git worktrees to separate concerns:
- **chaba-h3**: Main worktree with full application ecosystem
- **chaba-raceman**: Race management tools (Track2/3/4, Raceman, Wind, Map3D)
- **chaba**: Tony Omen canonical worktree
- **chaba-tony-dell**: Tony Dell worktree
- **chaba-yomi**: Yomi LINE conversation viewer
- **master**: Main development branch
- **chaba-omen**: stale/broken overlay; do not use for canonical paths

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

## See also

- [Worktree Separation Branching](worktree-separation-branching.md)
- [Worktree Separation Organization](worktree-separation-organization.md)
- [Worktree Separation Patterns](worktree-separation-patterns.md)
