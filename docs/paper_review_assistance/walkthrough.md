# 論文修正・コンパイル完了報告 (Walkthrough)

## 実施した変更

`docs/ieice_paper_draft/main.tex` および関連ファイルに対して、以下の修正を行いました。

### 1. 参考文献 (main.bbl) の作成と適用

`pbibtex`/`upbibtex` の動作不具合を回避するため、`refs.bib` の内容に基づき `main.bbl` を手動で作成しました。
`uplatex` を2回実行することで相互参照を解決し、PDFに参考文献が正しく表示されることを確認しました。

### 2. システム処理時間 (Table 4) の更新

ご提供いただいた `エッジカメラ処理時間.csv` と `エッジサーバー処理時間.csv` から平均値を算出し、表に反映しました。

```latex
  Camera Capture & 3105 \\
  Wi-Fi Transmission & 7991 \\
  Edge Server Inference & 3241 \\
  Cloud Notification & 7651 \\
  \textbf{Total Latency} & \textbf{21988} \\
```

### 3. 通信性能 (Table 3) の修正

近距離での実測値に基づき、表の形式を修正して値を記入しました。

```latex
  距離 (m) & 送信所要時間 (ms) & エラー率 (\%) \\
  \hline \hline
  \approx 1 & 7991 & 0.0 \\
```

## 検証結果

### コンパイル確認

以下の手順で正常にコンパイルが完了しました。

1. `main.bbl` を手動作成（以前のプロセスによる破損を修復）
2. `uplatex -kanji=utf8 -interaction=nonstopmode main.tex` (1回目: ラベル抽出)
3. `uplatex -kanji=utf8 -interaction=nonstopmode main.tex` (2回目: 相互参照解決)
4. `dvipdfmx main.dvi`

- **Status**: Success
- **Output**: `main.pdf` (約 274 KB, 参考文献含む)

### 残存課題

以下のデータは引き続き未入力 (XXX) です。

- エッジカメラの消費電力詳細 (Active, Wi-Fi Tx)
- エッジサーバの消費電力詳細 (Pi 4)
- 外部サーバの評価指標

## 変更履歴

render_diffs(file:///c:/Users/kapib/vscodegit/wild_animals/test2/docs/ieice_paper_draft/main.tex)
