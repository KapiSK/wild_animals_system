
# Implementation Plan - 関連研究セクションの追加

## Goal Description

論文「鳥獣害対策のための複数台カメラを用いた低コスト通信型警戒システムの開発」に、最新の関連研究（5件）を引用した「関連研究」セクションを追加する。
これにより、提案手法の優位性（低コスト、省電力、面的な監視）を明確にする。
また、参考文献管理を `thebibliography` 環境から BibTeX (`refs.bib`) に移行し、管理を効率化する。

## User Review Required
>
> [!IMPORTANT]
> 既存の `\begin{thebibliography}` ブロックは削除され、`\bibliography{refs}` に置き換えられます。既存の `\bibitem{maff}` (農林水産省のレポート) も `refs.bib` に移行します。

## Proposed Changes

### docs/ieice_paper_draft

#### [NEW] [refs.bib](file:///c:/Users/kapib/vscodegit/wild_animals/test2/docs/ieice_paper_draft/refs.bib)

以下の5件＋既存1件の文献情報を含むBibTeXファイルを作成する。

1. **[SMC2024]** Semba et al., "A Battery-Powered Wild Animal Tracking Device..."
2. **[IEICE2020]** Saito et al., "Battery-Powered Wild Animal Detection Nodes..."
3. **[Computers2025]** Rahman et al., "Smart Wildlife Monitoring..."
4. **[ArXiv2025]** Adhikari et al., "A Comprehensive Evaluation of YOLO-based Deer Detection..."
5. **[RSSJ2016]** Oishi, "The Use of Remote Sensing..."
6. **[MAFF]** 農林水産省レポート (既存)

#### [MODIFY] [main.tex](file:///c:/Users/kapib/vscodegit/wild_animals/test2/docs/ieice_paper_draft/main.tex)

- `\section{まえがき}` の後に `\section{関連研究}` を追加。
- 「既存研究（高機能・高コスト、あるいは単体デバイス）と本提案（低コスト・複数台連携）の対比」を中心に記述。
- 末尾の `\begin{thebibliography}` を削除し、`\bibliographystyle{sieicej}` および `\bibliography{refs}` を有効化。

## Verification Plan

### Automated Tests

- `platex` および `pbibtex` を実行し、コンパイルエラーが出ないことを確認する。

    ```bash
    cd docs/ieice_paper_draft
    platex main
    pbibtex main
    platex main
    platex main
    ```

- 生成された `main.pdf` (あるいはDVI) で、関連研究セクションが正しく表示され、引用番号が [1] 等となっていることを確認する（ログ確認）。

### Manual Verification

- `refs.bib` の内容が正しいか目視確認する。
