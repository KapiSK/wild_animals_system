# Implementation Plan - 論文への実験データ反映 & 教授指摘事項の対応

本フェーズでは、論文執筆タスクにおいて未記入となっている実験データ（数値、表）を補完し、記述の精度を高めることを目的とします。
また、教授（AI）からの査読コメントに基づき、論理構成と説得力を強化します。

## Goal Description

論文ドラフト (`main.tex`) 内のプレースホルダー（`XXX`等）を、実際の実験データに置き換える。不足しているデータがある場合は、測定計画を立案するか、既存の推測値や参考値を提示する。
さらに、「低コスト」「実用性」の主張を裏付ける定量的な比較データを追加する。

## User Review Required

> [!IMPORTANT]
> **不足データの特定**
> 既存のディレクトリ探索で見つからないデータについては、ユーザーに追加測定を依頼する可能性があります。

> [!WARNING]
> **「低コスト」の定義**
> タイトルにある「低コスト」を証明するため、**コスト試算表（BOM比較 + ランニングコスト比較）** の追加が必須です。

## Proposed Changes

### docs/ieice_paper_draft

#### [MODIFY] [main.tex](file:///c:/Users/kapib/vscodegit/wild_animals/test2/docs/ieice_paper_draft/main.tex)

1. **4.1 エッジカメラの評価**
    - 消費電力・処理時間の実測値を記入。
    - `docs/esp_processing_time` 等のディレクトリを調査。

2. **4.2 通信性能の評価**
    - 通信距離ごとの送信時間・エラー率を記入。
    - `docs/metrics_proposal` 等に関連データがないか確認。

3. **4.3 エッジサーバの評価**
    - 処理性能（スループット、各ステップの時間）、消費電力。
    - `docs/measure_processing_time` 等のデータを確認。

4. **4.X コスト優位性の評価（新規追加）**
    - **比較表の追加**:
        - 提案システム vs 市販LTEトレイルカメラ
        - 初期費用 (Device Cost) vs ランニングコスト (Operation Cost / Year)
    - 損益分岐点（Break-even point）の提示。

5. **議論の強化 (Discussion)**
    - **RPiの電源問題**: ソーラーパネルとバッテリーのスペックを明記し、電力収支（Energy Budget）が成立していることを論理的に説明する。
    - **見逃し（False Negative）の扱い**: 「なぜ見逃したか（小型動物、遮蔽）」の定性的な分析を加える。

## Verification Plan

### Manual Verification

- **[MODIFY] [main.tex](file:///c:/Users/kapib/vscodegit/wild_animals/test2/docs/ieice_paper_draft/main.tex)**:
  - **表1: 部品構成 (Component Configuration)**: 主要部品とスペック。
  - **表2: エッジカメラ消費電力**: 電圧(V), 電流(mA), 電力(mW)。
  - **表3: エッジサーバ消費電力**: 電圧(V), 電流(mA), 電力(mW/W)。
  - **表4: AI検知精度**:
    - Ground Truth: MegaDetector v5a
    - Metrics: TP, FP, FN, Precision, Recall, Accuracy, **Over-detection Rate (過検出率)**
  - **表5: 通信削減率**: 全画像数 vs 転送画像数。
  - **表6: システム処理時間 (System Processing Time)**: 検知〜通知までの遅延時間 (Latency) の内訳。

### 提案：追加すると論文の価値が高まる指標

ユーザー要望のデータに加え、以下の指標があると「実用性」と「通信コスト削減」の主張がより強固になります。

1. **システム遅延 (System Latency)**
    - **内容**: 動物検知からユーザーへの通知完了までにかかる時間。
    - **理由**: 「即時通知」を謳う上で必須。内訳（カメラ処理、通信、推論）があるとボトルネック分析としても優秀。
2. **データ通信量 (Data Traffic Volume)**
    - **内容**: 画像「枚数」だけでなく「データ量(MB)」での削減率。
    - **理由**: 通信料金はパケット量（バイト数）で決まるため、こちらのほうがコスト削減の直接的な根拠になる。
3. **バッテリー電圧推移 (Battery Voltage Trend)**
    - **内容**: 1週間程度のバッテリー電圧グラフ。
    - **理由**: 「計算上動く」だけでなく「実際に充電され、電圧が維持されている」実証データがあると、信頼性が段違いに上がる。

これらも含めるかどうか、ご判断をお願いします。

- **[MODIFY] [main.tex](file:///c:/Users/kapib/vscodegit/wild_animals/test2/docs/ieice_paper_draft/main.tex)**:
  - `\cite{IEICE2020}` (Saito et al.) を「主な参考文献」として位置づける。
  - 関連研究セクションだけでなく、まえがき等でも言及し、本研究がこの研究の発展形（単体→複数連携）であることを明確にする。
