# ダークモード実装計画 (トグルボタン追加版)

Web画面上のボタンで手動でライト/ダークを切り替えられるようにしたいというご要望に合わせ、実装方針を更新しました。

## 🎯 目的とアプローチ
CSSのメディアクエリ (`prefers-color-scheme`) だけで自動判定していた状態から、**JavaScriptを用いた状態管理とトグルボタン**による手動切り替え方式に変更します。切り替え状態はブラウザの `localStorage` に保存され、ページ遷移時や再訪問時にも維持されます。

## 🛠️ Proposed Changes

### 1. 共通トグルスクリプト・UIの追加
`server.py` 内で各画面を生成する前に、以下の共通HTML/JSスニペットを変数として定義し、4つの画面すべてに注入します。

- **Theme Toggle Script**: `<head>` タグ内に配置し、画面描画前に `localStorage` の状態（あるいはOSのデフォルト状態）を読み取って `<html>` 要素に `data-theme="dark"` などの属性を付与します。（画面のチラつきを防止します）
- **Toggle Button**: 太陽(☀️)と月(🌙)のアイコンを持つシンプルなフローティングボタン（画面の右下などを想定）や、各画面のヘッダー部分に切り替えボタンを追加します。クリック時に `localStorage` を更新し、`data-theme` を切り替えます。

### 2. CSSの書き換え
前回追加した `@media (prefers-color-scheme: dark) { ... }` の部分を、`[data-theme="dark"] { ... }` をベースとするスタイルに変更します。

#### [MODIFY] [server.py](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py)
以下の4つのエンドポイント（およびHTML文字列生成箇所）を修正します。
- **Event Detail**: 1485行目付近
- **Login**: 1768行目付近
- **Admin Settings**: 1845行目付近
- **Gallery**: 2669行目付近

**具体的な変更作業**:
1. `server.py` の上部に `THEME_TOGGLE_SCRIPT` および `THEME_TOGGLE_BUTTON` の文字列定数を定義します。
2. 各エンドポイントのHTMLの `<head>` に `THEME_TOGGLE_SCRIPT` を、`<body>` 内に `THEME_TOGGLE_BUTTON` を埋め込みます。
3. すでに追記した `@media (prefers-color-scheme: dark)` を `[data-theme="dark"] body` など、属性セレクタを利用したスタイルに一括置換します。

## 📝 User Review Required

- **ボタンの配置**: 画面の右下などに固定で浮いている「フローティングボタン」にするか、それとも画面の上部バー（Backボタン等の横）に配置するか、どちらがよろしいでしょうか？（全画面共通で手軽に実装・配置できるのはフローティングボタンです）

## ✅ Verification Plan
1. ローカルでサーバを起動します。
2. 各画面にアクセスし、トグルボタンが表示されていることを確認します。
3. ボタンをクリックすると、ライト/ダークが即座に切り替わることを確認します。
4. ページをリロードしたり、他の画面（GalleryからAdmin等）へ遷移しても、切り替えたテーマが維持されることを確認します。
