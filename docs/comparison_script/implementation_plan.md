# 実装計画: MegaDetector vs YOLOv8 比較スクリプト

## 目標

MegaDetector (MD) と YOLOv8 を使用して、同一画像セットに対する動物検知性能を比較する。
結果を画像単位およびサイクル単位で分類・可視化する。

## ユーザーレビューが必要な事項

- **MegaDetectorモデルのパス**: ユーザーにモデルファイル（`.pt`）の場所を指定してもらうか、ダウンロード手順を案内する必要がある。
- **サイクルIDの抽出**: ファイル名が `pi/main.py` の形式（`TIMESTAMP_CycleID-Index.jpg`）か、元の形式（`CycleID-Index.jpg`）かを確認する必要がある。両方に対応可能なロジックを実装する。

## 変更内容

### 新規フォルダ作成

- `compare_models/`

### スクリプト作成

#### [NEW] [compare_models.py](file:///c%3A/Users/kapib/vscodegit/wild_animals/test2/compare_models/compare_models.py)

- **機能**:
  - 設定変数:
    - `IMAGE_DIR`: 画像フォルダパス (デフォルトは以前のパスを使用)
    - `YOLO_MODEL_PATH`: YOLOv8モデルパス (`yolov8n.pt`)
    - `MD_MODEL_PATH`: MegaDetectorモデルパス (設定必須)
    - `CONF_THRESHOLD`: 推論時の信頼度閾値 (デフォルト: 0.25)

  - **推論**:
    - 全画像をループ。
    - YOLOv8 で推論 -> 動物検知有無 (特定のクラスIDのみ対象とするか？通常は全検出or動物クラス)
      - `conf` 引数に閾値を設定。
    - MegaDetector で推論 -> 動物検知有無 (MDは 'animal' クラスがある)
      - 結果の `conf` 値を閾値と比較。
  - **分類**:
    - 各画像について以下の4パターンに分類:
      1. Both Detected
      2. Only MegaDetector
      3. Only YOLO
      4. Neither
  - **サイクル集計**:
    - ファイル名からサイクルIDを抽出。
    - サイクル内の全画像の結果を統合し、サイクル単位での検知有無を判定。
    - サイクル単位でも同様に4パターンに分類。
  - **可視化**:
    - `matplotlib` を使用して、分類結果の件数を棒グラフまたは円グラフで可視化。
    - 結果をコンソールに出力し、CSV等で保存（オプション）。

## 検証計画

1. 少数の画像でスクリプトを実行し、エラーが出ないことを確認。
2. MegaDetectorモデルが見つからない場合のエラーハンドリングを確認。
3. 出力されたグラフを確認。
