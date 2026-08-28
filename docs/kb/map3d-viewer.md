---
category: operations
---

# Map3D Viewer
## What it is

title: Map3D Viewer


**Abstract**: A 3D map visualization application supporting point clouds, Gaussian splats, and tiltable overlays for race course visualization and geographic analysis.
## Context/Background

Created 2026-08-06 as part of Chaba infrastructure documentation.


## Overview

Map3D Viewer is a web-based 3D visualization tool that renders geographic data including point clouds, Gaussian splats, and traditional map overlays. It provides interactive 3D exploration of race course locations and surrounding terrain.

## Purpose

- **Course Visualization**: 3D visualization of race courses and surroundings
- **Terrain Analysis**: Understand geographic context and elevation changes
- **Point Cloud Rendering**: Display LiDAR or photogrammetry point cloud data
- **Gaussian Splat Testing**: Experimental 3D rendering technique evaluation
- **Interactive Exploration**: Tiltable, zoomable 3D map navigation

## Key Files

| File | Purpose |
|------|---------|
| `chaba-h3/public/apps/map3d/index.html` | Main HTML structure with 3D canvas |
| `chaba-h3/public/apps/map3d/main.js` | 3D rendering logic and scene management |
| `chaba-h3/public/apps/map3d/splat-layer.js` | Gaussian Splat rendering implementation |
| `chaba-h3/public/apps/map3d/data/` | Point cloud and splat data files |
| `docs/ssot/apps/ssot.apps.map3d.yml` | SSOT configuration and detailed documentation |

## Related Documentation

- **SSOT Configuration**: `docs/ssot/apps/ssot.apps.map3d.yml` - Complete technical documentation
- **Track4 Integration**: `docs/ssot/apps/ssot.apps.track4.yml` - Course visualization context
- **Test Splat**: `docs/ssot/apps/ssot.apps.test-pwa.yml` - Splat testing reference
- **chaba.h3 Pages**: `docs/kb/h3-pages.md` - Deployment patterns

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Initial creation with 3D rendering details and integration notes | tony |

## Tags

- **deployment**: deployment
- **ci**: ci
- **cd**: cd
- **docker**: docker
- **performance**: performance
- **optimization**: optimization
- **caching**: caching
- **testing**: testing
- **e2e**: e2e
- **automation**: automation
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **h3**: h3
- **gizmo**: gizmo
- **thailand**: thailand
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **2026**: 2026

## See also

- [Map3D Viewer Implementation](map3d-viewer-implementation.md)
- [Map3D Viewer Issues](map3d-viewer-issues.md)
