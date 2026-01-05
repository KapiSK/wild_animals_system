# システムテスト・実験手順書

本書は、Windows環境を操作端末として使用し、外部サーバー・エッジサーバー(Pi)の機能をシミュレーション・検証する方法と、最終的なESP32を含めたシステム全体の実験手順をまとめたものです。

## 1. テスト環境の構成

テストは以下の3段階で進行します。

* **Step 1: Windowsローカルシミュレーション**
  * 外部サーバーとエッジサーバー(Pi)の両方をWindows PC上で起動し、相互の連携とロジックを確認します。
* **Step 2: 各コンポーネントの配置と個別テスト**
  * Raspberry Piにエッジサーバーをデプロイし、Windowsからネットワーク経由でリクエストを送り動作を確認します。
* **Step 3: システム統合実験**
  * ESP32、Raspberry Pi、外部サーバーをすべて稼働させ、実際の撮影から通知までの一連の流れを検証します。

---

## Step 1: Windowsローカルシミュレーション

Windows PC上でサーバープログラムを実行し、擬似的にシステム全体の動作を確認します。

### 1.1 準備

必要なライブラリをインストールします。まだの場合は、プロジェクトルートで以下を実行してください。
(推奨: 仮想環境 `venv` の使用)

```powershell
# 仮想環境の作成と有効化 (任意)
python -m venv venv
.\venv\Scripts\Activate.ps1

# 依存関係のインストール
pip install fastapi uvicorn ultralytics opencv-python python-dotenv aiofiles httpx aiosmtplib requests
```

### 1.2 外部サーバーの起動 (Terminal 1)

新しいPowerShellウィンドウを開き、外部サーバーを起動します。

1. `.env` ファイルの設定（`original_server/.env` がなければ作成）:

    ```ini
    # original_server/.env
    # メール通知テスト用 (必要に応じて設定、テストだけなら空でも可)
    SMTP_SERVER=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=your_email@gmail.com
    SMTP_PASSWORD=your_app_password
    NOTIFICATION_EMAIL=target_email@example.com
    ```

2. サーバー起動:

    ```powershell
    # プロジェクトルートで実行
    python original_server/server.py
    ```

    * サーバーは `http://localhost:8000` で待機します。

### 1.3 エッジサーバー(Pi想定)の起動 (Terminal 2)

別のPowerShellウィンドウを開き、エッジサーバーを起動します。
この際、転送先として「ローカルで動いている外部サーバー」を指定します。

1. `.env` ファイルの設定（`pi/.env` がなければ作成）:

    ```ini
    # pi/.env
    UPLOAD_DIR=uploads_pi
    # ローカルの外部サーバーへ転送設定
    MAIN_SERVER_URL=http://localhost:8000/upload
    ```

2. サーバー起動:

    ```powershell
    # プロジェクトルートで実行
    # ポートが衝突しないように 8001番ポートなどで起動します
    uvicorn pi.main:app --port 8001 --reload
    ```

    * エッジサーバーは `http://localhost:8001` で待機します。

### 1.4 動作確認 (Terminal 3: 操作用)

3つ目のPowerShellウィンドウで、クライアントとして画像を送信し、動作を確認します。
`curl` コマンドを使用します。

**シナリオ: 「3枚中2枚」動物が写っているケース（転送されるはず）**

1. テスト画像の準備（`test_images`フォルダなどに適当な画像を用意）
    * `deer.jpg` (動物)
    * `empty.jpg` (風景のみ)
2. コマンド実行（PowerShellでの例）:
    * **Image 1 (動物)**: CycleID `TEST01`

        ```powershell
        curl -X POST -F "file=@test_images/deer.jpg;filename=TEST01-1.jpg" http://localhost:8001/upload
        ```

    * **Image 2 (動物)**: CycleID `TEST01`

        ```powershell
        curl -X POST -F "file=@test_images/deer.jpg;filename=TEST01-2.jpg" http://localhost:8001/upload
        ```

    * **Image 3 (なし)**: CycleID `TEST01`

        ```powershell
        curl -X POST -F "file=@test_images/empty.jpg;filename=TEST01-3.jpg" http://localhost:8001/upload
        ```

**確認事項:**

* **Terminal 2 (Pi)** のログ:
  * `Cycle TEST01 detected animals: 2/3`
  * `Cycle TEST01 MET criteria... Forwarding all strings.`
  * `Successfully forwarded...`
* **Terminal 1 (External)** のログ:
  * `Processing image...`
  * `Animal detected...`
  * (メール設定があれば) メール送信完了ログ
* **フォルダ確認**:
  * `processed_images/` (Original Server下) にバウンディングボックス付き画像が生成されていること。

---

## Step 2: 実機へのデプロイとリモートテスト

Raspberry Piにエッジサーバーを移行し、Windowsからネットワーク経由でテストします。

### 2.1 Raspberry Piのセットアップ

1. Raspberry Piにコード一式 (`pi/` フォルダなど) を転送します。
2. Raspberry Pi上で依存ライブラリをインストールします。
3. `pi/.env` を編集し、`MAIN_SERVER_URL` を **Windows PCのIPアドレス** (またはクラウド上のURL) に設定します。
    * 例: `MAIN_SERVER_URL=http://192.168.1.10:8000/upload`
    * ※ Windows PC側で外部サーバーを動かす場合、Firewallでポート8000を開放する必要があります。

### 2.2 サーバー起動

* **Windows PC**: `python original_server/server.py` (IPアドレス `0.0.0.0` でリッスンするようにコード変更が必要な場合があります。Uvicornなら `--host 0.0.0.0`)
  * 一時的にテストするなら: `uvicorn original_server.server:app --host 0.0.0.0 --port 8000`
* **Raspberry Pi**: `python pi/main.py` (または `uvicorn ... --host 0.0.0.0`)

### 2.3 Windowsからのテスト実行

WindowsのPowerShellから、Raspberry PiのIPアドレスに対して `curl` を実行します。

```powershell
# PiのIPが 192.168.1.20 の場合
curl -X POST -F "file=@test_images/deer.jpg;filename=REALTEST-1.jpg" http://192.168.1.20:8000/upload
```

※ `pi/main.py` 内の `uvicorn.run()` 設定や起動コマンドのポートに注意してください（デフォルト8000）。

---

## Step 3: システム統合実験

ESP32を含めた全体動作を確認します。

### 3.1 準備

1. **外部サーバー**: 稼働中 (Cloud または Windows PC)
2. **エッジサーバー (Pi)**: 稼働中
    * `MAIN_SERVER_URL` が正しく外部サーバーを向いていること。
    * `net/PI_UPLOAD_URL` (ESP32用) のエンドポイントとして機能していること。
3. **エッジデバイス (ESP32)**:
    * `esp/camera/camera.ino` の `net::PI_HOST` や `WIFI_SSID` が正しく設定されていること。
    * ファームウェアを書き込み、バッテリー/電源に接続。

### 3.2 実験手順

1. **ESP32の起動**: 電源を入れます。
2. **撮影トリガー**:
    * PIRセンサー検知範囲で動く、またはシステムのタイマー起動を待ちます。
    * カメラが3枚撮影し、フラッシュLEDが動作するのを確認します。
3. **アップロード確認**:
    * ESP32のシリアルログ（PCに繋いでいる場合）または、Raspberry Piのログを確認します。
    * Pi側で `Receiving upload: ...` と表示されれば画像の受信成功です。
4. **フィルタリングと転送確認**:
    * Pi側でサイクル（3枚）が揃った時点で判定が行われます。
    * 動物（人などYOLOが検知する対象）が映っていれば、外部サーバーへ転送されます。
5. **最終確認**:
    * 外部サーバーからのメール通知が届くことを確認します。

### トラブルシューティング

* **ESP32がPiに繋がらない**:
  * Wi-Fi設定 (SSID/Pass) を確認。
  * PiとESP32が同じネットワークにいるか確認。
  * mDNS (`wild-animal.local`) が解決できない場合、IPアドレス直打ち (`net::PI_HOST` をIP指定) を試してください。
* **Piから外部サーバーに転送されない**:
  * `MAIN_SERVER_URL` の設定ミスがないか確認。
  * `CycleManager` の判定ログを確認（「2 out of 3」を満たしていない可能性）。
* **外部サーバーでエラー**:
  * モデルファイル (`md_v5a.0.0.pt`) が存在するか確認。
  * メール送信設定 (SMTP) が正しいか確認。
