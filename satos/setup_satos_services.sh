#!/bin/bash
set -e

# 統合サーバ(Satos)用: 本番/テスト サービス自動構築スクリプト
# sudo ./setup_satos_services.sh で実行してください。

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

echo "=== Setup Satos Integration Services (Main & Test) ==="

# 共通パッケージのインストール
apt-get update
apt-get install -y python3-venv python3-pip libgl1-mesa-glx ffmpeg

setup_service() {
    ENV_NAME=$1
    SERVICE_NAME=$2
    CLOUD_URL=$3
    
    BASE_DIR="$USER_HOME/$ENV_NAME/wild_animals_system/satos"
    VENV_DIR="$BASE_DIR/venv"
    SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME.service"

    echo "Configuring $SERVICE_NAME..."

    if [ ! -d "$BASE_DIR" ]; then
        echo "Warning: $BASE_DIR does not exist. Skipping $SERVICE_NAME."
        return
    fi

    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating venv for $ENV_NAME..."
        sudo -u "$RUN_USER" python3 -m venv "$VENV_DIR"
    fi
    
    echo "Installing requirements for $ENV_NAME..."
    sudo -u "$RUN_USER" "$VENV_DIR/bin/pip" install --upgrade pip
    sudo -u "$RUN_USER" "$VENV_DIR/bin/pip" install -r "$BASE_DIR/requirements.txt"

    if [ ! -f "$BASE_DIR/.env" ]; then
        echo "Creating isolated .env for $ENV_NAME"
        cat <<EOF > "$BASE_DIR/.env"
GMAIL_ADDRESS=
GMAIL_APP_PASSWORD=
CLOUD_SERVER_URL=$CLOUD_URL
CLOUD_SERVER_API_KEY=wild-animals-token-2026
ENABLE_LOCAL_YOLO=true
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_FOLDER=INBOX
IMAP_READONLY=false
MARK_AS_SEEN_ON_SAVE=true
POLL_INTERVAL_SECONDS=15
SEARCH_CRITERIA=UNSEEN
SAVE_DIR=./saved_videos
FRAME_SAVE_DIR=./saved_frames
STATE_FILE=./state.json
EOF
        chown "$RUN_USER":"$RUN_USER" "$BASE_DIR/.env"
    fi

    cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Satos Integration Server ($ENV_NAME)
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$BASE_DIR
ExecStart=$VENV_DIR/bin/python $BASE_DIR/gmail_image_saver.py
Restart=always
RestartSec=10
EnvironmentFile=$BASE_DIR/.env
Environment=HOME=$USER_HOME

[Install]
WantedBy=multi-user.target
EOF

    echo "Created: $SERVICE_PATH"
}

setup_service "prod_env" "satos-integration-main" "https://YOUR_VPS_IP:443/upload"
setup_service "ex_env" "satos-integration-test" "http://YOUR_VPS_IP:8001/upload"

echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling and Starting services..."
systemctl enable satos-integration-main || true
systemctl start satos-integration-main || true

systemctl enable satos-integration-test || true
systemctl start satos-integration-test || true

echo "=== Complete ==="
echo "Please edit the .env files in ~/prod_env/../satos and ~/ex_env/../satos to put real passwords and IP config!"
