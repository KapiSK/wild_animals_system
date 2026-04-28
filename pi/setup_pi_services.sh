#!/bin/bash
set -e

# エッジサーバ(Pi)用: 本番/テスト サービス自動構築スクリプト
# sudo ./setup_pi_services.sh で実行してください。

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (use sudo)"
  exit
fi

if [ -n "$SUDO_USER" ]; then
    RUN_USER="$SUDO_USER"
else
    RUN_USER=$(whoami)
fi
USER_HOME=$(getent passwd "$RUN_USER" | cut -d: -f6)

echo "=== Setup Edge Pi Services (Main & Test) ==="

apt-get update
apt-get install -y python3-pip python3-venv python3-opencv python3-numpy libgl1 libglib2.0-0 git

setup_service() {
    ENV_NAME=$1
    SERVICE_NAME=$2
    UVICORN_PORT=$3
    
    BASE_DIR="$USER_HOME/$ENV_NAME/wild_animals_system/pi"
    VENV_DIR="$BASE_DIR/venv"
    SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME.service"

    echo "Configuring $SERVICE_NAME..."

    if [ ! -d "$BASE_DIR" ]; then
        echo "Warning: $BASE_DIR does not exist. Skipping $SERVICE_NAME."
        return
    fi

    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating venv for $ENV_NAME..."
        sudo -u "$RUN_USER" python3 -m venv --system-site-packages "$VENV_DIR"
    fi
    
    echo "Installing requirements for $ENV_NAME..."
    export TMPDIR="$BASE_DIR/pip_tmp"
    sudo -u "$RUN_USER" mkdir -p "$TMPDIR"
    sudo -u "$RUN_USER" "$VENV_DIR/bin/pip" install --no-cache-dir --upgrade pip
    sudo -u "$RUN_USER" "$VENV_DIR/bin/pip" install --no-cache-dir -r "$BASE_DIR/requirements.txt"
    sudo -u "$RUN_USER" rm -rf "$TMPDIR"

    # .envがなければ作成する（宛先URLを含む）
    if [ ! -f "$BASE_DIR/.env" ]; then
        echo "Creating isolated .env for $ENV_NAME"
        CLOUD_URL="https://YOUR_VPS_IP:443/upload"
        if [ "$ENV_NAME" == "ex_env" ]; then
            CLOUD_URL="http://YOUR_VPS_IP:8001/upload"
        fi
        
        cat <<EOF > "$BASE_DIR/.env"
CLOUD_SERVER_URL=$CLOUD_URL
# ESP32 がこのPiの推論結果等を受けとるポート
API_PORT=$UVICORN_PORT
# その他の設定
CAMERA_ID=CAM_PI_01
EOF
        chown "$RUN_USER":"$RUN_USER" "$BASE_DIR/.env"
    fi

    cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Wild Animal Edge ($ENV_NAME)
After=network.target

[Service]
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$BASE_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$VENV_DIR/bin/python -m uvicorn main:app --host 0.0.0.0 --port $UVICORN_PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    echo "Created: $SERVICE_PATH"
}

# 外部からアクセスする場合、本番は 8000番、テストは 8001番で動かす
setup_service "prod_env" "wild-animal-edge-main" 8000
setup_service "ex_env" "wild-animal-edge-test" 8001

echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling and Starting services..."
systemctl enable wild-animal-edge-main || true
systemctl start wild-animal-edge-main || true

systemctl enable wild-animal-edge-test || true
systemctl start wild-animal-edge-test || true

echo "=== Complete ==="
echo "Please edit the .env file in pi directory to set the correct CLOUD_SERVER_URL if needed."
