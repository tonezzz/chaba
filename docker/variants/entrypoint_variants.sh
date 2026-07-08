#!/bin/bash
# Variants entrypoint — 2DGS | mip-splatting | gof
# Set VARIANT env var to select: 2dgs | mip | gof

set -e

VARIANT="${VARIANT:-2dgs}"
MODE="${1:-help}"

case "$VARIANT" in
  2dgs)
    WORKDIR="/workspace/2dgs"
    TRAIN_SCRIPT="train.py"
    RENDER_SCRIPT="render.py"
    METRICS_SCRIPT="metrics.py"
    ;;
  mip)
    WORKDIR="/workspace/mip-splatting"
    TRAIN_SCRIPT="train.py"
    RENDER_SCRIPT="render.py"
    METRICS_SCRIPT="metrics.py"
    ;;
  gof)
    WORKDIR="/workspace/gof"
    TRAIN_SCRIPT="train.py"
    RENDER_SCRIPT="render.py"
    METRICS_SCRIPT="metrics.py"
    ;;
  *)
    echo "Unknown VARIANT: $VARIANT. Use: 2dgs | mip | gof"
    exit 1
    ;;
esac

echo "=== Variant: $VARIANT | Mode: $MODE ==="

case "$MODE" in
  train)
    shift
    python "$WORKDIR/$TRAIN_SCRIPT" "$@"
    ;;
  render)
    shift
    python "$WORKDIR/$RENDER_SCRIPT" "$@"
    ;;
  metrics)
    shift
    python "$WORKDIR/$METRICS_SCRIPT" "$@"
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    echo ""
    echo "Usage: VARIANT=<variant> docker compose run variants <mode> [args]"
    echo ""
    echo "VARIANT options:  2dgs | mip | gof"
    echo "Mode options:     train | render | metrics | shell"
    echo ""
    echo "Examples:"
    echo "  docker compose run -e VARIANT=2dgs variants train -s /data/scene -m /outputs/2dgs_scene"
    echo "  docker compose run -e VARIANT=mip  variants train -s /data/scene -m /outputs/mip_scene"
    echo "  docker compose run -e VARIANT=gof  variants train -s /data/scene -m /outputs/gof_scene"
    ;;
esac
