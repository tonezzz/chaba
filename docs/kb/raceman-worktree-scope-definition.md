---
category: operations
---

# Scope Definition

### Included Services (Docker Containers)
- **raceman-php**: PHP 8.3-FPM service for PHP API endpoints
- **raceman-web**: Nginx alpine serving on port 8083
- **Network**: raceman-network (bridge network)

### Static Files (Maintained in chaba-h3)
- **Raceman static files**: chaba-h3/public/apps/raceman/ deployed to Plesk shared hosting
- **URL**: https://chaba.h3.gizmo-thailand.com/apps/raceman/

### Deployment Scope
- **Docker services**: chaba-raceman worktree (active)
- **Static files**: chaba-h3 worktree (deployed to Plesk)
- **Docker services in chaba-h3**: Not running (containers exist but not started)

## Implementation

### Docker Configuration
- **docker-compose.yml**: Defines raceman-php and raceman-web services
- **nginx.conf**: Nginx configuration for PHP routing
- **Port**: 8083 (mapped to container port 80)
- **Network**: raceman-network (bridge network)

### Static Files
- **Location**: chaba-h3/public/apps/raceman/
- **Deployment**: Plesk shared hosting at chaba.h3.gizmo-thailand.com
- **URL**: https://chaba.h3.gizmo-thailand.com/apps/raceman/

## Benefits

### 1. Clear Deployment Separation
Docker services (raceman-php, raceman-web) are isolated in raceman worktree, while static files remain in chaba-h3 for Plesk deployment.

### 2. Simplified Management
Docker services can be managed independently without affecting the main chaba-h3 web stack.

### 3. Flexible Development
Local development with docker services (port 8083) while maintaining production static deployment.

### 4. Clear Service Boundaries
- **chaba-raceman**: Docker services only
- **chaba-h3**: Static files and full application ecosystem

## Git Branch Information

- **Branch**: raceman
- **Remote**: origin/raceman (newly created)
- **Tracking**: Set up with `git push -u origin raceman`
- **Base**: Created from chaba.h3 branch
- **Location**: `/home/tony/CascadeProjects/chaba-raceman`

## Container Configuration

The raceman worktree runs isolated containers:
- **raceman-php**: PHP 8.3-FPM service for PHP API endpoints
- **raceman-web**: Nginx alpine serving on port 8083
- **Network**: raceman-network (bridge network)
- **Status**: Currently running (up 34 minutes as of 2026-08-11)

## Related Worktrees

- **chaba-h3**: Main worktree with full application ecosystem
- **chaba**: Tony Omen canonical worktree
- **chaba-tony-dell**: Tony Dell worktree
- **chaba-yomi**: Yomi LINE conversation viewer worktree
- **master**: Main development branch
- **chaba-omen**: stale/broken overlay; do not use for canonical paths

