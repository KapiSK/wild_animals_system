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

必要なライブラリをインストールします。YOLOv8用の `ultralytics` とグラフ描画用の `matplotlib` が必要です。

```bash
pip install ultralytics matplotlib tqdm torch torchvision
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
python compare_models/compare_models.py --md "path/to/md_v5a.0.0.pt" --images "/path/to/images" --conf 0.4 --output "my_results"
```

引数を省略した場合、以下のデフォルト値が使用されます。

- 画像パス: `/home/slab/project/data/hykecam_1010/ALL/night/`
- 信頼度: `0.25`
- 出力先: `compare_results`

### 設定の変更（オプション）

スクリプト `compare_models/compare_models.py` の冒頭にある変数を直接編集することで、デフォルト値を変更できます。

```python
# 設定: モデルと画像のパス
DEFAULT_IMAGE_DIR = r"/home/slab/project/data/hykecam_1010/ALL/night/"
DEFAULT_MD_MODEL_PATH = r"md_v5a.0.0.pt" 
DEFAULT_CONF_THRESHOLD = 0.25
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
```

### CSVログ出力

`compare_results/detailed_log.csv` に、画像ごとの詳細な結果が出力されます。
カラム: `Filename`, `CycleID`, `YOLO_Detected`, `MD_Detected`, `YOLO_Conf`, `MD_Conf`

### 検知画像の保存

`compare_results/detected_images/` 配下に、以下のフォルダが作成され、検知された画像がコピーされます。

- `md_detected/`: MegaDetectorで検知された画像
- `yolo_detected/`: YOLOv8で検知された画像

### グラフ出力

`compare_results/comparison_chart.png` に、画像単位およびサイクル単位の分類結果を示す円グラフが保存されます。

## 注意点

- **クラスID**: YOLOv8はCOCOデータセットの動物クラス(cat, dog, bird, etc.)を対象にしています。MegaDetectorはクラスID 1 (animal) を対象にしています。
- **サイクル抽出**: ファイル名末尾の `-1`, `-2`, `-3` 等のインデックスの直前までをサイクルIDとしてグループ化します。
