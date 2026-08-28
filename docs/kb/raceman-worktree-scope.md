---
category: operations
---

# Raceman Worktree Scope Definition

## What it is

The raceman worktree is a focused Git worktree dedicated to raceman docker services (raceman-php, raceman-web), separated from the broader chaba-h3 application ecosystem to maintain clear deployment boundaries.

## Context/Background

Created 2026-08-05 as part of Chaba infrastructure documentation. Updated 2026-08-11 to reflect current deployment scope.

## Context

The raceman worktree contains the docker-compose configuration for raceman services (PHP-FPM and Nginx containers). Static files are maintained in chaba-h3/public/apps/raceman/ and deployed to Plesk shared hosting.

## Related Documentation

- `docs/kb/worktree-separation-strategy.md` - Worktree separation best practices
- `docs/kb/playwright-vs-playlive.md` - Browser automation for testing
- `chaba-raceman/docker-compose.yml` - Container configuration
- `chaba-raceman/nginx.conf` - Nginx configuration for PHP routing

## Tags

- **docker**: docker
- **containers**: containers
- **containerization**: containerization
- **php**: php
- **nginx**: nginx
- **web**: web
- **deployment**: deployment
- **worktree**: worktree
- **git**: git
- **branching**: branching
- **raceman**: raceman
- **plesk**: plesk
- **shared-hosting**: shared-hosting
- **health**: health
- **monitoring**: monitoring
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **h3**: h3
- **gizmo**: gizmo
- **thailand**: thailand
- **2026**: 2026

## See also

- [Raceman Worktree Scope Definition](raceman-worktree-scope-definition.md)
- [Raceman Worktree Usage](raceman-worktree-usage.md)
