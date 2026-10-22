# オープンキャンパス用 FTP カメラデモ

既製品カメラ → FTP受信 → YOLO人物検出 → ブラウザ表示。
転送完了後に1枚ずつ人物の枠を描いて表示します。人物が写っていない画像も表示します。ESP32用の3枚単位の判定はFTPには適用しません。画面は1秒ごとに最新10枚を取得します。

## 起動

Python 3.10以降を使用します。

```bash
cd open_campus/server
python -m venv venv
# Linux / Raspberry Pi
source venv/bin/activate
# Windows PowerShell: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env.example` を参考に `.env` にFTP設定を追記し、`FTP_PASSWORD` に任意のパスワードを設定してください（必須）。既存の `.env` は上書きしないでください。

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

初回は `yolov8n.pt` のダウンロードにインターネット接続が必要です。会場へ持ち込む前に起動してモデルを準備してください。FTPポートを共有するため、Uvicornは **1 worker** で実行します。
ブラウザで `http://サーバーのLAN内IP:8000/` を開きます。

## カメラのFTP設定

| 項目 | 設定値 |
| --- | --- |
| 通信方式 | FTP（SFTP / FTPSではありません） |
| サーバー | デモ機のLAN内IPアドレス |
| ポート | `2121`（`FTP_PORT` と一致させる） |
| ユーザー名 | `camera`（`FTP_USER`） |
| パスワード | `.env` の `FTP_PASSWORD` |
| 転送モード | PASV / パッシブ推奨 |
| 保存先 | `/`（日付などのサブフォルダ作成も可） |
| 送信内容 | 静止画、JPEG推奨 |

カメラ側で定期送信またはイベント時の静止画FTP送信を有効にします。接続テストだけでは画像を送信しない機種もあります。
ファイアウォールではTCP **8000、2121、60000–60009** をカメラ・閲覧端末のLANから許可します。FTP制御ポートだけでは画像を転送できません。通常 `FTP_MASQUERADE_ADDRESS` は空で構いません。FTPは認証情報・画像を暗号化しないため会場内の専用LANで使用してください。
21番固定のカメラは `FTP_PORT=21` とします。Linuxの下記サービス設定には低位ポートのバインド権限を付与しています。

## Raspberry Piで自動起動

`.env` 設定後、一般ユーザーから実行します。配置場所の `server` に仮想環境を作成し、専用サービスを登録します。

```bash
sudo bash setup_pi_services.sh
journalctl -u open-campus-camera -f
```

## PCから送信テスト

別のターミナルで実行します。パスワードはプロンプトで入力します。

```bash
curl --user camera --ftp-create-dirs -T test.jpg ftp://127.0.0.1:2121/demo/test.jpg
```

同じ名前を再送しても受信ごとに別の画像として保存します。転送途中の画像・破損画像・接続テスト用テキストは公開しません。転送後の一時ファイル名からのリネームにも対応します。

## 保存場所

- `ftp_inbox/`: カメラ送信先。転送後のリネーム対応のため元ファイルを保持します。運用終了後、サーバーを停止して不要なファイルを削除してください。
- `processing/`: 検出用一時ファイル。処理後に削除します。
- `uploads/`: 枠付き表示用JPEG。7日を超えた画像を日次で削除します。
- `edge_server.log`: 受信・検出ログ。検出失敗時はその画像を公開せず記録します。

相対パスは `server` 基準です。画像の連続送信で検出待ちが増える場合は撮影間隔を調整してください。
既存ESP32向けHTTPエンドポイントは残しています。FTPには `API_TOKEN` ではなくFTPユーザー名・パスワードを使用します。

## 自動テスト

```bash
python -m unittest discover -s tests -v
```

FTP転送からHTTP画像取得まで検証します。テストでは人物検出器を代替します。実機での人物枠は上記の送信テストで確認してください。
FTP完了判定は [pyftpdlibのコールバック](https://pyftpdlib.readthedocs.io/en/latest/api.html) を使用しています。
