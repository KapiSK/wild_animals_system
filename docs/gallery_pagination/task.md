# Gallery Pagination Task List

- [x] `server.py` バックエンドの修正
  - [x] `/api/images` 内の `[:500]` によるハードリミットを撤廃
- [x] `server.py` フロントエンドのJS状態管理追加
  - [x] `flatPagination = { page: 1, limit: 10 }` （要望に合わせて10件スタート）
  - [x] `groupedPagination = {}` (カメラごとに `{ page: 1, limit: 10 }` を管理)
- [x] ページ切り替え用JS関数の追加
  - [x] `changeFlatPage(page)`, `changeFlatLimit(limit)`
  - [x] `changeGroupedPage(folder, page)`, `changeGroupedLimit(folder, limit)`
- [x] `renderGallery` の改修
  - [x] GroupedモードのHTML生成時に、サイクルの配列をスライスして表示
  - [x] Groupedモードの各カメラ折りたたみ内に、専用のページネーションUIを描画
  - [x] FlatモードのHTML生成時に、サイクルの配列をスライスして表示
  - [x] FlatモードのHTML生成時に、上部に全体のページネーションUIを描画
  - [x] Flatモードの各サイクル内に、動画プレイヤーを描画
- [ ] 動作確認
