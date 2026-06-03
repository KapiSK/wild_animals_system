# サイクル削除機能の実装タスク

- `[x]` `statistics.csv` マイグレーション機能の追加
  - `[x]` サーバー起動時に古いCSVをチェック
  - `[x]` `EVENT_METADATA_DIR` の JSON と突き合わせて `cycle_id` を補完・再構築
- `[x]` 画像アップロード完了時（サイクル確定時）の `statistics.csv` 書き込み処理を6列に変更
- `[x]` バックエンドAPI `DELETE /api/cycle/{camera_id}/{cycle_id}` の追加
  - `[x]` 権限チェック（`role == "admin"`）
  - `[x]` 画像・動画・JSONファイルの物理削除
  - `[x]` `statistics.csv` から該当行を削除
  - `[x]` `server_sequence.json` の巻き戻し処理（最新サイクルだった場合）
- `[x]` フロントエンドの改修
  - `[x]` `isAdmin` をギャラリーのJSに注入
  - `[x]` ギャラリーの各サイクルヘッダーにゴミ箱（🗑️）アイコンを追加
  - `[x]` 2段階 `confirm` を使った削除リクエストの送信（JS関数 `deleteCycle`）
  - `[x]` 削除後の画面リロード
- `[x]` テスト・動作検証
- `[x]` ウォークスルー (`walkthrough.md`) の作成
