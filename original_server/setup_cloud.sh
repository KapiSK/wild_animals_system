#!/bin/bash
set -e

echo "================================================="
echo "☁️ Wild Animals Cloud Server Setup (Nginx + SSL)"
echo "================================================="

if [ "$EUID" -ne 0 ]; then
  echo "🚨 エラー: このスクリプトは root 権限 (sudo) で実行してください。"
  echo "実行例: sudo bash setup_cloud.sh"
  exit 1
fi

APP_DIR=$(pwd)
echo "📂 インストール先ディレクトリ: $APP_DIR"

echo "-------------------------------------------------"
echo "🔐 【IPアドレス制限の設定】"
echo "ダッシュボードやギャラリーを閲覧できるPCのグローバルIPアドレスを入力してください。"
echo "※空欄にしてEnterを押すと、一時的に「誰でもアクセス可能」になります（後から変更可能）。"
read -p "▶️ 管理用 IPアドレス (例: 133.1.x.x): " MGMT_IP

echo "-------------------------------------------------"
echo "📦 [1/5] 必要なパッケージのインストール..."
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx ufw openssl

echo "-------------------------------------------------"
echo "🐍 [2/5] Python仮想環境の構築と依存関係のインストール..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
if [ -f "requirements.txt" ]; then
    pip install setuptools wheel
    # クラウドサーバー用にopencvはGUI不要のheadless版を使うことを推奨
    # 前回の実行で -headless-headless になってしまった場合の自己修復
    sed -i 's/opencv-python-headless-headless/opencv-python-headless/g' requirements.txt || true
    # 厳密な正規表現で先頭の opencv-python のみを置換
    sed -i -E 's/^opencv-python(==.*)?$/opencv-python-headless\1/g' requirements.txt || true
    pip install -r requirements.txt
else
    echo "⚠️ requirements.txt が見つかりません。ライブラリのインストールをスキップします。"
fi

echo "-------------------------------------------------"
echo "🔑 [3/5] SSL「オレオレ証明書」の生成..."
mkdir -p /etc/nginx/ssl
if [ ! -f "/etc/nginx/ssl/wildanimals.crt" ]; then
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/wildanimals.key \
        -out /etc/nginx/ssl/wildanimals.crt \
        -subj "/C=JP/ST=Tokyo/L=Tokyo/O=WildAnimals/OU=IT/CN=wild-animals-server"
    echo "✅ SSL証明書を生成しました。"
fi

echo "-------------------------------------------------"
echo "🕸️ [4/5] Nginx（リバースプロキシ）の設定..."
NGINX_CONF="/etc/nginx/sites-available/wild_animals_cloud"

if [ -n "$MGMT_IP" ]; then
    ALLOW_RULE="allow $MGMT_IP;
        deny all;"
    echo "🔒 管理画面は $MGMT_IP からのアクセスのみ許可します。"
else
    ALLOW_RULE="allow all;"
    echo "🔓 IP制限は無効化されています。後でNginxの設定を変更してください。"
fi

cat > $NGINX_CONF <<EOF
server {
    listen 80;
    server_name _;
    # HTTPでアクセスされたらHTTPSに強制リダイレクト
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate /etc/nginx/ssl/wildanimals.crt;
    ssl_certificate_key /etc/nginx/ssl/wildanimals.key;
    client_max_body_size 50M;

    # 1. 画像アップロード用APIは世界中へ開放（APIトークンで保護済）
    location /upload {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # 2. その他の管理機能（/admin, /gallery, /api など）にはIP制限を適用
    location / {
        $ALLOW_RULE
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sf $NGINX_CONF /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
systemctl restart nginx

echo "-------------------------------------------------"
echo "🛡️ [5/5] ファイアウォール (UFW) と Systemd の有効化..."
# ファイアウォールの設定（SSH, HTTP, HTTPSを開放。FastAPIの8000は直接通さない）
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow http
ufw allow https
ufw --force enable

# Systemd サービス化（FastAPIの自動バックグラウンド起動）
SERVICE_FILE="/etc/systemd/system/wild-animals-cloud.service"
USER_NAME=\$(logname || echo \$USER)

cat > \$SERVICE_FILE <<EOF
[Unit]
Description=Wild Animals Cloud Server (FastAPI)
After=network.target

[Service]
User=\$USER_NAME
WorkingDirectory=\$APP_DIR
ExecStart=\$APP_DIR/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable wild-animals-cloud.service
systemctl restart wild-animals-cloud.service

echo "================================================="
echo "🎉 構築がすべて完了しました！"
echo "👉 ブラウザでサーバーのIPアドレス（ https://[クラウドのIPアドレス] ）にアクセスしてください！"
echo "※ オレオレ証明書の「警告画面」が出ますが、詳細設定からサイトへ進んでください。"
echo "================================================="
