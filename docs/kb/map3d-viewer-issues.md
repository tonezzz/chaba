---
category: operations
---

# Known Issues

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

