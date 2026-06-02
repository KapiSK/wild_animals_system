# 統計データ収集機能実装タスク

- [x] `original_server/server.py` の `process_cycle` を修正
  - [x] `load_telemetry()` からカメラの `temperature` を取得
  - [x] `event_metadata` に `temperature` を追加保存
  - [x] `statistics.csv` に追記保存 (画像の撮影日時 `cycle_time` を使用)
- [x] 動作確認 (Python構文チェックとテスト)
- [x] `walkthrough.md` の作成
