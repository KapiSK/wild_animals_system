# カメラ統合サーバー推論対応およびクラウドサーバー連携 実装完了の解説

カメラ統合サーバー（`satos`側の別サーバー）において、エッジサーバーと同様に自身で YOLOv8n 推論を行い、動物・人が検知された場合のみクラウドサーバー（Main Server）へ直接アップロードするよう実装を更新しました。

## 実装内容まとめ

1. **`gmail_image_saver.py` の推論＆転送ロジック改修**
   - ファイルの先頭で `requests` （転送用）と `ultralytics` （YOLO推論用）を利用するよう改修しました。
   - 初期化時に `yolov8n.pt` モデルをロードします。
   - 抽出した3枚のフレームを順番にモデルに入力し、1枚でも対象物（COCOでの「人」および「各種動物」）を検知すると、直ちに３枚一式をクラウドへ転送します。
   - アップロード処理には `requests.post` を用い、`multipart/form-data` にて `original_server` が待ち受けているエンドポイントへファイルを送信します。

2. **設定ファイル `.env` の更新**
   - 転送先の設定変数を `CLOUD_SERVER_URL` と `CLOUD_SERVER_API_KEY` （デフォルト: `wild-animals-token-2026`）へ変更しました。

3. **Linux 統合サーバー用セットアップスクリプトの新設**
   - Python仮想環境（venv）の構築、systemdサービス化などを一括で行う専用シェルスクリプト `setup_integration_server.sh` を作成しました。

---

## 統合サーバーへのデプロイ（セットアップ手順）

別のLinuxサーバーで稼働させるための完全な手順です。
あらかじめサーバー上に `wild_animals` プロジェクトを `git clone` 等で配置しておいてください。

### 1. セットアップスクリプトの実行

対象サーバーのターミナルにログインし、satosディレクトリーへ移動してセットアップスクリプトをroot（sudo）権限で実行します。

```bash
cd wild_animals/test2/satos
sudo chmod +x setup_integration_server.sh
sudo ./setup_integration_server.sh
```

このスクリプトは以下の処理を自動で行います：
- システムパッケージ（`ffmpeg`, `python3-venv`, `libgl1-mesa-glx` 等）のインストール。
- ローカル Python 仮想環境（`venv/`）の作成。
- `requirements.txt` からのライブラリ（`ultralytics`, `requests` 等）の依存関係インストール。
- `.env` が未存在の場合は雛形設定ファイルの自動生成。
- systemd サービス (`satos-integration.service`) の作成。

### 2. 環境変数（`.env`）の設定

スクリプトが完了したら、生成された `.env` ファイルを編集し、以下の環境情報を設定します。

```bash
nano .env
```
編集項目（例）：
- `GMAIL_ADDRESS=` （トレイルカメラから受信するGmailアドレス）
- `GMAIL_APP_PASSWORD=` （Gmailのアプリパスワード）
- `CLOUD_SERVER_URL=https://<クラウドサーバーのIP>:8000/upload`

### 3. サービスの起動と確認

設定完了後、サービスを起動します。

```bash
sudo systemctl start satos-integration.service
```

正常に常駐しているか、エラーがないか（特にYOLOモデルの初期ダウンロードなど）をログで確認します。
```bash
journalctl -u satos-integration.service -f
```

---

## 運用上の留意点

> [!WARNING]
> 一時的なメモリ超過とロード時間について
> - 初回起動時には `yolov8n.pt` モデル本体がインターネットから自動的にダウンロードされるため、ログ出力（`Model loaded successfully.`）まで数秒〜数十秒のタイムラグがあります。
> - 統合サーバーにも小～中規模のRAMリソース（最低でも1GB〜2GB程度の空きメモリ）が要件となります。もし推論時にプロセスがハングする場合（OOM killer起動など）はスワップ（Swap）設定での調整を行ってください。
