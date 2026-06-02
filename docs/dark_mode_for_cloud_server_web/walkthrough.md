# ダークモード実装のウォークスルー (トグルボタン対応版)

クラウドサーバ（`original_server`）の各Web画面に対して、手動でライト/ダークを切り替えられるフローティングトグルボタン機能を追加しました。

## 変更内容

各画面で OS の設定に自動追従するのみだったダークモード機能を、**「手動で切り替えられ、その設定が `localStorage` によって全画面で保持される」** 仕様にアップグレードしました。

### 1. 共通スクリプト・UIの追加 (`server.py`)
`server.py` の上部に、全画面で共通利用する2つの定数を追加しました。
- `THEME_TOGGLE_SCRIPT`: ページ描画前に `localStorage` の保存状態（またはOS設定）を読み取り、`<html>` に `data-theme="dark"` を付与する処理。
- `THEME_TOGGLE_UI`: 画面右下に固定配置されるフローティングボタン（☀️ / 🌙 アイコン）とそのクリックイベントのJSロジック。クリック時に `data-theme` を切り替え、`localStorage` に状態を保存します。

### 2. 各画面の HTML/CSS の書き換え
以下の4つの画面に対して、共通スクリプトとUIを埋め込み、CSSの適用条件を変更しました。
- [Event Detail 画面](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py#L1525)
- [Login 画面](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py#L1817)
- [Admin Settings 画面](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py#L1904)
- [Gallery 画面](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py#L2756)

**CSSの変更点**:
前回追加した `@media (prefers-color-scheme: dark)` をすべて、`[data-theme="dark"]` を起点とする属性セレクタ（例: `[data-theme="dark"] body`）に置き換えました。

## 確認結果

- Pythonの構文チェック (`python -m py_compile server.py`) にてエラーがないことを確認しました。
- ブラウザで画面右下に表示されるボタンをクリックすることで、シームレスにテーマが切り替わります。
- 一度切り替えたテーマは、他画面（例：GalleryからEventへ）に遷移しても `localStorage` により維持されます。
