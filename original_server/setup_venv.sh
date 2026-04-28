#!/bin/bash

echo "==================================================="
echo "  Python 仮想環境 (venv) セットアップスクリプト"
echo "==================================================="

# Python 3.10以降が使われることを想定（お使いの環境に合わせて python3 にしています）
PYTHON_CMD="python3"

echo "[1/3] venv を作成しています..."
$PYTHON_CMD -m venv venv
if [ $? -ne 0 ]; then
    echo "[エラー] venv の作成に失敗しました。"
    echo "ubuntu/debian系の場合、以下のコマンドでvenvパッケージをインストールしてください:"
    echo "sudo apt-get install python3-venv"
    exit 1
fi

echo "[2/3] venv を有効化しています..."
source venv/bin/activate

echo "[3/3] pip を最新版にアップデートしています..."
pip install --upgrade pip

echo ""
echo "==================================================="
echo "✅ 仮想環境 (venv) の作成と有効化が完了しました。"
echo ""
echo "※注意: このスクリプト内で有効化した環境は、スクリプト終了後に元に戻る場合があります。"
echo "手動で仮想環境に入る場合は、ターミナルで以下のコマンドを実行してください:"
echo ""
echo "  source venv/bin/activate"
echo ""
echo "仮想環境に入った後、以下のコマンドでテスト環境をセットアップできます:"
echo "  python setup_local_test.py"
echo "==================================================="
