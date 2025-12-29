# オリジナルサーバー (外部サーバー) - MegaDetector版

このサーバーはエッジデバイスから画像を受信し、**MegaDetector v5a** を用いて動物を検出し、処理済みの画像を添付してメール通知を行います。

## 必要要件

- Python 3.8以上
- Linux (Ubuntu/Debian推奨)

## Linuxでの運用セットアップ

### 1. 環境構築

必要なパッケージとPythonライブラリをインストールします。

```bash
# システムの更新とvenvのインストール
sudo apt update && sudo apt upgrade -y
sudo apt install python3-venv git -y

# プロジェクトディレクトリの作成 (例: /opt/wild_animals)
sudo mkdir -p /opt/wild_animals
sudo chown $USER:$USER /opt/wild_animals
cd /opt/wild_animals

# (コードをここに配置します - git clone または scp等で)
# ここでは original_server ディレクトリ配下にコードがあると仮定します

cd original_server

# 仮想環境の作成と有効化
python3 -m venv venv
source venv/bin/activate

# 依存ライブラリのインストール
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. 環境設定

`.env` ファイルを作成して設定を行います。

```bash
nano .env
```

内容例:

```env
UPLOAD_DIR=received_images
PROCESSED_DIR=processed_images

# メール設定
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SENDER_EMAIL='slabwildanimals@gmail.com'
SENDER_PASSWORD='cxwi qepd joxx mpbi'
RECIPIENT_EMAIL='25w6039c@shinshu-u.ac.jp'
```

### 3. ファイアウォール設定 (UFW)

ポート8000を開放します。

```bash
sudo ufw allow 8000/tcp
sudo ufw reload
```

### 4. 自動起動の設定 (Systemd)

サーバーが常にバックグラウンドで起動し、再起動時にも自動的に立ち上がるようにします。

1. サービスファイルの作成

   ```bash
   sudo nano /etc/systemd/system/wild-server.service
   ```

2. 以下の内容を記述します (パスやユーザー名は環境に合わせて変更してください):

   ```ini
   [Unit]
   Description=Wild Animals Detection Server
   After=network.target

   [Service]
   User=ubuntu
   Group=ubuntu
   WorkingDirectory=/opt/wild_animals/original_server
   Environment="PATH=/opt/wild_animals/original_server/venv/bin"
   ExecStart=/opt/wild_animals/original_server/venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000
   Restart=always
   RestartSec=5s

   [Install]
   WantedBy=multi-user.target
   ```

   ※ `User` はあなたのLinuxユーザー名 (例: `ubuntu`, `pi`, `root` など) に変更してください。

3. サービスの有効化と起動

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable wild-server
   sudo systemctl start wild-server
   ```

4. ステータスの確認

   ```bash
   sudo systemctl status wild-server
   ```

### 5. ログの確認

サーバーの動作ログを確認するには以下のコマンドを使用します。

```bash
# リアルタイムでログを表示
journalctl -u wild-server -f
```

## エッジデバイスの設定

Raspberry Pi (エッジサーバー) 上で `.env` を更新し、このサーバーを指定してください：

```env
MAIN_SERVER_URL=http://<外部サーバーのIPアドレス>:8000/upload
```
