import os
import json
import subprocess
import sys
from pathlib import Path

def main():
    print("=== クラウドサーバー ローカルテスト環境セットアップ ===")
    
    # 1. 必要なディレクトリの作成
    dirs_to_create = ["uploads", "processed_images", "events", "videos"]
    for d in dirs_to_create:
        Path(d).mkdir(exist_ok=True)
        print(f"✅ ディレクトリ確認: {d}/")
        
    # 2. .envファイルの作成（存在しない場合のみ）
    env_file = Path(".env")
    if not env_file.exists():
        env_content = """# テスト環境用 .env
PORT=8000
ADMIN_EMAIL=test@example.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=dummy
SMTP_PASSWORD=dummy
"""
        env_file.write_text(env_content, encoding="utf-8")
        print("✅ .envファイルを作成しました。")
    else:
        print("✅ .envファイルは既に存在します。")

    # 3. user_access_config.json の作成（テスト用アカウント）
    user_conf = Path("user_access_config.json")
    if not user_conf.exists():
        users = {
            "admin": {"password": "password", "role": "admin"}
        }
        user_conf.write_text(json.dumps(users, indent=4), encoding="utf-8")
        print("✅ user_access_config.json を作成しました (ID: admin, PW: password)")

    # 4. telemetry.json の作成（ダミーデータ）
    telemetry_file = Path("telemetry.json")
    if not telemetry_file.exists():
        telemetry_file.write_text(json.dumps({}), encoding="utf-8")
        print("✅ telemetry.json を作成しました")

    # 5. pip install の実行
    print("⏳ 依存パッケージのインストールを実行中...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ 依存パッケージのインストール完了")
    except Exception as e:
        print(f"❌ 依存パッケージのインストール中にエラーが発生しました: {e}")
        print("手動で pip install -r requirements.txt を実行してください。")

    # 6. 完了メッセージと起動方法の案内
    print("\n=== セットアップが完了しました！ ===")
    print("以下のコマンドでテストサーバーを起動してください:")
    print("  uvicorn server:app --host 0.0.0.0 --port 8000 --reload")
    print("\n[テスト手順]")
    print("1. クラウドサーバー起動後、ブラウザで http://localhost:8000 にアクセスし、admin / password でログインできます。")
    print("2. エッジサーバー(pi や satos)からの送信テストを行う場合は、")
    print("   エッジ側スクリプトの CLOUD_URL 等を http://<このPCのIPアドレス>:8000/upload に変更して実行してください。")

if __name__ == "__main__":
    main()
