# 動作確認: YOLOv8 物体検出カウンター

## 概要

作成したスクリプト `count_detections/count_yolo.py` の動作確認手順です。

## 前提条件

- Python環境に `ultralytics` がインストールされていること。

  ```bash
  pip install ultralytics
  ```

## 手順

1. **設定（オプション）**
   スクリプト `count_detections/count_yolo.py` の冒頭にある `DEFAULT_SOURCE_PATH` 変数を、対象の画像フォルダパスに変更します。

   ```python
   DEFAULT_SOURCE_PATH = r"C:\path\to\your\images"
   ```

2. **スクリプトの実行**
   **方法A: 設定したパスを使用する場合**
   引数なしで実行します。

   ```bash
   python count_detections/count_yolo.py
   ```

   **方法B: コマンドラインでパスを指定する場合**
   引数でパスを指定すると、設定変数の値よりも優先されます。

   ```bash
   python count_detections/count_yolo.py "C:\path\to\other\images"
   ```

3. **出力の確認**
   以下のような出力が表示されることを確認します。

   ```text
   Processing 10 images in test_images...
   ------------------------------
   Total Images: 10
   Images with Detections: 5
   Detection Rate: 50.00%
   ------------------------------
   ```

## 注意点

- 初回実行時は `yolov8n.pt` モデルが自動的にダウンロードされます。
- 画像が存在しないフォルダを指定した場合はエラーが表示されます。
