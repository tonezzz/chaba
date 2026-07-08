#!/bin/bash
# COLMAP preprocessing entrypoint
# Usage: docker run ... colmap [--source_path /data/my_scene] [--camera_model OPENCV]

set -e

SOURCE_PATH="${SOURCE_PATH:-/data/scene}"
CAMERA_MODEL="${CAMERA_MODEL:-OPENCV}"
COLMAP_BIN="colmap"

echo "=== COLMAP SfM Pipeline ==="
echo "Source: $SOURCE_PATH"
echo "Camera model: $CAMERA_MODEL"

if [[ "$1" == "--help" ]]; then
    echo ""
    echo "Usage:"
    echo "  docker run --gpus all -v /your/images:/data/scene \\"
    echo "    -e SOURCE_PATH=/data/scene \\"
    echo "    gaussian-splatting-colmap"
    echo ""
    echo "Environment variables:"
    echo "  SOURCE_PATH     Path to folder containing 'images/' subfolder (default: /data/scene)"
    echo "  CAMERA_MODEL    COLMAP camera model (default: OPENCV)"
    exit 0
fi

mkdir -p "$SOURCE_PATH/sparse/0"
mkdir -p "$SOURCE_PATH/distorted/sparse"

echo "[1/5] Feature extraction..."
$COLMAP_BIN feature_extractor \
    --database_path "$SOURCE_PATH/database.db" \
    --image_path "$SOURCE_PATH/images" \
    --ImageReader.single_camera 1 \
    --ImageReader.camera_model "$CAMERA_MODEL" \
    --SiftExtraction.use_gpu 1

echo "[2/5] Feature matching..."
$COLMAP_BIN exhaustive_matcher \
    --database_path "$SOURCE_PATH/database.db" \
    --SiftMatching.use_gpu 1

echo "[3/5] Sparse reconstruction (mapper)..."
$COLMAP_BIN mapper \
    --database_path "$SOURCE_PATH/database.db" \
    --image_path "$SOURCE_PATH/images" \
    --output_path "$SOURCE_PATH/distorted/sparse"

echo "[4/5] Image undistortion..."
$COLMAP_BIN image_undistorter \
    --image_path "$SOURCE_PATH/images" \
    --input_path "$SOURCE_PATH/distorted/sparse/0" \
    --output_path "$SOURCE_PATH" \
    --output_type COLMAP

echo "[5/5] Copying sparse model..."
cp -r "$SOURCE_PATH/sparse/0" "$SOURCE_PATH/sparse/0_backup" 2>/dev/null || true
mv "$SOURCE_PATH/sparse" "$SOURCE_PATH/sparse_full" 2>/dev/null || true
mkdir -p "$SOURCE_PATH/sparse"
cp -r "$SOURCE_PATH/distorted/sparse/0" "$SOURCE_PATH/sparse/0"

echo ""
echo "=== Done! COLMAP output ready at: $SOURCE_PATH ==="
echo "    sparse/0/  — cameras.bin, images.bin, points3D.bin"
echo "    images/    — undistorted images"
