# YOLO Benchmark Plan

## 概要

YOLOのモデルサイズ（n, s, m, l, x）や信頼度閾値を変更しながら、エッジ側での「取りこぼし率（Lost Cycle Rate）」を測定するツールを作成します。
MegaDetectorの結果を正解（Teacher）として扱います。

## 要件

1. **複数YOLOモデル対応**: `yolov8n.pt`, `yolov8s.pt` などを引数でリストとして受け取るか、ディレクトリ内の `.pt` ファイルを自動スキャンする。
2. **信頼度閾値**: 単一または複数の閾値を設定可能にする（例: 0.1, 0.2, 0.3...）。
3. **正解データ**: MegaDetector (v5) で検出された画像/サイクルを正解とする。
4. **出力**:
    - モデルごとの「サイクル取りこぼし率」、「サイクル過検出率（YOLO Only / Total Cycles）」、「処理時間（参考）」などをCSV/Markdownテーブルで出力。

## 実装方針 (`compare_models/benchmark_yolo.py`)

- **引数**:
  - `--images`: 画像ディレクトリ
  - `--md`: MegaDetectorモデルパス
  - `--yolo-models`: YOLOモデルのパスリスト（スペース区切り）
  - `--confs`: 信頼度閾値のリスト（スペース区切り、デフォルト: 0.1 0.2 0.3 0.4 0.5）
  - `--output`: 出力ディレクトリ

- **処理フロー**:
  1. MegaDetectorで全画像を推論（正解データの作成）。
     - 結果をメモリにキャッシュ（または一時ファイルに保存）。
     - サイクル単位で「MD Detect: True/False」を判定。
  2. 指定された各YOLOモデル・各閾値についてループ。
     - YOLO推論を実行。
     - サイクル単位で「YOLO Detect: True/False」を判定。
     - MDの結果と比較し、「Lost Cycle (MD=True, YOLO=False)」をカウント。
  3. 結果を集計し、MarkdownテーブルおよびCSVとして出力。

- **評価指標**:
  - **MD Positive Cycles**: MDが検知したサイクルの総数。
  - **YOLO Detected (Recall)**: MD Positive のうち、YOLOも検知した数。
  - **Lost Cycles (False Negative)**: MD Positive のうち、YOLOが検知できなかった数。
  - **Lost Rate**: `Lost Cycles / MD Positive Cycles`
  - **YOLO Positive Cycles**: YOLOが検知したサイクルの総数。
  - **Over Detection (False Positive)**: MD Negative のうち、YOLOが検知した数（参考値）。

## ファイル構成

- `compare_models/benchmark_yolo.py`: ベンチマーク実行スクリプト
- `compare_models/run_benchmark.sh`: モデルダウンロードと実行をまとめたシェルスクリプト
