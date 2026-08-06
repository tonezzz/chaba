---
title: Map3D Viewer
description: 3D map viewer with point clouds, Gaussian splats, and tiltable overlays for course visualization and geographic analysis.
tags: [3d, visualization, map3d, point-clouds, gaussian-splat, webgl, race-management]
created: 2026-08-06
updated: 2026-08-06
category: implementation
related: [ssot.apps.map3d.yml, ssot.apps.track4.yml, h3-pages.md]
search_keywords: [3d-map, point-cloud, gaussian-splat, webgl, visualization, course-visualization]
---

# Map3D Viewer

**Abstract**: A 3D map visualization application supporting point clouds, Gaussian splats, and tiltable overlays for race course visualization and geographic analysis.

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

## Implementation/Architecture

### 3D Rendering Engine

**WebGL/Three.js**:
- WebGL-based 3D rendering
- Three.js library for scene management
- Hardware acceleration for performance
- Cross-browser compatibility

### Data Types

**Point Clouds**:
- LiDAR point cloud data
- Photogrammetry-generated 3D points
- Elevation and color information
- Large dataset handling

**Gaussian Splats**:
- Experimental 3D rendering technique
- Efficient point-based rendering
- High-quality visual output
- Library compatibility challenges

**Map Overlays**:
- Traditional 2D map data
- Satellite imagery
- Course markings and boundaries
- Geographic reference layers

### Interactive Features

**Camera Controls**:
- Orbit controls for scene navigation
- Zoom in/out functionality
- Tilt and rotate views
- Preset viewpoints

**Layer Management**:
- Toggle different data layers
- Adjust opacity and visibility
- Layer ordering control
- Dynamic loading/unloading

### Performance Optimization

**Level of Detail**:
- Dynamic LOD based on camera distance
- Point cloud downsampling
- Frustum culling
- Memory management

## Operational Procedures

### Access

**URL**: `https://chaba.h3.gizmo-thailand.com/apps/map3d/`

**Local Development**: `http://tony-omen.local:8765/apps/map3d/` (Python server)

### Usage

1. Open Map3D Viewer
2. Load desired data layer (point cloud, splat, or overlay)
3. Use mouse/touch to navigate (orbit, zoom, tilt)
4. Toggle layers using layer controls
5. Adjust visualization settings as needed

### Data Loading

**Point Clouds**:
- Place data files in `data/` directory
- Use standard point cloud formats (PLY, PCD)
- Configure loading parameters in main.js

**Gaussian Splats**:
- Experimental format support
- Library compatibility issues
- Test with different splat viewers

## Integration Points

### Track4 Integration

**Course Visualization**:
- Load Track4 course data in 3D context
- Visualize course boundaries and buoys
- Understand terrain impact on racing
- Plan course layout with geographic context

**Data Flow**:
```
Track4 Course Data → Map3D Visualization → Geographic Analysis
```

### Raceman Integration

**Course Planning**:
- 3D visualization of planned courses
- Terrain analysis for buoy placement
- Elevation consideration for start/finish
- Wind pattern visualization

## Known Issues

### Gaussian Splat Compatibility

**Library Issues**:
- `@mkkellogg/gaussian-splats-3d` - Compatibility problems
- `@antimatter15/splat` - Limited functionality
- `react-three-fiber` - Integration challenges
- **Status**: Currently using basic splat viewer

**Workaround**:
- Use point cloud rendering as alternative
- Test with different splat libraries
- Consider custom implementation

### Performance Limitations

**Large Datasets**:
- Point clouds > 1M points may lag
- Memory usage increases with dataset size
- Mobile device performance limitations
- **Mitigation**: Use LOD and downsampling

### Browser Compatibility

**WebGL Requirements**:
- Requires WebGL-enabled browser
- Hardware acceleration needed
- Mobile browser variations
- **Recommendation**: Use modern desktop browsers

## Performance Metrics

- **Load Time**: 3-5 seconds for typical point clouds
- **Frame Rate**: 30-60 FPS depending on dataset size
- **Memory Usage**: 200-500MB for large point clouds
- **Dataset Size**: Supports up to 2M points with optimization

## Related Documentation

- **SSOT Configuration**: `docs/ssot/apps/ssot.apps.map3d.yml` - Complete technical documentation
- **Track4 Integration**: `docs/ssot/apps/ssot.apps.track4.yml` - Course visualization context
- **Test Splat**: `docs/ssot/apps/ssot.apps.test-pwa.yml` - Splat testing reference
- **chaba.h3 Pages**: `docs/kb/h3-pages.md` - Deployment patterns

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Initial creation with 3D rendering details and integration notes | tony |
