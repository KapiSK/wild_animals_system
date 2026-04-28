@echo off
echo ===================================================
echo   Python 仮想環境 (venv) セットアップスクリプト
echo ===================================================

echo [1/3] venv を作成しています...
python -m venv venv
if %errorlevel% neq 0 (
    echo [エラー] venv の作成に失敗しました。Pythonがインストールされているか確認してください。
    pause
    exit /b %errorlevel%
)

echo [2/3] venv を有効化しています...
call venv\Scripts\activate.bat

echo [3/3] pip を最新版にアップデートしています...
python -m pip install --upgrade pip

echo.
echo ===================================================
echo ✅ 仮想環境 (venv) の作成と有効化が完了しました。
echo.
echo 引き続きテスト環境をセットアップする場合は、
echo 以下のコマンドを実行してください:
echo.
echo   python setup_local_test.py
echo.
echo (仮想環境を終了する場合は 'deactivate' と入力してください)
echo ===================================================
cmd /k
