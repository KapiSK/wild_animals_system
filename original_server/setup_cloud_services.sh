#!/bin/bash
set -e

# クラウドサーバ用: 本番/テスト サービス自動構築スクリプト
# sudo ./setup_cloud_services.sh で実行してください。

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (use sudo)"
  exit
fi

# 実行ユーザーの取得
if [ -n "$SUDO_USER" ]; then
    RUN_USER="$SUDO_USER"
else
    RUN_USER=$(whoami)
fi
USER_HOME=$(getent passwd "$RUN_USER" | cut -d: -f6)

echo "=== Setup Cloud Services (Main & Test) ==="

setup_service() {
    ENV_NAME=$1
    SERVICE_NAME=$2
    PORT=$3
    
    BASE_DIR="$USER_HOME/$ENV_NAME/wild_animals_system/original_server"
    VENV_DIR="$BASE_DIR/venv"
    SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME.service"

    echo "Configuring $SERVICE_NAME..."

    # ディレクトリが存在しない場合はスキップ
    if [ ! -d "$BASE_DIR" ]; then
        echo "Warning: $BASE_DIR does not exist. Skipping $SERVICE_NAME."
        return
    fi

    # venvの確認と作成
    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating venv for $ENV_NAME..."
        sudo -u "$RUN_USER" python3 -m venv "$VENV_DIR"
    fi
    
    # 依存関係のインストール
    echo "Installing requirements for $ENV_NAME..."
    sudo -u "$RUN_USER" "$VENV_DIR/bin/pip" install --upgrade pip
    sudo -u "$RUN_USER" "$VENV_DIR/bin/pip" install -r "$BASE_DIR/requirements.txt"

    # .envがなければ作成
    if [ ! -f "$BASE_DIR/.env" ]; then
        echo "Creating isolated .env for $ENV_NAME (PORT=$PORT)"
        cat <<EOF > "$BASE_DIR/.env"
PORT=$PORT
API_TOKEN=change-me-$ENV_NAME
EOF
        chown "$RUN_USER":"$RUN_USER" "$BASE_DIR/.env"
    fi

    # サービスファイルの生成
    cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Wild Animal Server ($ENV_NAME)
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

    echo "Created: $SERVICE_PATH"
}

# 本番環境とテスト環境のサービスを作成
setup_service "prod_env" "wild-animal-server-main" 8000
setup_service "ex_env" "wild-animal-server-test" 8001

echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling and Starting services..."
systemctl enable wild-animal-server-main || true
systemctl start wild-animal-server-main || true

systemctl enable wild-animal-server-test || true
systemctl start wild-animal-server-test || true

echo "=== Complete ==="
echo "Status Check:"
echo "sudo systemctl status wild-animal-server-main"
echo "sudo systemctl status wild-animal-server-test"
