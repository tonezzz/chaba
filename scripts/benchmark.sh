#!/bin/bash
# Compute PSNR/SSIM/LPIPS for all trained models and write to benchmark_results.csv
# Usage: ./scripts/benchmark.sh [/outputs]

set -e

OUTPUT_BASE="${1:-/outputs}"
RESULTS_FILE="$OUTPUT_BASE/benchmark_results.csv"

echo "method,psnr,ssim,lpips" > "$RESULTS_FILE"

extract_metrics() {
    local method="$1"
    local metrics_json="$2"

    if [[ ! -f "$metrics_json" ]]; then
        echo "$method,N/A,N/A,N/A" >> "$RESULTS_FILE"
        return
    fi

    psnr=$(python3 -c "import json; d=json.load(open('$metrics_json')); print(round(d.get('psnr',0),4))")
    ssim=$(python3 -c "import json; d=json.load(open('$metrics_json')); print(round(d.get('ssim',0),4))")
    lpips=$(python3 -c "import json; d=json.load(open('$metrics_json')); print(round(d.get('lpips',0),4))")

    echo "$method,$psnr,$ssim,$lpips" >> "$RESULTS_FILE"
}

echo "=== Computing metrics for all methods ==="

# 3DGS
docker compose run 3dgs metrics -m "$OUTPUT_BASE/3dgs" 2>/dev/null || true
extract_metrics "3dgs" "$OUTPUT_BASE/3dgs/results.json"

# Mip-Splatting
docker compose run -e VARIANT=mip variants metrics -m "$OUTPUT_BASE/mip" 2>/dev/null || true
extract_metrics "mip-splatting" "$OUTPUT_BASE/mip/results.json"

# 2DGS
docker compose run -e VARIANT=2dgs variants metrics -m "$OUTPUT_BASE/2dgs" 2>/dev/null || true
extract_metrics "2dgs" "$OUTPUT_BASE/2dgs/results.json"

echo ""
echo "=== Benchmark Results ==="
column -t -s',' "$RESULTS_FILE"
echo ""
echo "Saved to: $RESULTS_FILE"
