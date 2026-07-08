#!/bin/bash
# Nerfstudio entrypoint
# Modes: process | train | render | export | viewer | help

set -e

MODE="${1:-help}"

case "$MODE" in
  process)
    shift
    echo "=== Nerfstudio: Process images with COLMAP ==="
    ns-process-data images "$@"
    ;;
  process-video)
    shift
    echo "=== Nerfstudio: Process video ==="
    ns-process-data video "$@"
    ;;
  train)
    shift
    METHOD="${METHOD:-splatfacto}"
    echo "=== Nerfstudio: Training [$METHOD] ==="
    ns-train "$METHOD" \
      --viewer.websocket-port 7007 \
      --viewer.websocket-host 0.0.0.0 \
      "$@"
    ;;
  render)
    shift
    echo "=== Nerfstudio: Rendering ==="
    ns-render "$@"
    ;;
  export)
    shift
    echo "=== Nerfstudio: Exporting Gaussians ==="
    ns-export gaussian-splat "$@"
    ;;
  viewer)
    shift
    echo "=== Nerfstudio: Starting viewer ==="
    ns-viewer "$@"
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    echo ""
    echo "Usage: docker run ... nerfstudio <mode> [args]"
    echo ""
    echo "Modes:"
    echo "  process        -- Process images dir → nerfstudio dataset"
    echo "                   --data /data/my_images --output-dir /data/processed"
    echo ""
    echo "  process-video  -- Process video → nerfstudio dataset"
    echo "                   --data /data/video.mp4 --output-dir /data/processed"
    echo ""
    echo "  train          -- Train a model (set METHOD env var)"
    echo "                   METHOD=splatfacto (default) | splatfacto-big"
    echo "                   --data /data/processed"
    echo ""
    echo "  render         -- Render from a trained model"
    echo "  export         -- Export .splat / .ply file"
    echo "  viewer         -- Launch standalone web viewer"
    echo "  shell          -- Open bash shell"
    echo ""
    echo "Examples:"
    echo "  docker compose run nerfstudio process --data /data/images --output-dir /data/processed"
    echo "  docker compose run -e METHOD=splatfacto-big nerfstudio train --data /data/processed"
    ;;
esac
