#!/bin/bash

# Update system packages
echo "Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y python3-pip python3-venv libgl1-mesa-glx libglib2.0-0 git

# Create Python virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "Setup complete!"
echo "To start the server, run:"
echo "  source venv/bin/activate"
echo "  uvicorn main:app --host 0.0.0.0 --port 8000"
