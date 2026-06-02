# クラウドサーバWeb画面へのダークモード実装計画

クラウドサーバ(`original_server/server.py`)内で生成されているHTMLにダークモードの対応を追加します。

## 🎯 目的とアプローチ
現在、`original_server/server.py` 内の以下の4つのエンドポイントでHTML画面が提供されています。
- **Event Detail**: `/event/{camera_id}/{event_id}`
- **Login**: `/login`
- **Admin Settings**: `/admin`
- **Gallery**: `/gallery`

これらの画面は、それぞれ直接 `server.py` 内にインラインの `<style>` でCSSが記述されています。
今回のアプローチとしては、各画面の `<style>` に `@media (prefers-color-scheme: dark)` を追加し、OSやブラウザのダークモード設定に合わせて自動で切り替わる「ネイティブ対応」なダークモードを実装します。

> [!TIP]
> トグルスイッチ（画面上のボタンによる手動切り替え）を設けることも可能ですが、JavaScriptやCookie等での状態管理が必要になり複雑化するため、まずは設定不要でOS連動する手法（CSSメディアクエリ）を推奨します。

## 📝 User Review Required

1. **トグルスイッチの要否**: 今回の提案は「OS設定に自動追従するダークモード」ですが、画面上に「ライト/ダーク手動切り替えボタン」を配置したいご要望はございますでしょうか？（手動切り替えを実装する場合、JavaScriptとlocalStorageを用いた状態管理を追加します。）
2. **デザインの方向性**: 現在のライトテーマ（白、薄い緑などのグラデーション）に対して、ダークモード時は「深緑・黒系のダークテーマ（Vercel等のモダンなダークUIに近いイメージ）」を想定していますが、指定のカラーコード等があればお知らせください。

## 🛠️ Proposed Changes

### 1. `server.py` の修正
各エンドポイントのHTMLレスポンス生成部分 (`f"""..."""` 形式の文字列) に含まれる `<style>` ブロックの末尾に、ダークモード用のCSSオーバーライドを追記します。

#### [MODIFY] [server.py](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py)

1. **Event Detail 画面** (1485行目付近):
   - 背景色を黒緑系に変更
   - カード（パネル）の背景色をダークグレー系に変更
   - テキスト色を明るい色（白やライトグレー）に変更
   - ボタン（Back to Gallery等）のホバー色を調整

2. **Login 画面** (1768行目付近):
   - `linear-gradient` の背景を暗い色調に変更
   - ログインフォーム（カード）の背景色、枠線をダークテーマ用に調整
   - Inputフィールドの背景色と文字色を暗転対応

3. **Admin Settings 画面** (1845行目付近):
   - すでにCSS変数が使用されているため、`@media (prefers-color-scheme: dark)` 内で `--glass-bg`, `--primary`, `--text-main`, `--text-sub` 等の変数をダークモード向けの値に上書き
   - `linear-gradient` の背景も暗い色へ変更

4. **Gallery 画面** (2669行目付近):
   - 背景色 `#f2f7f4` を `#1a202c` のような暗い色に変更
   - タブやカード (`.item`, `.latest-item`) の背景を `#2d3748` のような色に変更
   - テキスト色、影（box-shadow）の調整

## ✅ Verification Plan

### Manual Verification
1. `original_server/setup_local_test.py` などを実行してローカルでサーバを起動します。
2. ブラウザから `http://localhost:8000/gallery` (または設定されたポート) にアクセスします。
3. OSの設定、またはブラウザの開発者ツールで「ダークモード (prefers-color-scheme: dark)」をエミュレートし、4つの画面すべてでダークモードが正しく、視認性良く適用されることを確認します。
