# MegaDetector v5a vs v6 性能比較ベンチマーク計画 (Linux GPUサーバー向け)

MegaDetector v5a（現行クラウド環境）と v6（最新モデル）の性能差を定量的に比較し、クラウドサーバーのモデル更新の必要性を判断するためのベンチマーク環境を構築します。

## 目的
V6の推論結果を「擬似正解 (Ground Truth)」として扱い、V5aがどれだけ合致しているか（混同行列）を高速に算出します。また、両モデルの**結果が食い違った（Disagree）ケースのみを重点的に抽出し、比較画像を生成する**ことで、大規模データセットでも現実的な処理時間とストレージ容量で効果的な分析を可能にします。

## Proposed Changes

### 1. Linux用環境構築スクリプトの作成

#### [NEW] `ai_ex/setup_benchmark_linux.sh`
GPUサーバーでの環境構築を自動化します。
- `python3 -m venv venv` による仮想環境構築
- GPU版PyTorchのインストール
- 必要なライブラリのインストール (`yolov5==7.0.11`, `PytorchWildlife`, `huggingface_hub<0.25`, `scikit-learn`, `matplotlib`, `seaborn`, `opencv-python`, `pandas` など)
- V5aモデル (`md_v5a.0.0.pt`) の自動ダウンロード

### 2. 比較ベンチマーク用スクリプトの作成

#### [NEW] `ai_ex/benchmark_v5a_vs_v6_matrix.py`
ユーザーが簡単に設定を変更できるよう、スクリプト上部に分かりやすい設定ブロック（Configuration Block）を配置します。

1. **設定ブロック (スクリプト上部)**
   - `INPUT_DIR`: 画像フォルダのパス（デフォルト: `"animals/"`）
   - `OUTPUT_DIR`: 結果出力フォルダのパス（デフォルト: `"results_benchmark/"`）
   - `V5A_CONF_THRESHOLD`: V5aの信頼度閾値（デフォルト: `0.25`）
   - `V6_CONF_THRESHOLD`: V6の信頼度閾値（デフォルト: `0.30`）

2. **推論と混同行列 (Confusion Matrix) の生成**
   - V6を正解とした場合の4象限（TP, TN, FP, FN）を計算し、ターミナル上にCUIで出力します。
   - `seaborn` を使用してヒートマップ画像を `results_benchmark/confusion_matrix.png` に保存します。

3. **結果の食い違い（Mismatch）の抽出と可視化**
   - V5aとV6で検知結果（有無）が異なった画像のみを対象に、**横並び比較画像（左: V5a, 右: V6）**を生成し、`results_benchmark/mismatches/` フォルダに保存します。
   - 食い違った画像のリストを `results_benchmark/mismatch_list.csv` として出力します。

4. **全体レポート出力**
   - 全画像の推論時間、スコアなどを含む統合レポートは `results_benchmark/benchmark_full_report.csv` に出力します。

## Verification Plan

### Automated Tests
- ローカル環境にて数枚の画像を使ってスクリプトを実行し、Mismatchの画像とリスト、混同行列が正しく生成されるかを確認します。

### Manual Verification
- ユーザーにてGPUサーバーへデプロイして本番データセットで動作検証を行っていただきます。
