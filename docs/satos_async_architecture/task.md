# 非同期化リファクタリングタスク

- [x] `queue`, `threading` モジュールのインポート追加
- [x] `GmailMovProcessor` 初期化処理へのワーカーキューとスレッドの設定追加
- [x] バックグラウンド用の `_worker_loop` メソッドの実装（YOLO推論機能を含む安全な実行）
- [x] `run_forever` でのワーカースレッドの開始と終了待機の制御
- [x] `_process_message` および `_maybe_save_mov_part` の挙動変更（同期的な処理から、保存済みパスのキューへの追加への変更）
- [x] バックオフ・リトライ等のエラーハンドリングの強化
