# Edge Server

Raspberry Pi向けエッジサーバーのsetup/実行ガイドです。
動物検出機能と画像転送機能を提供します。

## 1. 環境構築

### 必須要件

- Python 3.8+
- Raspberry Pi (または Linux/Windows/Mac 環境)

### セットアップ手順

プロジェクトディレクトリ (`pi`) に移動し、仮想環境を作成して依存パッケージをインストールします。

```bash
cd pi

# 仮想環境の作成と有効化 (推奨)
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 依存ライブラリのインストール
pip install -r requirements.txt
```

初回実行時に、物体検出モデル (`yolov8n.pt`) が自動的にダウンロードされます。

## 2. 実行 (デバッグ) 方法

### サーバーの手動起動

開発やデバッグの際は、以下のコマンドでサーバーを起動します。

```bash
# --reload: コード変更を検知して自動で再起動します
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

> **Uvicornについて**:
> 高速なASGIサーバーです。本番環境でもこれを使用します。

### 動作確認 (テスト)

サーバーが起動している状態で、テストスクリプトを実行して動作を確認します。

```bash
# 別のターミナルで実行
python test_server.py
```

10件のリクエストが送信され、ログに検出結果が表示されれば正常です。

## 3. サービス化

Raspberry Pi起動時に自動的にサーバーが立ち上がるように設定します。

### 設定手順

1. **サービスファイルの配置**
   `wild-animals.service` を `/etc/systemd/system/` へリンクします。
   ※ ファイル内のパス (`/home/slab/wild-animals/...`) が実際の環境と合っているか確認してください。

   ```bash
   sudo ln -s $(pwd)/wild-animals.service /etc/systemd/system/wild-animals.service
   ```

2. **有効化と起動**

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable wild-animals.service
   sudo systemctl start wild-animals.service
   ```

3. **ステータス・ログ確認**

   ```bash
   # ステータス確認
   sudo systemctl status wild-animals.service

   # ログ確認 (リアルタイム)
   journalctl -u wild-animals.service -f
   ```

## 4. トラブルシューティング

### Q. `PermissionError: [Errno 13] Permission denied: .../server.log` が出る

**原因**: ログファイルの所有権が `root` など、現在のユーザーと異なる場合に発生します（手動で `sudo` を付けて実行した場合など）。

**対策**: 以下のコマンドで、ディレクトリの所有権を現在のユーザーに戻してください。

```bash
# ユーザー名が slab の場合
sudo chown -R slab:slab /home/slab/wild-animals/pi
```

### Q. サーバー等のプロセスが残っていて起動できない

ポート 8000 が既に使用されている場合 (`Address already in use`)、以下のコマンドでプロセスを確認し、停止させてください。

```bash
# ポート8000を使用しているプロセスを確認
sudo lsof -i :8000

# プロセスをkill (PIDを指定)
sudo kill -9 <PID>
```
