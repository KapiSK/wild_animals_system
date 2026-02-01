# 実装計画: YOLOv8 物体検出カウンター

## 目標

指定されたフォルダ内の画像に対してYOLOv8nを実行し、物体が検出された画像の割合を出力するプログラムを作成する。

## ユーザーレビューが必要な事項

- 特になし (新規スクリプト作成のため)

## 変更内容

### 新規フォルダ作成

- `c:\Users\kapib\vscodegit\wild_animals\test2\count_detections\`

### スクリプト作成

#### [NEW] [count_yolo.py](file:///c%3A/Users/kapib/vscodegit/wild_animals/test2/count_detections/count_yolo.py)

- **機能**:
  - コマンドライン引数またはコード内の変数で対象画像フォルダを指定。
  - `ultralytics` ライブラリを使用して `yolov8n.pt` モデルをロード。
  - 対象フォルダ内の画像ファイル (.jpg, .png, .jpeg) をリストアップ。

#### [MODIFY] [count_yolo.py](file:///c%3A/Users/kapib/vscodegit/wild_animals/test2/count_detections/count_yolo.py)

- **変更点**:
  - スクリプト冒頭に `DEFAULT_SOURCE_PATH` 変数を追加し、ユーザーがここでパスを設定できるようにする。
  - コマンドライン引数が指定されていない場合は、この変数の値を使用するようにロジックを変更する。

  - 各画像に対して推論を実行。
  - 検出された物体 (`results[0].boxes`) があるかどうかを判定。
  - 結果を集計し、検出された画像数 / 全画像数 を出力する。

## 検証計画

### 手動検証

1. テスト用の画像フォルダを用意する（または既存のフォルダを使用）。
2. スクリプトを実行する。

   ```bash
   python count_detections/count_yolo.py --source <画像フォルダパス>
   ```

3. 出力結果（例: "Detected: 5/10 (50.0%)"）が正しいか確認する。
