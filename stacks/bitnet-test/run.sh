#!/bin/bash
# BitNet Containerized Comparison Runner

set -e

echo "============================================"
echo "BitNet CPU vs GPU Containerized Test"
echo "============================================"

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed"
    exit 1
fi

# Build image
echo ""
echo "Building BitNet image (this may take 10-15 minutes)..."
docker build -t bitnet:test .

# Run comparison
echo ""
echo "Running CPU vs GPU comparison..."
docker run --rm --gpus all bitnet:test python compare.py 2>&1 | tee results.log

echo ""
echo "============================================"
echo "Results saved to: $(pwd)/results.log"
echo "============================================"
