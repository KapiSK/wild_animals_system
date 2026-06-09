# タスクリスト: 削除機能 (Safe Delete) の堅牢化

- [x] `server.py`: `delete_cycle` 内の `os.listdir` を廃止し、メタデータ(`event_metadata.json`)主導の削除ロジックへ変更
- [x] `server.py`: 画像ファイル（`UPLOAD_DIR`, `PROCESSED_DIR`）のピンポイント削除処理の実装
- [x] `server.py`: 動画ファイル（`VIDEO_DIR`）のピンポイント削除処理の実装
- [x] `server.py`: 各ファイルの `os.remove` に対する `try-except` 保護の追加
- [x] 動作確認: サーバーを再起動してシンタックスチェックを行う
