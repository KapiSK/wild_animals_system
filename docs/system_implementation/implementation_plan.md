# システム実装計画

## 目標

`docs/system_requirements.md` で定義されたシステム全体の要件を実装します。
エッジサーバーに軽量なYOLOv8nを導入し、外部サーバーではMegaDetectorを使用して高精度な解析を行います。

## ユーザー確認事項

> [!IMPORTANT]
> **エッジサーバーの推論モデル**: Raspberry Pi上で **YOLOv8n** を使用します。これによりMegaDetectorよりも高速な推論が期待できますが、一般的な動物クラス（COCO dataset準拠）での検出となります。

> [!WARNING]
> **ESP32のファイル命名**: ESP32等のファイル命名規則 (`{id}-{1~3}.jpg`) を変更するため、固定の `img1.jpg` 等ではなく、これらの新しいファイル名を動的に扱うようアップロードロジックを更新する必要があります。

## 変更案

### 1. 外部サーバー (解析・通知)

#### [MODIFY] [original_server/server.py](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py)

- **推論エンジン**:
  - **MegaDetector v5a** を継続して使用します（コード上の変更は少ないですが、役割が明確化されました）。
  - 検出された動物に対してバウンディングボックス(BB)を描画する処理が堅牢であることを確認します。
- **通知**:
  - Gmail SMTPによる通知で、BB描画済みの画像を添付します。

### 2. エッジサーバー (Raspberry Pi)

#### [MODIFY] [pi/main.py](file:///c:/Users/kapib/vscodegit/wild_animals/test2/pi/main.py)

- **フィルタリングロジック**:
  - 「3枚中2枚」ルールを実装します。
  - 受信した画像をバッファリングし、1サイクル（3枚）揃った時点で判定を行います（またはタイムアウト）。
  - 2枚以上で動物が検出された場合のみ、3枚全てを外部サーバーへ転送します。

#### [MODIFY] [pi/detector.py](file:///c:/Users/kapib/vscodegit/wild_animals/test2/pi/detector.py)

- **YOLOv8n統合**:
  - `ultralytics` ライブラリを使用し、YOLOv8nモデル (`yolov8n.pt`) をロードするように実装を変更します。
  - COCOデータセットのクラスから動物（bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe等）のみを検出対象 (Target Classes) とするようにフィルタリングします。

### 3. エッジデバイス (ESP32)

#### [MODIFY] [esp/camera/camera.ino](file:///c:/Users/kapib/vscodegit/wild_animals/test2/esp/camera/camera.ino)

- **ファイル命名**:
  - `shootAndSave` を更新し、`{CycleID}-{1~3}{n/d}.jpg` の形式で保存するようにします。
- **アップロードロジック**:
  - 新しいファイル名を扱えるよう `uploadFile` を更新します。

## 検証計画

### 自動テスト

- **ユニットテスト**:
  - Pi上のフィルタリングロジック（3枚中2枚ルール）のPythonテスト。

### 手動検証

- **データフローテスト**:
    1. ESP32をトリガーして撮影させる。
    2. Piが3枚の画像を受信し、ログにYOLOv8nによる検出結果が出力されることを確認する。
    3. 動物が2枚以上検出された場合のみ、外部サーバーへ転送されることを確認する。
    4. 外部サーバーでMegaDetectorが動作し、メール通知が届くことを確認する。
