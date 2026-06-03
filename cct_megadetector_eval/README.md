# Caltech Camera Traps (CCT) MegaDetector Evaluation

このプロジェクトは、Caltech Camera Traps (CCT) データセットを用いて、MegaDetector (v5a, v6-compact, v6-extra) の動物検出性能（animal / empty）を比較・評価するためのツール群です。

## 概要
- CCT の image-level annotations を使用し、指定した枚数（例: animal 3000枚, empty 3000枚）のサブセットを自動作成・ダウンロードします。
- MegaDetectorのバッチ推論 (`run_detector_batch`) を実行し、複数の閾値（Threshold）で Precision, Recall, F1, 誤検知率などを算出します。
- MegaDetectorは `animal`, `person`, `vehicle` を検出しますが、本検証では主に `animal` クラス（ID "1"）の検出性能を評価します。CCTは人検出の評価にはあまり向いていないため、人を評価する場合は別途データセットを用意してください。

## インストール

```bash
# 仮想環境の作成と有効化 (推奨)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 依存ライブラリのインストール
pip install -r requirements.txt
```
※ `megadetector` パッケージは、公式のセットアップ手順に従ってインストールされているか、上記コマンドで適切に導入されている必要があります。

## CCTアノテーションの準備
以下のファイルをLILA等からダウンロードし、`data/annotations/` 以下に配置してください（存在しないディレクトリは自動作成されますが、事前に手動で配置することを推奨します）。
- `image_annotations.json` (必須)
- `bbox_annotations.json` (BBox評価を行う場合のみ)
- `splits.json` (オプション)

## 設定の変更 (`config.yaml`)
`config.yaml` を編集することで、以下を変更できます。
- サンプリング枚数 (`n_animal`, `n_empty`)
- V5a/V6のモデル名（ローカル環境のMegaDetectorが認識するモデル名）
- 評価するThresholdのリスト

## 実行手順

プロジェクトルートから以下の順番でスクリプトを実行してください。

```bash
# 1. サブセット（評価用画像のリスト）の作成
python scripts/01_make_subset.py --config config.yaml

# 2. 画像のダウンロード
python scripts/02_download_images.py --config config.yaml

# 3. MegaDetectorによる推論実行
python scripts/03_run_megadetector.py --config config.yaml

# 4. 画像単位（Image-level）での性能評価
python scripts/04_evaluate_image_level.py --config config.yaml

# 5. 結果のグラフ化（PNG出力）
python scripts/05_plot_results.py --config config.yaml
```

## 出力物
- `data/outputs/image_level_threshold_summary.csv`: 各閾値における詳細なメトリクス
- `data/outputs/best_thresholds.csv`: F1最大となる閾値、および Recall >= 0.98 を満たすFP最小の閾値
- `data/outputs/plots/*.png`: 閾値と各種メトリクスの関係を示すグラフ
- `data/subsets/cct_eval_subset.csv`: 評価に使用した画像のリストとGround Truth
- `data/md_results/*.json`: 各モデルの生推論結果
