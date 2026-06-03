# サイクル削除機能 ＆ statistics.csv の拡張 実装完了

管理者権限でギャラリーから特定のサイクル（画像、動画、メタデータ、統計情報）を完全に削除する機能と、その準備として `statistics.csv` に `cycle_id` を含める改修を完了しました。

## 変更内容 (Changes Made)

### 1. `statistics.csv` のマイグレーション処理
- `original_server/server.py` の起動時に `migrate_statistics_csv()` 関数を実行するようにしました。
- 既存の `statistics.csv` が5列（`timestamp,camera_id,temperature,labels,target_count`）の場合、`EVENT_METADATA_DIR` 内のJSONファイルをスキャンし、`cycle_time` と `event_id` (cycle_id) を紐付けて、6列目（実際には2列目）に `cycle_id` を挿入した新しいCSVに書き換える（マイグレーションする）処理を自動で行います。

### 2. サイクル確定時の書き込み更新
- 動画等の処理が終わり、サイクルが確定してCSVに追記される際（`check_and_finalize_cycles`内）にも、新たに `cycle_id` を含めた6列のフォーマットでデータを保存するように修正しました。

### 3. `DELETE /api/cycle/{camera_id}/{cycle_id}` エンドポイントの追加
- 管理者権限（`role == "admin"`）でのみ実行可能な削除APIを新設しました。
- このAPIは以下を順に実行します：
  1. `UPLOAD_DIR`（オリジナル画像）、`PROCESSED_DIR`（推論画像）、`VIDEO_DIR`（動画）、`EVENT_METADATA_DIR`（JSON）の物理ファイルを検索し削除。
  2. `statistics.csv` を読み込み、削除対象の `camera_id` と `cycle_id` に合致する行を除外して上書き保存。
  3. `server_sequence.json` を確認し、削除したサイクルがそのカメラの「最新」であった場合、シーケンス（`current_server_seq`）を1つ減らして巻き戻し、次のアップロード時に同じ番号を使えるようにリセット。

### 4. ギャラリーUIの更新
- `server.py` 内で生成するHTMLに `isAdmin` フラグを注入し、管理者アカウントでログインしている場合のみ以下のUIを表示するようにしました。
- グループビュー、およびフラットビューの各サイクルヘッダー右側に「🗑️ (ゴミ箱)」アイコンが表示されます。
- アイコンをクリックすると、誤操作を防ぐために2段階の `confirm`（確認ダイアログ）が表示され、両方で「OK」を押すと削除処理が実行されます。
- 削除完了後は自動的に画面がリロードされ、ギャラリーと統計データから該当のサイクルが消去されます。

## 検証手順 (Verification)

1. `original_server` サーバーを再起動してください。
2. 起動時のログに `Migrating statistics.csv to include cycle_id...` と表示され、成功すると `Successfully migrated statistics.csv` と出力されます（既に移行済みの場合はスキップされます）。
3. 管理者アカウント（`admin`）で `/gallery` にアクセスしてください。
4. 各サイクルのタイトル右側に 🗑️ アイコンが表示されていることを確認します。
5. テスト用の不要なサイクルで 🗑️ をクリックし、2段階の確認を通過させてください。
6. 以下が正常に行われたことを確認してください：
   - 画面がリロードされ、そのサイクルがギャラリーから消えていること。
   - `statistics.csv` から該当行が消えていること（統計ダッシュボードに反映されなくなっていること）。
   - 最新サイクルを削除した場合、次にカメラから送られてきたデータが「削除したサイクルと同じ番号」として再採番されること。
