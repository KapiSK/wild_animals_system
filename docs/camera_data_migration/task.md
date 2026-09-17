# Camera Data Migration Tasks

- [x] `server.py` への API エンドポイント (`POST /api/admin/migrate_camera`) の追加
    - [x] 移行対象ディレクトリ (`received_images`, `processed_images`, `received_videos`, `event_metadata`) の定義
    - [x] 指定日時以降のファイルを抽出するロジックの実装
    - [x] ファイルの移動・リネーム処理の実装
    - [x] `event_metadata` JSON 内部の ID 書き換え処理の実装
- [x] Admin 画面への UI 追加
    - [x] `server.py` の HTML レスポンス (Admin ページ) へのセクション追加
    - [x] 移行実行のためのフロントエンド (JavaScript, `fetch`) 実装
- [ ] テスト・検証
    - [ ] テスト用ディレクトリ・ファイルでの移行動作確認
- [ ] `walkthrough.md` の作成
