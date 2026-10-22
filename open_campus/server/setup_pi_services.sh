#!/bin/bash
set -euo pipefail
if [ "$EUID" -ne 0 ] || [ -z "${SUDO_USER:-}" ]; then
    echo "Run as your normal user with: sudo bash setup_pi_services.sh"
    exit 1
fi
BASE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="$SUDO_USER"
RUN_GROUP="$(id -gn "$RUN_USER")"
VENV_DIR="$BASE_DIR/venv"
if [ ! -f "$BASE_DIR/.env" ]; then
    echo "Create $BASE_DIR/.env using .env.example and set FTP_PASSWORD first."
    exit 1
fi
apt-get update
apt-get install -y python3-pip python3-venv libgl1 libglib2.0-0
if [ ! -x "$VENV_DIR/bin/python" ]; then
    sudo -u "$RUN_USER" python3 -m venv "$VENV_DIR"
fi
# Pi uses CPU inference. Avoid PyPI's ARM CUDA dependencies and /tmp tmpfs.
sudo -u "$RUN_USER" mkdir -p "$BASE_DIR/pip_tmp"
sudo -u "$RUN_USER" env TMPDIR="$BASE_DIR/pip_tmp" "$VENV_DIR/bin/python" -m pip install --no-cache-dir --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cpu
# Keep the selected CPU builds when resolving the application's dependencies.
sudo -u "$RUN_USER" "$VENV_DIR/bin/python" -c 'import sys; from pathlib import Path; from importlib.metadata import version; Path(sys.argv[1]).write_text("".join(f"{name}=={version(name)}\n" for name in ("torch", "torchvision")))' "$VENV_DIR/cpu-constraints.txt"
sudo -u "$RUN_USER" env TMPDIR="$BASE_DIR/pip_tmp" "$VENV_DIR/bin/python" -m pip install --no-cache-dir -c "$VENV_DIR/cpu-constraints.txt" -r "$BASE_DIR/requirements.txt"
cat > /etc/systemd/system/open-campus-camera.service <<EOF
[Unit]
Description=Open Campus FTP Camera Demo
After=network.target

[Service]
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$BASE_DIR
ExecStart="$VENV_DIR/bin/python" -m uvicorn main:app --host 0.0.0.0 --port 8000
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
Restart=on-failure
RestartSec=5
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable open-campus-camera
systemctl restart open-campus-camera
echo "Use journalctl -u open-campus-camera -f to check startup and FTP reception."
