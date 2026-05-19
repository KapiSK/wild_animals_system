# Gallery UI Optimization Task List

- [ ] `server.py` の改修
  - [ ] 画像カード（`renderImageCard`）のリンクを廃止し、`openOverlay`（モーダル）表示へ変更
  - [ ] すべての `<img>` に `loading="lazy" decoding="async"` を付与
  - [ ] 一覧画面（`renderGallery`）にオーバーレイ用HTMLとJS制御関数を追加
  - [ ] サイクルごとの動画を一覧画面に組み込み、`preload="none"` と `poster` を設定
  - [ ] 初期データの画像読み込み件数を500件程度に制限（APIまたはフロント側でフィルタ）
  - [ ] 不要になった `/event/...` エンドポイントを削除
- [ ] 動作確認（手動）
  - [ ] 一覧ページの爆速表示
  - [ ] オーバーレイ機能の動作
  - [ ] 動画の再生動作
