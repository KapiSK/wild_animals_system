# 外部サーバー実装計画 (MegaDetector版)

## 目標

エッジサーバー（Raspberry Pi）から画像を受信し、**MegaDetector v5** を用いて動物を検出し、検出時にユーザーへメール通知を行う外部サーバーを開発する。

## 変更内容

### 外部サーバー (`original_server/`)

#### [変更] `server.py`

- **モデル**: `yolov8n.pt` から `md_v5a.0.0.pt` (MegaDetector v5a) に変更。
- **ダウンロード**: サーバー起動時にモデルファイルが存在しない場合、自動的にダウンロードするロジックを追加。
  - URL: `https://github.com/ecology-tech/MegaDetector/releases/download/v5.0/md_v5a.0.0.pt`
- **クラスID**:
  - MegaDetector (0-indexed in ultralytics):
    - 0: animal (動物)
    - 1: person (人)
    - 2: vehicle (乗り物)
  - フィルタ: `0` (animal) のみを対象とする。

#### [変更] `requirements.txt`

- `requests` (モデルダウンロード用) を追加。
- `ultralytics` はそのまま維持 (YOLOv5モデルのロードをサポート)。

### エッジサーバー (`pi/`)

- 変更なし (既存の計画通り)。

## 検証計画

### 手動検証

1. 外部サーバーを起動: `python server.py`
    - 初回起動時に `md_v5a.0.0.pt` がダウンロードされることを確認。
2. テスト画像 (動物、人、空の画像) を送信。
3. 確認事項:
    - 動物のみが検出・カウントされ、メール通知されること。
    - 人や乗り物は通知対象外（または設定により変更可能）であること。
