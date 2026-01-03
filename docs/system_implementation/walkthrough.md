# システム実装ウォークスルー

## 変更内容の概要

外部サーバー、エッジサーバー (Raspberry Pi)、エッジデバイス (ESP32) に対する変更を行い、システム全体の要件を実装しました。

### 1. 外部サーバー (解析・通知)

- **ファイル**: `original_server/server.py`
- **変更点**:
  - **モデル**: MegaDetector v5a (`md_v5a.0.0.pt`) の使用を確定。モデルのロードとクラス名のログ出力を強化しました。
  - **推論**: 検出の安定性を確保するため、信頼度しきい値 (`conf=0.25`) を追加しました。
  - **通知**: メール通知に、検出された動物の具体的な数と、バウンディングボックスが描画された処理済み画像を添付するようにしました。

### 2. エッジサーバー (Raspberry Pi)

- **ファイル**: `pi/main.py`, `pi/detector.py`
- **変更点**:
  - **推論**: `ultralytics` YOLOv8n を統合し、デバイス上で高速な推論を行えるようにしました。
  - **フィルタリングロジック**: 「**3枚中2枚**」ルールを実装しました。画像はサイクルが完了する（3枚揃う）まで `CycleManager` でバッファリングされます。2枚以上の画像で動物が検出された場合のみ、3枚すべての画像が外部サーバーへ転送されます。
  - **保存**: 画像は設定された `UPLOAD_DIR` に保存されます。

### 3. エッジデバイス (ESP32)

- **ファイル**: `esp/camera/camera.ino`
- **変更点**:
  - **命名規則**: ファイル名を `{CycleID}-{Index}{n/d}.jpg` (例: `AABBCC-01-1n.jpg`) に変更しました。ここで `n` は夜、`d` は昼を表します。
  - **アップロードロジック**: 新しい命名規則のファイルを検出・アップロードできるようにスキャンロジックを更新しました。また、サーバー側で元のファイル名を追跡しやすくするため、アップロード時に `X-File-Name` ヘッダーを追加しました。

## 検証ガイド

### 1. 外部サーバーのテスト

1. **依存関係の確認**: `requirements.txt` がインストールされていることを確認します (`pip install -r requirements.txt`)。
2. **サーバー起動**: `python original_server/server.py`
3. **アップロードテスト**: `curl` または Postman を使用して画像を `http://localhost:8000/upload` にアップロードします。

    ```bash
    curl -X POST -F "file=@test_animal.jpg" http://localhost:8000/upload
    ```

4. **確認**:
    - サーバーログに "model loaded" および "Animal detected" が表示されるか確認します。
    - `processed_images/` フォルダにアノテーション付き画像が生成されているか確認します。
    - 通知メールが届いているか確認します。

### 2. エッジサーバー・ロジックのテスト

1. **依存関係の確認**: `pip install ultralytics fastapi uvicorn python-dotenv aiofiles httpx`
2. **サーバー起動**: `python pi/main.py`
3. **サイクルシミュレーション**: 1サイクル分として3枚の画像をアップロードします。
    - 画像1 (動物あり): `curl -X POST -F "file=@deer1.jpg;filename=MAC001-1.jpg" http://localhost:8000/upload`
    - 画像2 (動物あり): `curl -X POST -F "file=@deer2.jpg;filename=MAC001-2.jpg" http://localhost:8000/upload`
    - 画像3 (空): `curl -X POST -F "file=@empty.jpg;filename=MAC001-3.jpg" http://localhost:8000/upload`
4. **確認**:
    - ログに "Cycle MAC001 detected animals: 2/3" と表示されるか確認します。
    - ログに "Forwarding all strings" (転送中) と表示されるか確認します。
    - (外部サーバーのURLが設定されている場合) 外部サーバーがリクエストを受信することを確認します。

### 3. エッジデバイスのテスト

1. **ファームウェア書き込み**: `esp/camera/camera.ino` をコンパイルし、XIAO ESP32S3 に書き込みます。
2. **シリアルモニタ**: シリアルモニタを開きます (115200 bps)。
3. **トリガー**: PIRセンサーの前で手を振るか、タイマー起動を待ちます。
4. **SDカード確認**:
    - ファイルが `[MAC]-[SEQ]-1d.jpg` (または `n`) などの名前で保存されていることを確認します。
5. **アップロード確認**:
    - Wi-Fi と Piサーバーが利用可能な場合、シリアルログに `[UPLOAD] Uploading ...` と表示されることを確認します。
