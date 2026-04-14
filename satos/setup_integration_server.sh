#!/bin/bash
set -e

# ルート権限チェック
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (use sudo)"
  exit
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/venv"
SERVICE_NAME="satos-integration.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
ENV_FILE="$APP_DIR/.env"

# 実効ユーザー (sudo前のユーザー名) の取得
if [ -n "$SUDO_USER" ]; then
    RUN_USER="$SUDO_USER"
else
    RUN_USER=$(whoami)
fi

echo "Installing system dependencies..."
apt-get update
# OpenCV用およびffmpeg関連ライブラリのインストール
apt-get install -y python3-venv python3-pip libgl1-mesa-glx ffmpeg

echo "Creating Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    chown -R "$RUN_USER":"$RUN_USER" "$VENV_DIR"
fi

echo "Installing Python dependencies..."
# 権限問題を避けるため実行ユーザーとしてpip installを実行
sudo -u "$RUN_USER" "$VENV_DIR/bin/pip" install --upgrade pip
sudo -u "$RUN_USER" "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

# .envが存在しない場合は雛形を作成
if [ ! -f "$ENV_FILE" ]; then
    echo "Creating empty .env file..."
    cat <<EOF > "$ENV_FILE"
GMAIL_ADDRESS=
GMAIL_APP_PASSWORD=

CLOUD_SERVER_URL=
CLOUD_SERVER_API_KEY=wild-animals-token-2026

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
FILE_NAME_TEMPLATE={filename}
CREATE_SENDER_SUBDIR=false
LOG_LEVEL=INFO
FFMPEG_PATH=ffmpeg
FRAME_CAPTURE_OFFSETS_SECONDS=0,1,2
FRAME_IMAGE_FORMAT=jpg
EOF
    chown "$RUN_USER":"$RUN_USER" "$ENV_FILE"
    echo "PLEASE EDIT $ENV_FILE before starting the service!"
fi

echo "Creating systemd service..."

cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Satos Integration Server (Trail Camera to Cloud Filter)
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=$VENV_DIR/bin/python $APP_DIR/gmail_image_saver.py
Restart=always
RestartSec=10
EnvironmentFile=$ENV_FILE
# yolov8 の自動ダウンロード等の一時ファイル用への対処
Environment=HOME=/home/$RUN_USER

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd and enabling service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo "================================================="
echo "Setup is complete!"
echo "Configuration step:"
echo " 1. Edit the .env file:  nano $ENV_FILE"
echo " 2. Start the service:   sudo systemctl start $SERVICE_NAME"
echo " 3. Check logs:          journalctl -u $SERVICE_NAME -f"
echo "================================================="
