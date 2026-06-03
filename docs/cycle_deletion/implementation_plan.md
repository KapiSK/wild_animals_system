# サイクル削除機能 ＋ 統計データ(CSV)への cycle_id 追加 実装計画

先ほどのサイクル削除機能に加えて、ご指摘の通り「統計データ（`statistics.csv`）からの該当レコード削除」と、根本的な改善である「`statistics.csv` への `cycle_id` 列の追加」も合わせて実装します。

## Proposed Changes

### `original_server/server.py`

#### 1. `statistics.csv` への `cycle_id` 追加（マイグレーション処理）
- 現在 `statistics.csv` は `timestamp,camera_id,temperature,labels,target_count` の5列で記録されています。
- ここに `cycle_id` を追加し、6列のデータとします。
- **後方互換性（既存データの補完）**: サーバー起動時（または初回アクセス時）に既存の `statistics.csv` のヘッダーを確認します。もし `cycle_id` が存在しない古いフォーマットだった場合、`EVENT_METADATA_DIR` に保存されている各サイクルのJSONファイルと `timestamp`（`cycle_time`）を突き合わせて `cycle_id` を割り出し、新しい6列のフォーマットとして `statistics.csv` を再構築（マイグレーション）する処理を追加します。

#### 2. 画像アップロード時の CSV 書き込み修正
- 新しくサイクルが完了した際に `statistics.csv` へ行を追記する処理（`check_and_finalize_cycles`内）において、`cycle_id` も含めて書き込むように変更します。

#### 3. バックエンド: 削除用APIの追加 (`DELETE /api/cycle/{camera_id}/{cycle_id}`)
- 権限チェック（`principal.get("role") == "admin"`）を実施。
- 以下のファイルを物理削除:
  - `UPLOAD_DIR`（オリジナル画像）
  - `PROCESSED_DIR`（推論済み画像）
  - `VIDEO_DIR`（受信動画）
  - `EVENT_METADATA_DIR`（JSONメタデータ）
- **統計データからの削除**: `statistics.csv` を読み込み、対象の `camera_id` と `cycle_id` が一致する行を除外した上で、CSVを上書き保存します。
- **シーケンス番号の巻き戻し**: 削除対象の `cycle_id` が最新シーケンスであった場合、`server_sequence.json` の `current_server_seq` を1つ減らし、`last_edge_event_id` をリセットして、次回受信時に同じシーケンス番号を再利用するようにします。

#### 4. フロントエンド: ギャラリーUIの追加
- ギャラリーの各サイクルのヘッダー部分に、管理者（`isAdmin` が true の場合）のみゴミ箱（🗑️）ボタンを表示します。
- ゴミ箱ボタンを押した際、2段階の確認（`confirm`）ダイアログを表示します。
  1. 「本当にこのサイクルを削除しますか？」
  2. 「【最終確認】すべての画像・動画・メタデータおよび統計情報が削除されます。よろしいですか？」
- 両方でOKが押された場合のみ、削除APIを呼び出し、成功後にギャラリーと統計情報をリロードします。

## User Review Required

- 既存の `statistics.csv` を一度作り直す（JSONファイルと突き合わせて `cycle_id` を補完する）処理が入りますが、過去データが多い場合でもサーバー起動時のみの処理なので負荷は軽微です。この方針で問題ないでしょうか？
- 削除時は、JSON、画像、動画だけでなく `statistics.csv` の該当行も同時に削除されるため、統計ダッシュボードのグラフからもそのイベントの集計が完全に消えることになります。
- 上記の計画で問題なければ、実装に進みます！
