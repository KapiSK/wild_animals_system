#!/bin/bash
cd "$(dirname "$0")"

echo "Setting up Python environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

echo "Installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt

echo "Starting Server..."
echo "Access at http://<PI_IP_ADDRESS>:8000/upload"
echo "Press Ctrl+C to stop."
python3 main.py
