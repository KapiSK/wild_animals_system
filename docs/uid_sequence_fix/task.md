# 統合サーバーのシーケンス番号（UID）対応タスク

- `[x]` 原因の特定（ファイル名重複時のリネーム `_1` による誤抽出）
- `[x]` `gmail_image_saver.py` の `_process_message` にて、キューに `uid` を追加
- `[x]` `_worker_loop` にて、キューから `uid` を受け取るように変更
- `[x]` `_extract_frames` に `uid` 引数を追加
- `[x]` `_upload_to_cloud_server` に `uid` 引数を追加し、`seq` として使用するように変更
- `[x]` `_upload_to_cloud_server` のファイル名抽出処理で、`_1` などのサフィックスを無視するよう改善
- `[x]` 実装のテスト/検証
- `[x]` 修正内容の walkthrough ドキュメント作成
