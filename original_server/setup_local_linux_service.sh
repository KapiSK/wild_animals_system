#!/bin/bash
set -e

# クラウドサーバ用: Linuxローカルサーバテスト用 サービス自動構築スクリプト
# 現在のディレクトリを対象としてサービスを構築します。
# 必ず original_server ディレクトリ内で、sudo を付けて実行してください。
# 例: sudo ./setup_local_linux_service.sh

if [ "$EUID" -ne 0 ]; then
  echo "root権限で実行してください (例: sudo ./setup_local_linux_service.sh)"
  exit 1
fi

# 実行ユーザーの取得
if [ -n "$SUDO_USER" ]; then
    RUN_USER="$SUDO_USER"
else
    RUN_USER=$(whoami)
fi

BASE_DIR=$(pwd)
VENV_DIR="$BASE_DIR/venv"
SERVICE_NAME="wild-animal-server-local"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME.service"

echo "=== Setup Local Linux Service ==="
echo "Target directory: $BASE_DIR"
echo "Run user: $RUN_USER"

# venvの確認と作成
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating venv in $VENV_DIR..."
    sudo -u "$RUN_USER" python3 -m venv "$VENV_DIR"
fi

# pip のアップデート
echo "Upgrading pip..."
sudo -u "$RUN_USER" "$VENV_DIR/bin/pip" install --upgrade pip

# テスト環境の初期設定 (setup_local_test.py を利用)
# setup_local_test.py の中で pip install -r requirements.txt も実行されます
echo "Running setup_local_test.py to initialize test environment..."
sudo -u "$RUN_USER" "$VENV_DIR/bin/python" setup_local_test.py

# サービスファイルの生成
echo "Creating systemd service: $SERVICE_NAME..."
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Wild Animal Server (Local Test)
After=network.target

[Service]
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$BASE_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$VENV_DIR/bin/python server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling and Starting service..."
systemctl enable $SERVICE_NAME || true
systemctl restart $SERVICE_NAME || true

echo "=== Complete ==="
echo "Status Check:"
echo "sudo systemctl status $SERVICE_NAME"
echo "Logs:"
echo "sudo journalctl -u $SERVICE_NAME -f"
