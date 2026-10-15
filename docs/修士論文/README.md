# 修士論文のLaTeXひな形

題目：**獣害対策トレイルカメラシステムに関する研究**

`修士論文_長澤_final.pdf` を体裁の参考として作成した原稿です。第2章「前提知識」と第3章「関連研究」はICOIACT論文原稿と追加文献を基に本文を記述し，第4章「提案システムの設計と実装」は原稿で確認できる構成と処理を記述しています。第4章の未確定仕様には灰色の記入案内を残し，その他の章は章立てと記入案内の段階です。提出用の完成原稿ではありません。執筆元と確認事項は [source_notes.md](source_notes.md) を参照してください。

## 体裁

- A4縦，11pt，1カラム，片面。LuaLaTeXの日本語文書クラス `ltjsreport` を使用。
- 和文は明朝体，見出しはゴシック体。上・下余白30mm，左右26mm。
- 参考PDFのように，表紙は題目を枠で囲み，指導教員・提出年月・提出者を配置。
- 表紙と概要はページ番号なし。目次・図目次・表目次はローマ数字，本文以降は算用数字。ページ番号は右上。
- 章の開始時に改ページし，章・節・項の3階層を使用。図・表・数式は章ごとの番号。

余白やフォントサイズは参考PDFの外観に合わせた設定であり，大学の正式な提出規定を確認したものではありません。大学ロゴは複製していません。所属・氏名・年度などはすべて記入欄にしています。

## 構成

1. 序論
2. 前提知識
3. 関連研究
4. 提案システムの設計と実装
5. 実験評価
6. 考察
7. 結論

前付け：表紙，概要，目次，図目次，表目次。
後付け：謝辞，参考文献，付録「実験条件と補足資料」。

第2章はトレイルカメラ，画像認識，マイコンとシングルボードコンピュータ，Wi-Fi HaLowの4節で構成します。第3章には関連研究との比較表，第4章には構成図と主要機器の一覧表を挿入しています。図表に `\caption{...}` を付けると，ビルド時に図目次・表目次へ自動登録されます。

## 編集するファイル

| ファイル | 編集内容 |
| --- | --- |
| `main.tex` | 全体の読み込み順，章・付録の追加や削除 |
| `metadata.tex` | 題目，年度，提出年月，所属，指導教員，学籍番号，氏名 |
| `preamble.tex` | 余白，文字サイズ以外の共通書式，ページ番号，記入案内の表示 |
| `frontmatter/abstract.tex` | 概要 |
| `chapters/01_*.tex` ～ `07_*.tex` | 各章の本文 |
| `backmatter/*.tex` | 謝辞，参考文献，付録 |

灰色の `\writehere{...}` は執筆のための案内です。執筆時は命令全体を本文に置き換えてください。未記入箇所は `rg -n 'writehere|［' --glob '*.tex'` で探せます。

## PDFを作る（Windows）

TeX LiveでLuaLaTeX，LuaTeX-ja，原ノ味フォントと，`preamble.tex` に記載したパッケージが利用できる環境を用意します。文字コードはUTF-8です。外部画像，BibTeX，Python，ネットワーク接続はビルドには不要です。

リポジトリのルートから実行します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "docs\修士論文\build.ps1"
```

3回コンパイルして目次と参照を確定し，このディレクトリに `main.pdf` を生成します。中間生成物・コンパイルログ・フォントキャッシュは `out/` に保存します。初回はフォントキャッシュの作成に時間がかかります。エラー時は `out/compile-pass-*.txt` と `out/main.log` を確認してください。

スクリプトを使わない場合は，このディレクトリを作業ディレクトリとして次のコマンドを3回実行します。Overleafでは `main.tex` をメイン文書，コンパイラをLuaLaTeXに設定します。

```text
lualatex -interaction=nonstopmode -halt-on-error main.tex
```

## 図・表・数式の記述例

以下は書き方の例です。ひな形の本文には挿入していません。

```latex
\begin{figure}[tbp]
  \centering
  \includegraphics[width=0.85\linewidth]{figures/system.pdf}
  \caption{システム全体構成}
  \label{fig:system}
\end{figure}
図\ref{fig:system}に全体構成を示す．

\begin{table}[tbp]
  \centering
  \caption{実験条件}
  \label{tab:conditions}
  \begin{tabularx}{\linewidth}{lX}
    \toprule
    項目 & 条件 \\
    \midrule
    撮影期間 & ［実際の期間］ \\
    \bottomrule
  \end{tabularx}
\end{table}

\begin{equation}
  P = \frac{\mathrm{TP}}{\mathrm{TP}+\mathrm{FP}}
  \label{eq:precision}
\end{equation}
```

図ファイルは必要になった時点で `figures/` を作って配置してください。

## 参考文献を追加する

`backmatter/references.tex` の既存の `thebibliography` 環境内に `\bibitem{reference-key}` を追加し，本文から `\cite{reference-key}` で引用します。以下は環境全体の記述例です。著者名などは実際に確認した書誌情報に置き換えてください。本文中の `\cite` のない文献を自動的に除く仕組みではないため，引用との対応と掲載順を確認してください。

```latex
\begin{thebibliography}{99}
  % ltjsreportでは参考文献の目次登録は自動．
  \bibitem{reference-key}
    著者名，``論文名，'' 掲載誌名，巻，号，ページ，年．
\end{thebibliography}
```

本ひな形は書誌ツールを必須にしていません。文献が増えた段階でBibTeX等へ移行できます。
