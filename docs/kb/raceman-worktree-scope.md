# Raceman Worktree Scope Definition

## What it is

The raceman worktree is a focused Git worktree dedicated exclusively to race management tools, separated from the broader chaba-h3 application ecosystem to maintain clear project boundaries and reduce maintenance overhead.

## Context

The raceman worktree was created as an isolated environment for race management development, but initially contained unrelated applications (AI tools, watersports booking, system monitoring) that diluted its purpose. A cleanup was performed to focus the worktree exclusively on race-related functionality.

## Scope Definition

### Included Applications (Race Management Focus)
- **Track2**: Windsurf race simulation with buoys, start/finish, and leaderboard
- **Track3**: Race course guide with start/finish, buoy rounding, and guide lines
- **Track4**: Windsurf race course editor and simulator with YAML support
- **Raceman**: Race management system with course editor and simulation
- **Wind**: Wind forecast map and hourly table for race locations
- **Map3D**: 3D map viewer with point clouds and tiltable overlays for course visualization
- **Test Splat**: 3D Gaussian Splat test page for library experimentation

### Excluded Applications (Maintained in chaba-h3)
- **AI Tools**: imagen, imagen2, imagen3, raj, txt2vid (image/video generation)
- **Watersports**: reefriders, reefriders-01 (booking sites)
- **System Tools**: cams, gpu-queue, docs, overview, shared (monitoring/documentation)
- **Legacy**: track (superseded by track2/3/4)

## Implementation

### Files Removed
- **E2E Tests**: imagen2.spec.js, reeferiders.spec.js (unrelated test suites)
- **AI Apps**: public/apps/imagen/, public/apps/imagen2/, public/apps/imagen3/, public/apps/raj/, public/apps/txt2vid/
- **Watersports**: public/apps/reefriders/, public/apps/reefriders-01/
- **System**: public/apps/cams/, public/apps/gpu-queue/, public/apps/docs/, public/apps/overview/, public/apps/shared/
- **Scripts**: scripts/reefriders/, scripts/reefriders-01/

### apps.yml Changes
Updated to focus on race management:
```yaml
title: Race Management
nav:
  - label: Dashboard
    href: /
  - label: Tracks
    href: /apps/track4/
    children:
      - label: Track2
        href: /apps/track2/
      - label: Track3
        href: /apps/track3/
      - label: Track4
        href: /apps/track4/
  - label: Raceman
    href: /apps/raceman/
  - label: Wind
    href: /apps/wind/
  - label: Map3D
    href: /apps/map3d/
```

## Benefits

### 1. Clear Purpose
Raceman worktree now exclusively focused on race management tools, eliminating confusion about project scope and purpose.

### 2. Reduced Maintenance
Fewer applications to update, test, and maintain in the raceman worktree. Only race-related changes need to be tracked here.

### 3. Cleaner E2E Testing
E2E test suite now only contains track3.spec.js (2/2 passing), eliminating failures from unrelated applications.

### 4. Better Organization
Related applications are grouped logically in appropriate worktrees:
- **raceman**: Race management tools
- **chaba-h3**: Full application ecosystem (AI tools, watersports, system tools)

### 5. Smaller Deployments
Faster container builds and deployments due to reduced codebase size (701 files removed, 52,916 deletions).

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
- **Data**: apps_data/raceman/ for course persistence

## Related Worktrees

- **chaba-h3**: Main worktree with full application ecosystem
- **chaba-omen**: Tony Omen host-specific worktree
- **chaba-yomi**: Yomi LINE conversation viewer worktree
- **master**: Main development branch

## Usage

### Development Workflow
1. Work in raceman worktree for race management features
2. Test changes locally with raceman containers
3. Commit to raceman branch
4. Push to origin/raceman
5. Merge to chaba.h3 when ready for integration

### Testing
```bash
# Run E2E tests
npx playwright test e2e/track3.spec.js

# Start containers
docker compose up -d

# Check container status
docker compose ps
```

## Migration Notes

Applications removed from raceman remain available in chaba-h3:
- imagen2, imagen3, raj, txt2vid → Available via main web stack
- reefriders, reefriders-01 → Available via main web stack
- cams, gpu-queue, docs, overview → Available via main web stack

No functionality was lost - only moved to the appropriate worktree.

## Troubleshooting

### Missing Applications
If you need applications that were removed from raceman:
1. Switch to chaba-h3 worktree: `cd /home/tony/CascadeProjects/chaba-h3`
2. Applications are available in the main worktree
3. Consider if they should be added back to raceman if race-related

### Branch Tracking
If branch tracking is lost:
```bash
git branch --set-upstream-to=origin/raceman raceman
```

### Container Issues
If raceman containers have issues:
```bash
docker compose logs raceman-web
docker compose logs raceman-php
docker compose restart
```

## Related Documentation

- `docs/kb/worktree-separation-strategy.md` - Worktree separation best practices
- `docs/kb/playwright-vs-playlive.md` - Browser automation for testing
- `chaba-raceman/docker-compose.yml` - Container configuration
- `chaba-raceman/nginx.conf` - Nginx configuration for PHP routing

## Tags

raceman, worktree, scope, race-management, git, project-organization, cleanup, refactoring