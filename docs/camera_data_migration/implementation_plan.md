# カメラデータ・マイグレーション機能 実装計画 (Camera Data Migration)

現地でのカメラ設置場所変更に伴い、クラウド側で意図せず元のカメラIDのまま保存されてしまった画像やイベントデータを、指定した日時以降について一括で新しいカメラIDへ移行（リネーム・移動）する機能を追加します。

## User Review Required

> [!IMPORTANT]
> この機能は、サーバー上のファイルを直接操作（移動およびリネーム）します。実行前にバックアップ等の運用を考慮してください。
> UIは、管理者権限を持つユーザーがアクセスする Admin ページ (`/admin`) 内に追加することを想定しています。

## Open Questions

> [!WARNING]
> 1. **日時の指定方法**: ファイルを移行する基準となる日時（例：「2026年9月17日 12:00 以降」）は、ファイル名に含まれるタイムスタンプで判定しますか？それともファイルの作成日時（OSレベル）を使用しますか？（※今回は確実性のため、ファイル名に含まれる `YYYYMMDDHHMMSS` の解析とOSタイムスタンプの併用を想定しています）
> 2. **対象ディレクトリ**: `received_images`, `processed_images`, `received_videos`, `event_metadata` の4つのディレクトリを対象として移行処理を行いますが、他に対象とすべきディレクトリはありますか？

## Proposed Changes

### original_server (Cloud Server Backend)

バックエンドの `server.py` に、データ移行のための専用エンドポイントを追加し、ファイル操作の実装を行います。

#### [MODIFY] [server.py](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py)
- **APIエンドポイントの追加**: `POST /api/admin/migrate_camera` を新設（Admin権限必須）。
- **パラメータ**:
  - `source_camera_id`: 移行元のID (例: `CAM_01`)
  - `dest_camera_id`: 移行先のID (例: `CAM_02`)
  - `start_datetime`: 移行対象とする開始日時（ISO8601等）
- **移行ロジックの追加**:
  1. `received_images`, `processed_images`, `received_videos`, `event_metadata` の各ディレクトリで `source_camera_id` フォルダを走査。
  2. 該当ファイル名からタイムスタンプを抽出（またはOSの更新日時を取得）し、指定日時以降であれば対象とする。
  3. `dest_camera_id` のディレクトリへファイルを移動。
  4. ファイル名に `source_camera_id` が含まれる場合、それを `dest_camera_id` に置換（例: `CAM_01_2026...jpg` -> `CAM_02_2026...jpg`）。
  5. JSONメタデータ（`event_metadata`内）の場合、内部の `"camera_id"` や参照パスも更新して保存。

### original_server (Admin Frontend)

管理者用画面にデータ移行を行うためのUIを追加します。

#### [MODIFY] [server.py (Admin HTML部)](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py)
- `/admin` のHTMLレスポンス内に「Camera Data Migration（カメラデータ移行）」セクションを追加。
- 入力フォーム（Source ID, Destination ID, Start Date & Time）と「Migrate」ボタンを配置。
- `fetch` APIを用いて非同期に `POST /api/admin/migrate_camera` を呼び出し、結果をアラート表示するJavaScript処理を追加。

## Verification Plan

### Manual Verification
1. クラウドサーバーをテスト環境で起動。
2. テスト用に、過去日時と現在日時のファイルを持つ `CAM_TEST1` ディレクトリを意図的に作成。
3. `/admin` にアクセスし、「Migrate Data」機能を用いて `CAM_TEST1` から `CAM_TEST2` へ、現在日時以降のデータのみ移行するよう実行。
4. `CAM_TEST2` ディレクトリが生成され、指定日時以降の画像ファイルやメタデータが正しく移動・リネームされていることを確認。
5. 古い日時のファイルは `CAM_TEST1` に残ったままであることを確認。
