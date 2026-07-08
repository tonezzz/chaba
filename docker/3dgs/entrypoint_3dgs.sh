#!/bin/bash
# Original 3DGS entrypoint
# Modes: train | render | metrics | help

set -e

MODE="${1:-help}"

case "$MODE" in
  train)
    shift
    echo "=== 3DGS Training ==="
    python /workspace/gaussian-splatting/train.py "$@"
    ;;
  render)
    shift
    echo "=== 3DGS Rendering ==="
    python /workspace/gaussian-splatting/render.py "$@"
    ;;
  metrics)
    shift
    echo "=== 3DGS Metrics (PSNR/SSIM/LPIPS) ==="
    python /workspace/gaussian-splatting/metrics.py "$@"
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    echo ""
    echo "Usage: docker run ... 3dgs <mode> [args]"
    echo ""
    echo "Modes:"
    echo "  train    -- Run training"
    echo "             Required: -s <source_path> -m <model_path>"
    echo "             Optional: --iterations 30000 --eval"
    echo ""
    echo "  render   -- Render trained model"
    echo "             Required: -m <model_path>"
    echo "             Optional: --iteration 30000"
    echo ""
    echo "  metrics  -- Compute PSNR/SSIM/LPIPS"
    echo "             Required: -m <model_path>"
    echo ""
    echo "  shell    -- Open bash shell inside container"
    echo ""
    echo "Examples:"
    echo "  docker compose run 3dgs train -s /data/my_scene -m /outputs/my_scene --iterations 30000"
    echo "  docker compose run 3dgs render -m /outputs/my_scene"
    echo "  docker compose run 3dgs metrics -m /outputs/my_scene"
    ;;
esac
