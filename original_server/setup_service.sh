#!/bin/bash

# External Server Service Setup Script
# Works on Debian/Ubuntu based systems

# 1. 変数の設定
# サービス名、実行ユーザー、作業ディレクトリなどを定義します
SERVICE_NAME="wild-animal-server"
USER_NAME=$USER
WORKING_DIR=$(pwd)
# スクリプト自身のディレクトリを取得 (venvの位置特定に使用)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
VENV_DIR="$SCRIPT_DIR/venv"
PYTHON_EXEC="$VENV_DIR/bin/python"

echo "=== Wild Animal Server Service Setup ==="
echo "Service Name: $SERVICE_NAME"
echo "User: $USER_NAME"
echo "Working Directory: $WORKING_DIR"
echo "Python Executable: $PYTHON_EXEC"

# Check if venv exists
# 2. 仮想環境の確認
# Python仮想環境が存在しない場合はエラー終了します
if [ ! -d "$VENV_DIR" ]; then
    echo "Error: Virtual environment not found at $VENV_DIR"
    echo "Please create a virtual environment first: python3 -m venv venv"
    exit 1
fi

# Create systemd service file
# We will create it in the script's directory and verify the path.
# 3. サービス定義ファイルのパス設定
# ローカル(スクリプトと同じ場所)に作成し、/etc/systemd/system へリンクします
LOCAL_SERVICE_FILE="$SCRIPT_DIR/$SERVICE_NAME.service"
SYSTEM_SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME.service"

echo "Creating local service file at $LOCAL_SERVICE_FILE..."

# Note: We use the absolute path for WorkingDirectory based on where the script is run (project root)
# Ensure we are linking to the file with absolute path
# 4. サービスファイルの作成
# systemdが読み込む設定ファイルの中身を書き込みます
cat > "$LOCAL_SERVICE_FILE" <<EOF
[Unit]
Description=Wild Animal Monitoring External Server
After=network.target

[Service]
User=$USER_NAME
Group=$USER_NAME
WorkingDirectory=$WORKING_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$PYTHON_EXEC original_server/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Local service file created."

# Create symlink
# 5. シンボリックリンクの作成
# /etc/systemd/system/ にリンクを貼り、systemdに認識させます
echo "Linking service file to $SYSTEM_SERVICE_PATH..."
if [ -f "$SYSTEM_SERVICE_PATH" ] || [ -L "$SYSTEM_SERVICE_PATH" ]; then
    echo "Removing existing service file/link..."
    sudo rm -f "$SYSTEM_SERVICE_PATH"
fi

sudo ln -s "$LOCAL_SERVICE_FILE" "$SYSTEM_SERVICE_PATH"

# Reload systemd
# 6. 設定の反映と起動
# デーモンのリロード (ファイルの変更を認識)
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable service
# 自動起動の有効化
echo "Enabling $SERVICE_NAME..."
sudo systemctl enable $SERVICE_NAME

# Start service
# サービスの即時開始
echo "Starting $SERVICE_NAME..."
sudo systemctl start $SERVICE_NAME

# Check status
# 7. 状態確認
# 起動ステータスを表示します
echo "Checking service status..."
sudo systemctl status $SERVICE_NAME --no-pager

echo "=== Setup Complete ==="
echo "To check logs: sudo journalctl -u $SERVICE_NAME -f"
