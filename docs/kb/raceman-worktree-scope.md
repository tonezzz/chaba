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

## Scope Definition

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
- **chaba-omen**: Tony Omen host-specific worktree
- **chaba-yomi**: Yomi LINE conversation viewer worktree
- **master**: Main development branch

## Usage

### Development Workflow
1. Work in raceman worktree for docker service changes
2. Test changes locally with raceman containers (port 8083)
3. Commit to raceman branch
4. Push to origin/raceman
5. Static file changes go to chaba-h3 for Plesk deployment

### Testing
```bash
# Start containers
cd /home/tony/CascadeProjects/chaba-raceman
docker compose up -d

# Check container status
docker compose ps

# Test service
curl -s http://tony-omen.local:8083/apps/raceman/

# View logs
docker compose logs raceman-web
docker compose logs raceman-php
```

## Deployment

### Docker Services (chaba-raceman)
- **Local URL**: http://tony-omen.local:8083/apps/raceman/
- **Status**: Active and running
- **Management**: docker compose in chaba-raceman worktree

### Static Files (chaba-h3)
- **Production URL**: https://chaba.h3.gizmo-thailand.com/apps/raceman/
- **Status**: Deployed to Plesk shared hosting
- **Management**: Git push to chaba.h3 branch

## Troubleshooting

### Container Issues
If raceman containers have issues:
```bash
cd /home/tony/CascadeProjects/chaba-raceman
docker compose logs raceman-web
docker compose logs raceman-php
docker compose restart
```

### Service Not Responding
If port 8083 is not accessible:
1. Check if containers are running: `docker compose ps`
2. Check port mapping: `docker compose ps` should show 0.0.0.0:8083->80
3. Test locally: `curl -s http://localhost:8083/apps/raceman/`
4. Check hostname resolution: `ping tony-omen.local`

### Static File Changes
If static file changes aren't appearing:
1. Ensure changes are in chaba-h3/public/apps/raceman/
2. Commit and push to chaba.h3 branch
3. Plesk deployment is automatic via git push

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
