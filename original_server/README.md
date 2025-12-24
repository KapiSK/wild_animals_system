# オリジナルサーバー (外部サーバー)

このサーバーはエッジデバイスから画像を受信し、YOLOv8による推論を行って動物を検出し、処理済みの画像を添付してメール通知を行います。

## セットアップ

1. **必要なライブラリのインストール**

    ```bash
    pip install -r requirements.txt
    ```

2. **環境変数**
    このディレクトリ (`original_server/.env`) に `.env` ファイルを作成し、以下の内容を設定してください：

    ```env
    UPLOAD_DIR=received_images
    PROCESSED_DIR=processed_images
    
    # メール設定 (Gmailの例)
    # Gmailで2段階認証を使用している場合は、アプリパスワードを生成してください
    SMTP_SERVER=smtp.gmail.com
    SMTP_PORT=587
    SENDER_EMAIL=your_email@gmail.com
    SENDER_PASSWORD=your_app_password
    RECIPIENT_EMAIL=recipient@example.com
    ```

3. **サーバーの実行**

    ```bash
    python server.py
    ```

    または uvicorn を直接使用する場合：

    ```bash
    uvicorn server:app --reload
    ```

## エッジデバイスの設定

Raspberry Pi (エッジサーバー) 上で `.env` を更新し、このサーバーを指定してください：

```env
MAIN_SERVER_URL=http://<あなたのPCのIPアドレス>:8000/upload
```
