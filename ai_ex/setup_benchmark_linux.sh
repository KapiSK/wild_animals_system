#!/bin/bash

echo "==================================================="
echo "  MegaDetector V5a vs V6 Benchmark Setup (Linux)"
echo "==================================================="

# 1. 仮想環境の作成
echo "[1/4] Python仮想環境 (venv) を作成しています..."
python3 -m venv venv
if [ $? -ne 0 ]; then
    echo "[エラー] venv の作成に失敗しました。python3-venv がインストールされているか確認してください。"
    exit 1
fi

# 2. 仮想環境の有効化
echo "[2/4] venv を有効化しています..."
source venv/bin/activate

# pip のアップデート
pip install --upgrade pip

# 3. ライブラリのインストール
echo "[3/4] 必要なライブラリをインストールしています..."
# CUDA 11.8 対応の PyTorch (サーバー環境に合わせて変更してください)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# MegaDetector依存関係
pip install yolov5==7.0.11
pip install PytorchWildlife
# yolov5 と huggingface_hub の競合回避
pip install "huggingface_hub<0.25"

# データ処理・描画ライブラリ
pip install scikit-learn matplotlib seaborn pandas opencv-python

# 4. モデルのダウンロード (V5a)
echo "[4/4] モデルファイルを確認しています..."
MODEL_FILE="../md_v5a.0.0.pt"
if [ ! -f "$MODEL_FILE" ]; then
    echo "md_v5a.0.0.pt が見つかりません。ダウンロードします..."
    wget -O "$MODEL_FILE" "https://github.com/agentmorris/MegaDetector/releases/download/v5.0/md_v5a.0.0.pt"
else
    echo "md_v5a.0.0.pt は既に存在します。"
fi

echo "==================================================="
echo "✅ セットアップが完了しました！"
echo "以下のコマンドで仮想環境に入り、スクリプトを実行してください:"
echo ""
echo "  source venv/bin/activate"
echo "  python benchmark_v5a_vs_v6_matrix.py"
echo "==================================================="
