#!/bin/bash
# Prepare a scene from images or video using the COLMAP container.
# Usage:
#   ./scripts/prepare_scene.sh --images /path/to/images --output /data/my_scene
#   ./scripts/prepare_scene.sh --video  /path/to/video.mp4 --output /data/my_scene

set -e

IMAGES_PATH=""
VIDEO_PATH=""
OUTPUT_PATH=""
CAMERA_MODEL="${CAMERA_MODEL:-OPENCV}"
FPS="${FPS:-2}"  # Frames per second to extract from video

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --images) IMAGES_PATH="$2"; shift ;;
        --video)  VIDEO_PATH="$2"; shift ;;
        --output) OUTPUT_PATH="$2"; shift ;;
        --fps)    FPS="$2"; shift ;;
        --camera) CAMERA_MODEL="$2"; shift ;;
        *) echo "Unknown param: $1"; exit 1 ;;
    esac
    shift
done

if [[ -z "$OUTPUT_PATH" ]]; then
    echo "Error: --output is required"
    exit 1
fi

mkdir -p "$OUTPUT_PATH/images"

# ── Video → frames ────────────────────────────────────────────────────────────
if [[ -n "$VIDEO_PATH" ]]; then
    echo "[1/2] Extracting frames from video at ${FPS}fps..."
    ffmpeg -i "$VIDEO_PATH" \
        -vf "fps=$FPS" \
        -q:v 1 \
        "$OUTPUT_PATH/images/frame_%05d.jpg"
    echo "  Extracted $(ls "$OUTPUT_PATH/images/" | wc -l) frames"

# ── Copy images ───────────────────────────────────────────────────────────────
elif [[ -n "$IMAGES_PATH" ]]; then
    echo "[1/2] Copying images..."
    cp -r "$IMAGES_PATH/." "$OUTPUT_PATH/images/"
    echo "  Copied $(ls "$OUTPUT_PATH/images/" | wc -l) images"
else
    echo "Error: provide --images or --video"
    exit 1
fi

# ── COLMAP ────────────────────────────────────────────────────────────────────
echo "[2/2] Running COLMAP SfM pipeline..."
docker compose run \
    -e SOURCE_PATH=/data/$(basename "$OUTPUT_PATH") \
    -e CAMERA_MODEL="$CAMERA_MODEL" \
    colmap

echo ""
echo "=== Scene ready! ==="
echo "    $OUTPUT_PATH/images/   — undistorted images"
echo "    $OUTPUT_PATH/sparse/0/ — COLMAP sparse model"
echo ""
echo "Now train with:"
echo "  docker compose run 3dgs train -s /data/$(basename "$OUTPUT_PATH") -m /outputs/$(basename "$OUTPUT_PATH")"
