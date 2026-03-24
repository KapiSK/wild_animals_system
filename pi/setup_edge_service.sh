#!/bin/bash

# Edge Server (Pi) Service Setup Script
# Works on Raspberry Pi OS / Debian / Ubuntu

# --- 設定変数 ---
SERVICE_NAME="wild-animal-edge"
USER_NAME=$USER
# スクリプトがあるディレクトリを起点にする
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
VENV_DIR="$SCRIPT_DIR/venv"
# Pythonのパス (venv内)
PYTHON_EXEC="$VENV_DIR/bin/python"

echo "=== Wild Animal Edge Server Setup ==="
echo "Service Name: $SERVICE_NAME"
echo "User: $USER_NAME"
echo "Base Directory: $SCRIPT_DIR"

# 1. システムパッケージの更新とインストール
# OpenCVなどに必要なライブラリを含める
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv libgl1-mesa-glx libglib2.0-0 git

# 2. 仮想環境の作成
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists."
fi

# 3. 依存ライブラリのインストール
echo "Installing Python requirements..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

# 4. サービス定義ファイルの作成
LOCAL_SERVICE_FILE="$SCRIPT_DIR/$SERVICE_NAME.service"
SYSTEM_SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME.service"

echo "Creating local service file at $LOCAL_SERVICE_FILE..."

# pi/main.py は "uvicorn main:app" で起動する設計
cat > "$LOCAL_SERVICE_FILE" <<EOF
[Unit]
Description=Wild Animal Monitoring Edge Server (Pi)
After=network.target

[Service]
User=$USER_NAME
Group=$USER_NAME
WorkingDirectory=$SCRIPT_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin"
# ポート8000で起動 (外部サーバーとポートが被る場合は注意が必要だがPi単体動作ならOK)
# 外部公開用に --host 0.0.0.0 を指定
ExecStart=$PYTHON_EXEC -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Local service file created."

# 5. シンボリックリンクの作成
echo "Linking service file to $SYSTEM_SERVICE_PATH..."
if [ -f "$SYSTEM_SERVICE_PATH" ] || [ -L "$SYSTEM_SERVICE_PATH" ]; then
    echo "Removing existing service file/link..."
    sudo rm -f "$SYSTEM_SERVICE_PATH"
fi
sudo ln -s "$LOCAL_SERVICE_FILE" "$SYSTEM_SERVICE_PATH"

# 6. サービスの有効化と起動
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "Enabling $SERVICE_NAME..."
sudo systemctl enable $SERVICE_NAME

echo "Starting $SERVICE_NAME..."
sudo systemctl start $SERVICE_NAME

# 7. 状態確認
echo "Checking service status..."
sudo systemctl status $SERVICE_NAME --no-pager

echo "=== Setup Complete ==="
echo "You can check logs with: sudo journalctl -u $SERVICE_NAME -f"
