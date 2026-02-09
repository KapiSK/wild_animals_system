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
# You can add 'yolov8m.pt' 'yolov8l.pt' etc. if you have resources
MODELS=("yolov8n.pt" "yolov8s.pt")

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
