#!/bin/bash

echo "=== MegaDetector Comparison Setup ==="

# Check if python3 is available
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "Error: Python could not be found."
    exit 1
fi

echo "Using Python: $PYTHON_CMD"
echo "Installing required Python packages..."
$PYTHON_CMD -m pip install ultralytics matplotlib tqdm torch torchvision

# Check if MegaDetector model exists
MD_MODEL="md_v5a.0.0.pt"
if [ ! -f "$MD_MODEL" ]; then
    echo "Downloading MegaDetector v5a model..."
    if command -v wget &> /dev/null; then
        wget "https://github.com/microsoft/CameraTraps/releases/download/v5.0/md_v5a.0.0.pt" -O "$MD_MODEL"
    elif command -v curl &> /dev/null; then
        curl -L -o "$MD_MODEL" "https://github.com/microsoft/CameraTraps/releases/download/v5.0/md_v5a.0.0.pt"
    else
        echo "Error: Neither wget nor curl found. Please download $MD_MODEL manually from:"
        echo "https://github.com/microsoft/CameraTraps/releases/download/v5.0/md_v5a.0.0.pt"
        exit 1
    fi
else
    echo "MegaDetector model ($MD_MODEL) already exists."
fi

echo "Setup complete!"
echo "You can now run the comparison script:"
echo "python compare_models.py --conf 0.25 --output test_results"
