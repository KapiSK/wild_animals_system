# カメラ統合サーバーにおける推論およびクラウド連携の実装計画（改訂版）

先ほどまでの計画を変更し、`satos` プログラムが稼働するサーバー（以下、カメラ統合サーバー）内でみずから `yolov8n` を使った推論を行い、対象（人や動物）が検出された場合のみ**ダイレクトにクラウドサーバー（Main Server）に送信する**構成に方針転換します。

## 実装内容の概要

1. **ローカル推論機能（YOLOv8n）の導入**
   - エッジサーバー（Raspberry Pi）と同等の `ultralytics`ライブラリを使った推論機能を `gmail_image_saver.py` に組み込みます。
   - `yolov8n.pt` モデルを用いた物体検出メソッド `detect_targets` を実装します。
   - 人・動物のCOCOクラス（0, 14～23）でフィルタリングし、3フレームのうち最低1枚で検知した場合にのみクラウドへ送信するフラグを立てます（BBoxの描画はクラウド側でMegaDetectorが行うためここでは実施しません）。

2. **通信先をクラウドサーバー（Main Server）へ変更**
   - `EDGE_SERVER_URL` から **`CLOUD_SERVER_URL`** へ名称と役割を変更します。
   - アップロード処理を `original_server` の仕様（`multipart/form-data` 形式で `file` を送信する）に合わせます。実装をシンプルにするため `requests` ライブラリを採用します。
   - 送信用のファイル名を `satos_<元のファイル名>-001-1.jpg` 等のフォーマットに調整し、クラウドサーバーが正しく別々のカメラサイクルとして認識できるようにします。

3. **環境変数 `.env` の修正**
   - `EDGE_SERVER_URL` 系を削除し、`CLOUD_SERVER_URL` と `CLOUD_SERVER_API_KEY` に変えます。

## User Review Required

> [!IMPORTANT]
> 以下の変更点をご承認ください：
> 1. 推論負荷がカメラ統合サーバー上に発生しますが、構成としては独立して動作するため問題ないという認識で合っていますか？
> 2. `ultralytics`, `requests`, `opencv-python` といった推論用・通信用ライブラリを統合サーバー側にもインストールする必要があります。これらを手順書（Walkthrough）に記載します。
> 3. ファイル名フォーマットは `satos_<動画タイトル等>-001-<1~3>.jpg` のような形式でクラウドサーバーへ送りますが、レポートの表示名もその名前の一部が利用されます。

## Proposed Changes

### satos

#### [MODIFY] [gmail_image_saver.py](file:///c:/Users/kapib/vscodegit/wild_animals/test2/satos/gmail_image_saver.py)
- 先ほどの `edge_server` 関連のプロパティやメソッドを `cloud_server` 向けにリネームおよび再実装。
- `import requests`, `from ultralytics import YOLO` の追加。
- YOLOモデルを用いた判定ロジックの実装。
- 3フレーム抽出ループ直後に判定を実施→Trueなら `requests.post(files=...)` を利用してクラウドへ転送するように修正。

#### [MODIFY] [.env](file:///c:/Users/kapib/vscodegit/wild_animals/test2/satos/.env)
- `# Edge Server Configuration` のコメントを消し `# Cloud Server Integration` 用のURL変数に変更。

## Verification Plan

### 自動・手動テスト
- 対象サーバーで `pip install ultralytics requests` などを済ませ、実行。
- メールを受信し、動物や人間が映った動画からフレームが抽出された際、`YOLO`による推論ログが正常に出力されるかテスト（ユーザー側に実行を依頼）。
- 判定結果がTrueのときのみ、クラウドサーバーへ `POST` 通信が行われ、クラウド側で集約→レポートメール送信のプロセスが発火することの確認。
