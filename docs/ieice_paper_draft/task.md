# 論文執筆タスク

- [x] 作業用ディレクトリ `docs/ieice_paper_draft` の作成とファイルのコピー
- [x] テンプレートファイル (`main.tex`) の作成と初期コンパイル確認
- [x] 論文構成案 (Implementation Plan) の作成
- [x] タイトル・著者情報の決定
  - [x] タイトル更新
  - [x] 著者名更新
  - [x] 所属情報更新
- [x] 本文の執筆
  - [x] まえがき (Introduction)
  - [x] 提案システム (Proposed System)
  - [x] 実装 (Implementation)
  - [x] 実験と評価 (Evaluation)
  - [x] むすび (Conclusion)
- [x] 教授指摘事項への対応 (参考文献・コスト比較方針変更・電力収支)

## 実験データの反映（指定データへの書き換え）

- [x] **評価項目の再構築**
  - [x] **部品構成表 (Component Configuration)** の追加
  - [x] **消費電力評価 (Voltage & Current)** の形式変更
    - [x] エッジカメラ (Voltage, Current, Power)
    - [x] エッジサーバ (Voltage, Current, Power)
  - [x] **AI検知精度の定義変更**
    - [x] Ground Truth = MegaDetector
    - [x] 指標: 精度(Accuracy), 過検出率(Over-detection Rate), 再現率(Recall)
  - [x] **データ削減効果**
    - [x] 通信削減率 (Communication Reduction Rate)
  - [x] **システム処理時間 (System Processing Time)**
    - [x] 検知〜通知までの遅延時間 (Latency)
- [/] **フロー図の反映** (Updated)
  - [x] `main.tex` の図参照を更新 (Edge Camera, Edge Server, System Flow)
  - [x] 画像ファイルの配置とコンパイル
  - [x] **図の統合** (System Flowのみにする)
- [/] **数値データの埋め込み**
  - [ ] ユーザーから提供された値、または測定値を記入
  - [ ] **主張（通信コスト削減・労力軽減）に合わせた強調**
- [/] **記述の推敲** (In Progress)
  - [x] 用語統一 (サーバー -> サーバ)
  - [x] 表現の学術的修正 (User -> Operator, Payment -> Cost)
  - [x] 図表配置の最適化
- [x] 最終コンパイルとプレビュー確認
