# 動作確認: MegaDetector vs YOLOv8 比較スクリプト

## 概要

作成したスクリプト `compare_models/compare_models.py` の動作確認および使用手順です。

## 前提条件

### 1. 自動セットアップ（推奨）

同梱の `compare_models/setup.sh` を実行することで、必要なライブラリのインストールとMegaDetectorモデルのダウンロードを自動で行えます。

```bash
cd compare_models
bash setup.sh
```

### 2. 手動セットアップ

手動で行う場合は、以下の手順に従ってください。

#### ライブラリのインストール

必要なライブラリをインストールします。YOLOv8用の `ultralytics` が必要です。

```bash
pip install ultralytics tqdm torch torchvision
```

#### MegaDetectorモデルの準備

MegaDetector (v5) のモデルファイル (`.pt`) が必要です。
まだお持ちでない場合は、以下のGitHubリリースページなどから `md_v5a.0.0.pt` または `md_v5b.0.0.pt` をダウンロードしてください。

- [Microsoft/CameraTraps Releases](https://github.com/microsoft/CameraTraps/releases)

ダウンロード後、プロジェクトフォルダ（例: `compare_models/`）に配置してください。

## 実行手順

### コマンドラインでの実行

スクリプトは `compare_models` フォルダ内にあります。MegaDetectorモデルのパスを引数で指定して実行します。

```bash
# 例: MegaDetectorモデルがカレントディレクトリにある場合
python compare_models/compare_models.py --md "path/to/md_v5a.0.0.pt"

# 例: 画像フォルダ、信頼度、出力先を変更する場合
# 例: 画像フォルダ、信頼度、出力先を変更する場合
python compare_models/compare_models.py --md "path/to/md_v5a.0.0.pt" --images "/path/to/images" --yolo-conf 0.05 --md-conf 0.3 --output "my_results"
```

引数を省略した場合、以下のデフォルト値が使用されます。

- 画像パス: `/home/satoko/project/hykecam_1010/ALL/night/`
- YOLO信頼度: `0.1` (エッジ側)
- MD信頼度: `0.25` (クラウド側)
- 出力先: `compare_results`

### 設定の変更（オプション）

スクリプト `compare_models/compare_models.py` の冒頭にある変数を直接編集することで、デフォルト値を変更できます。

```python
# 設定: モデルと画像のパス
DEFAULT_IMAGE_DIR = r"/home/satoko/project/hykecam_1010/ALL/night/"
DEFAULT_MD_MODEL_PATH = r"md_v5a.0.0.pt" 
DEFAULT_YOLO_CONF = 0.1
DEFAULT_MD_CONF = 0.25
DEFAULT_OUTPUT_DIR = "compare_results"
```

## 出力結果

### コンソール出力

実行が完了すると、以下のような集計結果が表示されます。

```text
========================================
 SUMMARY
========================================

[Per Image] Total: 100
  Both Detected:      40
  MD Only:             5
  YOLO Only:           2
  Neither:            53

[Per Cycle] Total: 30
  Both Detected:      12
  MD Only:             2
  YOLO Only:           1
  Neither:            15

========================================
 EDGE-CLOUD PIPELINE SIMULATION
========================================
Edge Threshold (YOLO): 0.1
Cloud Threshold (MD):  0.25

[Analysis]
Lost at Edge (MD detected, YOLO missed): 2
  -> WARNING: 2 images would be lost at the edge.
     Consider lowering the YOLO threshold (--yolo-conf).

Edge Filter Rate: 50.0%
  - Total Images: 30
  - Sent to Cloud: 13
  - Filtered Out: 17
```

### CSVログ出力

`compare_results/detailed_log.csv` に、画像ごとの詳細な結果が出力されます。
カラム: `Filename`, `CycleID`, `YOLO_Detected`, `MD_Detected`, `YOLO_Conf`, `MD_Conf`, `YOLO_Label`, `MD_Label`

### 検知画像の保存

`compare_results/detected_images/` 配下に、以下のフォルダが作成され、検知された画像がコピーされます。

- `md_detected/`: MegaDetectorで検知された画像
- `yolo_detected/`: YOLOv8で検知された画像

## 注意点

- **クラスID**: YOLOv8はCOCOデータセットの **動物クラス(bird, cat, dog...) および 人(person)** を対象にしています。MegaDetectorはクラスID 1 (animal) および 0 (some versions) を対象にしています。
- **サイクル抽出**: ファイル名末尾の `-1`, `-2`, `-3` 等のインデックスの直前までをサイクルIDとしてグループ化します。

## ベンチマークツール (`benchmark_yolo.py`)

YOLOのモデル（n, s, m...）や閾値を変更しながら、サイクル単位での「取りこぼし率」を一括測定できるツールも用意しました。

### 実行方法

```bash
# ヘルパースクリプトを使用（推奨）
# デフォルトで yolov8n.pt と yolov8s.pt を比較します
bash compare_models/run_benchmark.sh
```

### 結果の見方

`benchmark_results/benchmark_summary.csv` に結果が出力されます。

| Model | Threshold | MD_Positive_Cycles | FN_Cycles (Missed) | Miss_Rate (%) |
| :--- | :--- | :--- | :--- | :--- |
| yolov8n.pt | 0.1 | 20 | 2 | 10.00 |
| yolov8n.pt | 0.2 | 20 | 5 | 25.00 |
| yolov8s.pt | 0.1 | 20 | 1 | 5.00 |

- **Miss_Rate (%)**: 取りこぼし率。低いほど良いです。
- **FN_Cycles**: 取りこぼしたサイクルの数。
- **MD_Positive_Cycles**: MegaDetectorが検知した（正解）サイクルの総数。
