# データセット・エクスポート機能の再構築および拡張計画

先ほどの統計ページ削除に伴い失われた「Export Dataset」機能をギャラリー画面に統合し、さらにご要望の「動画ファイルの包含」に対応するための実装計画を提案いたします。

## User Review Required
> [!IMPORTANT]
> - 本計画ではエクスポート用UIを「Gallery（ギャラリー）」ページのヘッダーに配置します。
> - エクスポートされるZIPファイルに、対象イベントの**動画ファイル (.mp4)** も含まれるようにバックエンドAPIを改修します。
> これで要件を満たしているか、ご確認をお願いいたします。

## Proposed Changes

### original_server

#### [MODIFY] [server.py](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py)
1. **バックエンド改修 (`/api/export/download`)**:
   - 現在のZIP生成ロジックは「画像」と「メタデータ(JSON)」のみを対象としています。
   - 指定されたイベント(`cycle_id` / `event_id`)に関連する動画ファイル(`VIDEO_DIR` 配下の `.mp4`)が存在する場合、ZIP内の `videos/` ディレクトリにそれらを同梱するように修正します。
2. **フロントエンド移設 (`/gallery` のHTML)**:
   - ヘッダー領域の操作ボタン群（Top Actions等）に「📦 Export Dataset」ボタンを追加します。
   - 以前 `/statistics` に存在したエクスポート用モーダルUI（HTML/CSS）をギャラリーのHTMLに移植します。
   - モーダル制御およびプレビュー・ダウンロード実行用のJavaScript関数（`openExportModal`, `checkExportSize`, など）を統合します。

## Verification Plan

### Manual Verification
1. ブラウザから `/gallery` にアクセスし、「Export Dataset」ボタンが表示されることを確認。
2. モーダルを開き、カメラや期間・ラベルでフィルタリングし「Check Data Size」が正常に動作することを確認。
3. ダウンロードを実行し、取得した ZIP ファイル内に `images/`、`videos/`、および `md_results.json` が正しく格納されているかを目視確認。
