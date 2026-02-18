# IEICE論文コンパイル用プロンプト (AI指示用)

このプロジェクトのTeXファイルをコンパイルする際は、以下の点に注意してください。

## 1. 必須コマンド (UTF-8環境)

参考文献処理に `pbibtex` ではなく **`upbibtex`** を使用する必要があります。また、LaTeXエンジンは **`uplatex`** を使用してください。

### コンパイル手順

以下の順序でコマンドを実行してください。

```bash
# 1. 1回目のコンパイル (auxファイル生成)
uplatex -interaction=nonstopmode main.tex

# 2. 参考文献処理 (UTF-8対応の upbibtex を使用)
upbibtex main

# 3. 2回目のコンパイル (文献参照の反映)
uplatex -interaction=nonstopmode main.tex

# 4. 3回目のコンパイル (相互参照の解決)
uplatex -interaction=nonstopmode main.tex

# 5. PDF生成
dvipdfmx main
```

## 2. 環境変数 (PATH)

実行環境によっては `uplatex` や `upbibtex` にパスが通っていない場合があります。
その場合は、以下のパスを一時的に環境変数PATHに追加してください。

- **TeX Live 2025 (Windows)**: `C:\texlive\2025\bin\windows`

```powershell
# PowerShellでのパス追加例
$env:PATH = "C:\texlive\2025\bin\windows;" + $env:PATH
```

## 3. フォント設定

`newtxtext` / `newtxmath` パッケージが見つからないエラーが出る場合は、一時的に `mathptmx` に切り替えるか、当該パッケージをコメントアウトしてデフォルトフォントを使用するよう修正してください。

## 4. 文字コード

すべてのファイル (`main.tex`, `refs.bib` 等) は **UTF-8** で保存されています。Shift-JISとして処理しないよう注意してください。
