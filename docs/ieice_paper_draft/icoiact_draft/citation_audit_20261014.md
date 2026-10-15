# ICOIACT原稿の引用チェック（2026-10-14）

対象：`main_english.tex`の全24引用資料（論文23件・農林水産省資料1件）と、追加候補のAmeliaらのICOIACT 2024論文。
方法：保存済みPDFの要旨・該当する方法／結果／考察を原稿の引用文と照合。農林水産省資料は公式サイトで確認した。引用先の実験を再現して品質を保証する監査ではなく、原稿の説明が引用先の内容に対応するかを点検した。
チェック時点では本文・BibTeX・PDFを変更していない。以下は修正前の原稿に対する記録。

**後続の反映状況（2026-10-14）：** ユーザーの修正依頼に基づき、下記1–5の引用表現を修正。6は風・植生への限定を外し、誤作動による空画像という表現に変更した。ECISの構成説明を具体化し、Saitoらの補助ボードによる電源制御、通信集約と推論集約の区別、研究の位置付けを明確化した。書誌情報の修正候補も反映し、PDFの6ページ、引用解決、はみ出し警告なしを確認。著者欄・謝辞は維持。Ameliaらの新規引用は追加していない。ユーザーが別途追記した参考文献メモは、確認した2つの「メモ」ファイルに見当たらず、保存先を照会中。

**メモ照合完了：** その後、`icoiact_draft/メモ`に追記された正式書誌情報を確認。Whytockらの著者名・3号、BeeryらのarXiv表記、Patkarらの2号、Madhumathiらのイニシャル、Carmona-GalánとA. Cole Burtonの著者表記、IEICEの巻表記を反映した。タイトル中のAI・IoT・YOLO等の大文字表記もBibTeXの変換から保護した。参考文献24件と6ページ構成を維持。メモの所在確認に関する保留は解消済み。

## 優先して修正したい箇所

### 1. Muleroらの研究を「空画像を除外してから種を判別」とまとめるのは不正確

箇所：Related Work、main_english.texの74行目。

現在はHitchcockら（rs18030502）とMuleroら（Mulero2025）を一緒に引用し、MegaDetectorで空画像を除去した後、専門モデルで種を判別する流れとして説明している。

Muleroらは、MegaDetectorを初期モデルとした転移学習を使い、全体モデルと動物グループ別の専門モデルを組み合わせる。全体モデルが背景と判定した画像も、すべての専門モデルへ回して再評価する。空画像として捨てるだけの流れではない（PDF pp. 3, 7, 9、Fig. 2）。

修正の意味：
「複数段階の処理には、汎用検出器・種分類器・人手確認を組み合わせる方法や、全体モデルの判定を専門モデルで再評価する方法がある。」

英文案：
> Hitchcock et al. proposed a semi-automated workflow combining a general-purpose detector, a species classifier, and manual verification \cite{rs18030502}. Mulero-Pázmány et al. combined a global model with group-specific expert models to refine animal identification \cite{Mulero2025}.

その後の「初段で非対象画像を捨てると後段を効率化できる」という総括は、両研究に共通する結論として置かない。残すなら、空画像フィルタリングの文献だけに結び付ける。

### 2. Hitchcockらの人手確認を省略すると、完全自動処理の実証のように読める

同じ74行目。Hitchcockらの提案はMegaDetector → Conservation AI → 人手確認という半自動ワークフロー。論文の中心的な性能評価はConservation AIの再学習前後の評価であり、この引用から本研究の自動エッジ・クラウド構成の性能が実証されたとは言えない（PDF pp. 1–3, 14–15、Fig. 6）。上記の英文案なら適切。

### 3. Satoらの「運用費と消費電力を削減した」は効果を広くまとめすぎている

箇所：Related Work、78行目、およびProposed System冒頭83行目とのつながり。

Satoらは公衆回線の通信を親ノードへ集約し、子ノードから公衆回線用モジュールを取り除く構成を提案している。子ノードは引き続き動物検出と警報を実行する（PDF p. 7、Figs. 7–9）。
省エネルギー評価は、複数の対策、動作頻度などの条件を含む。携帯回線契約料などを含む運用費削減を定量的に検証したとは確認できなかった。

修正の意味：
「Satoらは、公衆回線の通信を親ノードへ集約し、子ノードの通信モジュールを省くことで消費電力を抑える構成を提案した。動物検出は子ノードに残る。」

英文案：
> Sato et al. separated public-network communication into a parent node to reduce the power requirements of child nodes, which retained animal detection and alerting functions \cite{Sato2022}.

本研究が参考にしたのは通信集約という考え方であることが明確になる。本研究の共有エッジサーバーへの推論集約まで、この先行研究の構成として説明しない。

### 4. Introductionの「LTEまたは衛星通信」という一括説明を広げる

箇所：64行目。Whytock2023、Patkar2025、9345858をまとめて引用している。

WhytockらはIridium衛星通信なので適切。一方、Patkarらで確認できるのはRaspberry Pi・YOLOv8n・Twilio SMS通知、Zualkernanらで確認できるのはWi-Fi対応SDカードからの画像取得、エッジ推論、クラウドDB・アプリ連携である。これらを一括してLTE利用の事例とする根拠は弱い。

修正の意味：
「IoTや衛星通信を用いて、遠隔地へ検出結果を通知する監視システムが提案されている。」

英文案：
> IoT-based monitoring systems with remote notifications and satellite-connected camera traps have been developed to provide timely information \cite{Whytock2023,Patkar2025,9345858}.

### 5. Tabakらの98%に評価範囲を添える

箇所：74行目。

98%という値は正しい。ただし米国データの種分類結果。地域外のカナダデータでは82%、タンザニアでの動物画像識別は別の評価で94%と報告されている（PDF p. 1）。

修正の意味：「米国の評価画像で約98%の種分類正解率を報告した」。短い限定だけで一般化しすぎる印象を防げる。

### 6. Beeryらを引用した「風で動く植生」の原因説明を調整

箇所：66行目。

Beeryらの論文は空画像と誤作動の多さを説明するが、保存PDF本文にwind／vegetationの明示は確認できなかった。風による植生の動きは、既存文献のZualkernanら（9345858、PDF p. 1）やMuleroら（PDF p. 2）が明記している。

原稿の主張自体を否定する指摘ではない。Beeryらの引用を保つなら「誤作動によって空画像が生じる」と一般化する。原因まで残すなら、それを直接説明している既存文献を併記する案が適切。引用の変更は今回実施していない。

## 文献ごとの判定一覧

「概ね適切」は原稿で現在述べている範囲についての判定。引用先のすべての主張や数値を保証する意味ではない。ページは原則として保存PDF内のページ番号。

| 引用キー／文献 | 判定 | 確認した内容と注意点 |
|---|---|---|
| maff | 適切 | FY2024の188億円＝18.8 billion yenは公式資料と一致。鳥類も含む野生鳥獣全体の統計。 |
| Tabak2019 | 限定を追加 | CNNによる種分類、空画像識別の引用は適切。98%は米国データでの結果と限定する。PDF p. 1。 |
| Beery2019 | 一部調整 | 汎用動物検出と空画像除去の出典として適切。風・植生という具体的原因は別文献が直接裏付ける。MegaDetectorの基礎的手法の出典として使え、v5a固有仕様の裏付けとは区別する。 |
| rs18030502／Hitchcockら | 修正推奨 | 汎用検出・種分類・人手確認の3段階。「半自動」と「人手確認」を明記。PDF pp. 3, 14–15。 |
| Whytock2023 | 内容は適切 | Iridiumによる遠隔通知。通信圏外での通知の事例として対応している。書誌ページに誤りあり。 |
| Patkar2025 | 一部調整 | Raspberry Pi上のYOLOv8nとTwilio SMSは対応。LTEの事例としての一括引用は避ける。PDF pp. 1, 6–7。 |
| 9345858／Zualkernanら | 一部調整 | カメラ→Raspberry Pi推論→クラウドDB・アプリという説明は適切。LTEの実装例とは断定しない。PDF pp. 1–3。 |
| Sato2022 | 修正推奨 | 親子構成と省電力は対応。運用費削減を実証したという断定を弱め、子ノードで推論する点を明確にする。PDF pp. 6–7, 10–12。 |
| 10394750／Shettyら | 概ね適切 | YOLOv5・YOLOv8による動物検出の例として対応。原稿は結果数値を転用していない。PDF要旨・結論。 |
| 10126065／Madhumathiら | 概ね適切 | YOLOv5による検出と警報の研究として対応。実環境での効果や被害削減を実証した根拠にはしない。PDF要旨。 |
| VELASCOMONTERO2024102815 | 適切 | 空画像フィルタリングと省エネルギーなカメラ内AI実装の文脈に対応。PDF pp. 3, 5–7。 |
| IEICE2020／Saitoら | 概ね適切、具体化可能 | Raspberry Piと低消費電力Lazuriteボードを併用し、待機時のPi給電を止める構成を含む。「power-saving microcontroller implementations」は誤引用とまでは言えないが、補助ボードによる電源制御と書く方が明確。PDF pp. 4–7。 |
| Fennell2022 | 概ね適切 | 動物画像に対するprecision 82%、recall 92%を報告（閾値90%）。現在の一般的な説明は対応する。MegaDetectorを完全な正解ラベルと見なす根拠にはならない。PDF p. 1。 |
| Mulero2025 | 修正が必要 | 全体モデル＋専門モデル。背景判定画像も再評価するため、単純な空画像破棄の流れとして一括説明しない。PDF pp. 3, 7, 9。 |
| Computers2025／Rahmanら | 適切 | Kalman・LBP等を使った追跡で同じ動物の繰り返し送信を抑制。原稿の説明と対応。本文には電力・帯域削減率の表記の揺れがあるので、現在のように数値を転用しない記述がよい。PDF pp. 1, 26–27。 |
| 10716895／Kathirら | 適切 | YOLOv8を用いる農地への動物侵入検出の事例として対応。PDF要旨。 |
| 11459678／Selvarajら | 適切 | YOLO・CNNを用いた動物侵入検出と通知の事例として対応。PDF要旨。 |
| SMC2024／Sembaら | 適切 | YOLOv5・DeepSort・PTZカメラ制御による追跡。原稿のPTZ追跡の説明と対応。PDF p. 1。 |
| 11337723／Eyes in the Thicket | 適切 | PIRを起点とした画像処理とGSM通知を記載。現在のPIR-triggered alertsという説明に対応。PDF pp. 3–5。 |
| 8912138／階層型エッジ研究 | 適切 | 低価格のRaspberry Piゲートウェイで主要処理を担い、クラウド依存による費用・遅延の課題に対応する研究。PDF要旨。 |
| SPARROW2026 | 適切 | 周辺カメラ・センサー→ローカルハブ→携帯／衛星通信という構成、および定期送信と条件付き即時送信を明記。PDF pp. 4, 6, 8–9。arXivプレプリントであることを保つ。 |
| Harits2025ECIS | 適切 | ESP32→Raspberry Pi 4での侵入防止・暗号化→Firebaseという構成。中間処理層の先行事例という現在の引用は妥当。PDF pp. 2–3。野生動物検出や本研究の省電力性能の根拠には使わない。 |
| 8716170／Kamesaka・Hoshino | 適切 | サルを検出・通知し、管理者がWebブラウザーで檻を操作する構成。遠隔操作の捕獲装置という説明に対応。PDF p. 2。 |
| 11324419／超音波忌避研究 | 概ね適切 | 動物種に応じた超音波出力を組み合わせる提案として対応。長期的な忌避効果の保証としては扱わない。PDF pp. 1, 4–5。 |
| Ameliaら／ICOIACT 2024（追加候補） | 提案した用途なら適切 | DIORの小物体検出でYOLOv8の構造とWIoUを組み合わせた研究。モデル改善の候補として引用可能。夜間の野生動物検出やRaspberry Pi上の速度改善を実証した論文ではない。現原稿には未引用。 |

## 書誌情報の修正候補

本文の引用意図とは別に、PDFとBibTeXを照合して次を確認した。

- Whytock2023：BibTeXのページは823–830だが、保存PDFは **867–874**。修正が必要。
- Tabak2019：著者一覧から **Paul M. Lukacs、Anna K. Moeller、Elizabeth G. Mandeville、Jeff Clune** が抜けている。保存PDFの著者順に補う。DOI `10.1111/2041-210X.13120` も追加可能。
- Computers2025：第一著者を `Rahman, Md` としているが、保存PDFは **Md. Auhidur Rahman**。`Rahman, Md. Auhidur` など、正しいイニシャルが出る表記にする。
- IEICE2020：保存PDFの巻号は **E103-B, no. 12, December 2020**。現在の月は7月（オンライン公開月に対応）。巻号の正式発行情報に合わせるなら12月・12号に整える。
- Sato2022：DOI `10.1109/ACCESS.2022.3155242` が保存PDFにあり、BibTeXへ追加可能。
- ECIS：ユーザー提供BibTeXと照合済み。24–29ページは追加済み。引用キーが数値IDと異なっていても問題ない。

## 原稿全体の位置付け

Introductionの「これらを両立するシステムは十分検討されていない」という広い研究ギャップの断定は、SPARROWなどを追加した現在では慎重に扱いたい。本研究が評価した具体的な組合せ（撮影専用ノード、共有エッジでの軽量選別、クラウドでの再確認）を貢献として述べる方が明確。既存研究がないことを証明するための追加調査を必要としない表現にできる。

まずは上記1–4と書誌情報の明確な誤りを修正し、5–6を短い表現調整で対応する案を推奨する。追加実験・新しい比較表は不要。6ページ維持には、追記よりも既存文の置換を中心にする。

## 参照先

- [原稿](main_english.tex)
- [BibTeX](refs_english.bib)
- [Muleroら](../参考文献/s41598-025-90249-z.pdf)
- [Hitchcockら](../参考文献/remotesensing-18-00502.pdf)
- [Satoら](../参考文献/Energy_Reduction_Methods_for_Wild_Animal_Detection_Devices.pdf)
- [ECIS](../参考文献/Edge_Computing_IoT_Security_ECIS_Implementation_of_IPS_and_Encryption_for_My_I-Pond.pdf)
- [SPARROW](../参考文献/2606.00108v1.pdf)
- [農林水産省：全国の野生鳥獣による農作物被害状況](https://www.maff.go.jp/j/seisan/tyozyu/higai/hogai_zyoukyou/index.html)
