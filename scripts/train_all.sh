#!/bin/bash
# Run the same scene through ALL implementations for comparison.
# Usage: ./scripts/train_all.sh /data/my_scene

set -e

SCENE_PATH="${1:-/data/scene}"
OUTPUT_BASE="${2:-/outputs}"
ITERATIONS="${ITERATIONS:-30000}"

echo "============================================"
echo " Gaussian Splatting — Train All Variants"
echo "============================================"
echo " Scene:      $SCENE_PATH"
echo " Output:     $OUTPUT_BASE"
echo " Iterations: $ITERATIONS"
echo ""

run_and_time() {
    local name="$1"
    local start end elapsed
    shift
    echo "--- [$name] Starting ---"
    start=$(date +%s)
    "$@"
    end=$(date +%s)
    elapsed=$((end - start))
    echo "--- [$name] Done in ${elapsed}s ---"
    echo "$name,$elapsed" >> "$OUTPUT_BASE/benchmark_times.csv"
}

echo "method,time_seconds" > "$OUTPUT_BASE/benchmark_times.csv"

run_and_time "3dgs" \
    docker compose run 3dgs train \
        -s "$SCENE_PATH" \
        -m "$OUTPUT_BASE/3dgs" \
        --iterations "$ITERATIONS" \
        --eval

run_and_time "mip-splatting" \
    docker compose run -e VARIANT=mip variants train \
        -s "$SCENE_PATH" \
        -m "$OUTPUT_BASE/mip" \
        --iterations "$ITERATIONS" \
        --eval

run_and_time "2dgs" \
    docker compose run -e VARIANT=2dgs variants train \
        -s "$SCENE_PATH" \
        -m "$OUTPUT_BASE/2dgs" \
        --iterations "$ITERATIONS" \
        --eval

run_and_time "nerfstudio-splatfacto" \
    docker compose run -e METHOD=splatfacto nerfstudio train \
        --data "$SCENE_PATH" \
        --output-dir "$OUTPUT_BASE/nerfstudio"

echo ""
echo "============================================"
echo " All training complete!"
echo " Timing summary: $OUTPUT_BASE/benchmark_times.csv"
echo "============================================"
