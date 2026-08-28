#!/bin/bash
# Build all Docker images in dependency order.
# Run from the project root: ./scripts/build_all.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "============================================"
echo " Gaussian Splatting Docker — Build All"
echo "============================================"

echo ""
echo "[1/6] Building base image..."
docker build -t gaussian-splatting-base:latest docker/base/

echo ""
echo "[2/6] Building COLMAP image..."
docker build -t gaussian-splatting-colmap:latest docker/colmap/

echo ""
echo "[3/6] Building original 3DGS image..."
docker build -t gaussian-splatting-3dgs:latest docker/3dgs/

echo ""
echo "[4/6] Building Nerfstudio/gsplat image..."
docker build -t gaussian-splatting-nerfstudio:latest docker/nerfstudio/

echo ""
echo "[5/6] Building variants image (2DGS, Mip-Splatting, GOF)..."
docker build -t gaussian-splatting-variants:latest docker/variants/

echo ""
echo "[6/6] Building John the Ripper image..."
docker build -t gaussian-splatting-john:latest docker/john/

echo ""
echo "============================================"
echo " All images built successfully!"
echo "============================================"
echo ""
echo "Quick-start examples:"
echo "  docker compose run colmap"
echo "  docker compose run 3dgs train -s /data/scene -m /outputs/scene"
echo "  docker compose run nerfstudio train --data /data/processed"
echo "  docker compose run -e VARIANT=2dgs variants train -s /data/scene -m /outputs/2dgs"
echo "  docker compose run john test"
echo "  docker compose up jupyter"
