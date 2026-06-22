# クラウドサーバ：カメラごとのメール送信設定機能の追加

特定のカメラからの画像のみをメール送信し、それ以外のカメラからは送信しないようにするための設定をWeb上（Admin画面）から行えるようにします。

## 背景と目的
現在、`original_server` はカメラごとに送信先メーリングリストを設定する機能を持ちますが、設定がない場合は環境変数（`RECIPIENT_EMAIL`）へフォールバックして一律でメールが送信される仕様です。このため「このカメラからはメールを送らない」という設定ができませんでした。
本実装により、Camera Alert 設定において「送信しない (Do Not Send)」という選択肢を追加し、不要なメール通知を停止できるようにします。

## User Review Required

> [!IMPORTANT]
> 「送信しない」設定を表す内部識別子として `__NONE__` という文字列を使用します。設定ファイル（`camera_alert_config.json`）にはこの文字列が保存されます。
> UI上では「送信しない (Do Not Send)」として表示されます。

## Proposed Changes

### original_server

#### [MODIFY] [server.py](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py)
1. **バックエンド関数の改修**
   - `get_recipients_for_camera` 関数を修正し、カメラのアラート設定が `"__NONE__"` の場合は、フォールバックせずに特別なリスト `["__NONE__"]` を返すようにします。
   - `send_email` 関数を修正し、`recipients` の値が `["__NONE__"]` の場合はメール送信処理をスキップ（早期リターン）するようにします。

2. **フロントエンド（Admin Dashboard HTML）の改修**
   - `@app.get("/admin")` 内の `renderMapping()` JavaScript関数を修正し、メーリングリスト選択のプルダウンに「送信しない (Do Not Send)」の `<option>` を追加します。

## Verification Plan

### 自動/手動テスト
1. FastAPIサーバーを再起動し、`/admin` 画面にアクセスする。
2. Camera Alert 設定（メーリングリスト選択プルダウン）に「送信しない (Do Not Send)」が追加されていることを確認する。
3. 任意のカメラに対して「送信しない」を設定し、Save Changes が正常に行われるか確認する。
4. そのカメラから画像を受信した場合、`server.py` のログに `Email sending is disabled for this camera.` が出力され、メールが送信されないことを確認する。
