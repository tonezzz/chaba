# Gaussian Splat Files

This directory contains 3D Gaussian Splat scene files for Track4 courses.

## File Format

Supported formats:
- `.ply` - Point cloud format (exported from 3DGS training)
- `.splat` - Optimized splat format
- `.ksplat` - Compressed splat format

## Metadata Schema

Each splat should have a corresponding `.json` metadata file with the same base name:

```json
{
  "name": "Course Name",
  "splatFile": "course.ply",
  "gpsBounds": [[lat1, lon1], [lat2, lon2]],
  "gpsCenter": [lat, lon],
  "sceneOffset": [x, y, z],
  "sceneScale": 1.0
}
```

### Fields

- `name`: Human-readable course name
- `splatFile`: Relative path to the splat file
- `gpsBounds`: Leaflet LatLngBounds `[[south, west], [north, east]]`
- `gpsCenter`: Reference GPS point `[lat, lon]` for coordinate mapping
- `sceneOffset`: 3D offset from reference point in meters `[x, y, z]`
- `sceneScale`: Scale factor for the scene (default 1.0)

## Integration with Course YAML

Add splat metadata to course YAML:

```yaml
splat:
  file: "splats/course-name.ply"
  bounds: [[13.5, 100.5], [13.6, 100.6]]
  center: [13.55, 100.55]
```

## Training Workflow

1. Capture drone footage of the race course area
2. Run 3DGS training in `docker/3dgs` container
3. Export `.ply` file
4. Determine GPS bounds of the captured area
5. Create metadata JSON
6. Place files in this directory
