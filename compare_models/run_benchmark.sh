#!/bin/bash

# Default arguments
IMAGE_DIR="${1:-/home/satoko/project/hykecam_1010/ALL/night/}"
MD_MODEL="${2:-md_v5a.0.0.pt}"

# Check for MegaDetector model
if [ ! -f "$MD_MODEL" ]; then
    echo "MegaDetector model not found: $MD_MODEL"
    echo "Please download it or specify correct path."
    # Optional: logic to download if needed, similar to setup.sh
    exit 1
fi

echo "======================================================="
echo " Starting YOLO Benchmark"
echo " Images: $IMAGE_DIR"
echo " MD Model: $MD_MODEL"
echo "======================================================="

# Define YOLO models to test
# Valid models (if supported by ultralytics version):
# v8, v9, v10, v11 (latest)

# Note: The user requested "v26", but as of early 2025, Ultralytics supports up to YOLO11 (v11).
# We will benchmark v8, v9, v10, v11.
# Limited to models up to 'm' (medium) size.

MODELS=(
    # YOLOv8
    "yolov8n.pt" "yolov8s.pt" "yolov8m.pt"
    
    # YOLOv9 (t, s, m)
    # v9c/e are large, so we include t, s, m if available
    "yolov9t.pt" "yolov9s.pt" "yolov9m.pt"
    
    # YOLOv10 (n, s, m)
    "yolov10n.pt" "yolov10s.pt" "yolov10m.pt"
    
    # YOLO11 (n, s, m)
    "yolo11n.pt" "yolo11s.pt" "yolo11m.pt"
)

echo "Target Models: ${MODELS[*]}"
echo "Running benchmark..."

# Run Python script
python3 compare_models/benchmark_yolo.py \
    --images "$IMAGE_DIR" \
    --md "$MD_MODEL" \
    --yolo-models "${MODELS[@]}" \
    --confs 0.05 0.1 0.15 0.2 0.25 0.3 0.4 0.5 \
    --output "benchmark_results"

echo "======================================================="
echo " Benchmark Complete!"
echo " Results saved in: benchmark_results/"
echo "======================================================="
