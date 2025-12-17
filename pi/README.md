# Edge Server for Wild Animal Monitoring

Raspberry Pi上で動作するエッジサーバーのドキュメントです。
このサーバーは、カメラ（ESP32など）から送信された画像を受け取り、YOLOv8を用いて動物の検出を行い、その結果をメインサーバーへ転送する役割を持ちます。

## 目次

1. [機能概要](#1-機能概要)
2. [動作環境・前提条件](#2-動作環境・前提条件)
3. [セットアップ手順](#3-セットアップ手順)
4. [サーバーの起動](#4-サーバーの起動)
5. [動作テスト](#5-動作テスト)
6. [開発ワークフロー (Windows ⇔ Pi)](#6-開発ワークフロー-windows--pi)
7. [チュートリアル: ゼロから環境構築まで](#7-チュートリアル-ゼロから環境構築まで)
8. [自動起動の設定 (Service化)](#8-自動起動の設定-service化)

---

## 1. 機能概要

- **画像受信**: `/upload` エンドポイントで画像データを受信。
- **物体検出**: 受信した画像に対してYOLOv8を実行し、動物（Cow, Sheep, Bear, etc.）が含まれているか判定。
- **データ転送**: 動物が検出された場合のみ、指定されたメインサーバーへ画像を転送。
- **非同期処理**: 受信と推論処理を分離し、スムーズな応答を実現。

## 2. 動作環境・前提条件

- **OS**: Raspberry Pi OS (64-bit 推奨) または Linux/Windows/Mac
- **Python**: 3.8 以上
- **Network**: カメラデバイスおよびメインサーバーと通信可能な状態であること

## 3. セットアップ手順

プロジェクトディレクトリ (`pi`) に移動し、必要なライブラリをインストールします。

```bash
cd pi
pip install -r requirements.txt
```

※ 初回実行時にYOLOのモデルファイル (`yolov8n.pt`) が自動的にダウンロードされます。

## 4. サーバーの起動

以下のコマンドでサーバーを起動します。

### 開発モード (自動リロードあり)

コードを変更すると自動的に再起動します。デバッグ時に便利です。

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 本番モード

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0`: 外部からのアクセスを許可します。
- `--port 8000`: ポート番号を指定します。

> **Uvicornとは?**
> Uvicornは、Pythonのための高速なASGI (Asynchronous Server Gateway Interface) サーバーです。
> FastAPIで作成されたWebアプリケーションを実行するために必要となります。
> 非同期処理に優れており、Raspberry Piのようなリソースが限られた環境でも効率的に動作します。

## 5. 動作テスト

サーバーが起動している状態で、動作確認を行います。

### テストスクリプトを使用する

`test_server.py` を実行すると、ダミー画像を生成して並列送信テストを行います。

```bash
# ローカルでテストする場合
python test_server.py
```

※ 別の端末からテストする場合は、スクリプト内の `SERVER_URL` を編集してください。

### 手動テスト (curlコマンド)

```bash
curl -X POST -F "file=@test_image.jpg" http://localhost:8000/upload
```

## 6. 開発ワークフロー (Windows ⇔ Pi)

Windowsでコーディングを行い、Raspberry Piへ反映させる手順です。

### Gitを使用する方法 (推奨)

GitHubなどのリモートリポジトリを経由して同期します。

1. **[Windows]** 変更を開発し、コミット＆プッシュ。

   ```bash
   git add .
   git commit -m "Add new feature"
   git push origin main
   ```

2. **[Raspberry Pi]** 変更を取り込む。

   ```bash
   git pull origin main
   ```

   ※ `.gitignore` により、画像データやログ、環境変数は同期から除外されます。

### SCPで直接転送する方法

Gitを使わず、ファイルを直接コピーします。(PowerShell等で実行)

```bash
# ファイル単体
scp .\main.py pi@<Pi_IP_Address>:/path/to/project/pi/

# ディレクトリ全体 (注意: 上書きされます)
scp -r .\pi pi@<Pi_IP_Address>:/path/to/project/
```

## 7. チュートリアル: ゼロから環境構築まで

Raspberry Pi上のディレクトリ `/home/slab/wild-animals` にリポジトリがある想定での完全な手順です。

### Step 1: ディレクトリへ移動

```bash
cd /home/slab/wild-animals/pi
```

### Step 2: 仮想環境の作成 (推奨)

システム環境を汚さないために仮想環境 (`venv`) を使用します。

```bash
python3 -m venv venv
```

### Step 3: 仮想環境の有効化

```bash
source venv/bin/activate
```

※ プロンプトに `(venv)` と表示されたら成功です。以降の作業はこの状態で行います。

### Step 4: 依存関係のインストール

```bash
pip install -r requirements.txt
```

### Step 5: サーバー起動

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

成功すると `INFO: Uvicorn running on http://0.0.0.0:8000` と表示されます。

### Step 6: 動作確認

別のターミナルを開き、テストを実行します。

```bash
cd /home/slab/wild-animals/pi
source venv/bin/activate
python test_server.py
```

---
**設定ファイルについて**:
設定は `.env` ファイルで行います。必要に応じて作成してください。

- `UPLOAD_DIR`: 画像保存先ディレクトリ
- `MAIN_SERVER_URL`: 転送先サーバーURL (未設定なら転送なし)

## 8. 自動起動の設定 (Service化)

Raspberry Piの起動時に自動的にサーバーが立ち上がるように、Systemdのサービスとして登録します。

### Step 1: サービスファイルの編集

リポジトリに含まれている `wild-animals.service` を確認し、必要に応じてユーザー名やパスを修正してください。
(デフォルトでは `/home/slab/wild-animals/pi` ディレクトリ、`slab` ユーザーを想定しています)

### Step 2: シンボリックリンクの作成

サービスファイルを `/etc/systemd/system/` にリンクします。

```bash
sudo ln -s /home/slab/wild-animals/pi/wild-animals.service /etc/systemd/system/wild-animals.service
```

### Step 3: サービスの有効化と起動

```bash
# 設定の読み込み
sudo systemctl daemon-reload

# 自動起動の有効化
sudo systemctl enable wild-animals.service

# サービスの起動
sudo systemctl start wild-animals.service
```

### Step 4: ステータス確認

```bash
sudo systemctl status wild-animals.service
```

`Active: active (running)` と表示されていれば正常に動作しています。

### ログの確認

サービスとして動作している場合のログは、`journalctl` コマンドで確認できます。

```bash
# リアルタイムでログを表示
journalctl -u wild-animals.service -f
```
