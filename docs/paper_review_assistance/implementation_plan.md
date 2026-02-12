# 論文修正計画 (Implementation Plan)

## 目標

IEICE技術研究報告（または論文）のドラフト (`docs/ieice_paper_draft/main.tex`) を完成させる。具体的には、未定の実験データを埋め、論理構成と日本語表現を推敲する。

## ユーザーレビューが必要な事項

- **実験データのソース**: 過去のログから抽出するか、ユーザーが提供するか。
- **執筆の方向性**: 「通信コスト削減」と「誤検知削減」のどちらを主軸にするかの最終確認（現状は両立）。

## 提案される変更

### `docs/ieice_paper_draft/`

#### [MODIFY] [main.tex](file:///c:/Users/kapib/vscodegit/wild_animals/test2/docs/ieice_paper_draft/main.tex)

- **データ補完**:
  - `Table 2` (Camera Power): 消費電力の実測値を記入。
  - `Table 3` (Comm Perf): 通信距離ごとの成功率・時間を記入。
  - `Table 4` (Latency): 各処理ステップの時間を記入。
  - `Table 5` (Server Power): Pi 4の消費電力を記入。
  - `Table 7` (Cloud Perf): 外部サーバの統計を記入。
- **テキスト修正**:
  - アブストラクトの具体化（数値が入った後）。
  - 「まえがき」の論理展開の微修正。
  - 誤字脱字、表記ゆれの修正。

## 検証計画

### 自動テスト

- LaTeXコンパイル (`latexmk` 等) を実行し、エラーがないことを確認する。
- 生成されたPDF（テキスト抽出）を確認し、`XXX` が残っていないかチェックする。

### 手動検証

- ユーザーによる査読。
- 論理構成の整合性確認。
