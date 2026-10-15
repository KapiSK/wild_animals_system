# 修士論文に用いる追加文献の選定

確認日：2026年10月8日

対象は本ディレクトリの `参考文献/`。ICOIACT原稿側の参考文献フォルダに同名ファイルがない6件を新規候補として確認した。これはファイル名による差分であり，追加日時の断定ではない。論文の要旨と関連箇所を読み，現在の第2章・第3章に必要な説明を補えるかで選定した。

**追加候補6件のうち5件を採用候補，YOLO26の1件を条件付き候補とする。** また，以前から保存されているCunhaらの論文を，優先度の高い文献として追加で推す。選定後の依頼により，採用候補5件とCunhaらの計6件を第2章・第3章と参考文献一覧に反映した。Cunhaらは第4章の選別方針でも引用した。YOLO26は未採用。

## 優先順位と使用箇所

| 優先度 | 文献 | 主な使用箇所 | 採用する理由 |
| --- | --- | --- | --- |
| A：優先採用 | Welbourne et al. (2016) | 2.1.2 PIRセンサによる動体検知 | 検知の仕組みと誤解を直接扱い，空撮影の説明を補強できる |
| A：優先採用 | Tian et al. (2021) | 2.4.1・2.4.2 Wi-Fi HaLow | 現状のメーカー資料に，技術全体を整理した学術文献を加えられる |
| A：優先採用 | Zualkernan et al. (2022) | 3.2 通信型の監視・通知，3.3 省電力化と通信量削減，3.4 位置付け | エッジでの動物種分類とLoRaWAN通知を扱い，本研究の画像転送との違いが明確 |
| B：基礎文献として採用 | Redmon et al. (2016) | 2.2.1 物体検出，2.2.2 YOLO | YOLOの基本的な発想を原論文で説明できる |
| B：関連研究を補強 | Norouzzadeh et al. (2018) | 3.1 トレイルカメラ画像の自動解析 | 大規模な画像解析と人手確認の削減を説明できる |
| C：条件付き | Jocher et al. (2026), YOLO26 | 6章のモデル改善，7.2 今後の課題 | 更新モデルの検討には使えるが，使用中のYOLOv8nの直接の根拠にはならない |
| A：既存フォルダから追加推薦 | Cunha et al. (2021) | 3.3 省電力化と通信量削減，5章の評価設計 | 空撮影の選別，見逃しの抑制，推論時間を同時に扱い，本研究との対応が強い |

## 各論文の使い方

### 1. Welbourne et al. (2016)

**How do passive infrared triggered camera traps operate and why does it matter? Breaking down common misconceptions**

[保存PDF](<参考文献/Remote Sens Ecol Conserv - 2016 - Welbourne - How do passive infrared triggered camera traps operate and why does it matter.pdf>) ／ [DOI](https://doi.org/10.1002/rse2.20)

PIRセンサのフレネルレンズと焦電素子，物体表面からの赤外放射，検知領域の関係を説明している。PDFの3〜5ページ，特に「Components of PIR sensors」「Clarifying problematic descriptions」が役立つ。

**引用する論点：** PIRは動物種を認識したり，動物の体内温度と気温を直接比較したりする装置ではない。物体表面からの放射と検知領域の変化を踏まえて，草木やカメラの揺れによる誤トリガーを説明する。

**本文への反映案：** 2.1.2で検知原理の説明に引用し，現在のPanasonic仕様書は採用センサに関わる補足資料として残す。「熱を検知する」だけの説明を避け，なぜ動物が写っていない画像も発生するかにつなげる。

### 2. Tian et al. (2021)

**Wi-Fi HaLow for the Internet of Things: An Up-to-date Survey on IEEE 802.11ah Research**

[保存PDF](参考文献/jnl-tian2021a.pdf) ／ [著者所属大学の出版情報](https://biblio.ugent.be/publication/01M1BXGAWMN56QGK4E5S2P9E5P)

IEEE 802.11ahのPHY・MAC，接続数，省電力，遅延などの研究を整理するサーベイ。保存版の第2節を前提知識に使い，RAWはPDFの10ページ以降，TWTは15ページを参照する。

**引用する論点：** sub-GHzの利用に加えて，多数端末のアクセス調整やスリープ制御が，HaLowの通信と電力に関係する。2.4では，概要と従来のWi-Fiとの比較の根拠になる。

**注意：** 総説なので，個々の距離・電池寿命・速度の実験値を引用する場合は，そこに引用されている実験論文まで確認する。2021年時点の研究動向と，現在の製品仕様や国内の利用条件を混同しない。

保存PDFには「Preprint submitted to Elsevier」とあるが，刊行先は *Journal of Network and Computer Applications*, vol. 182, article 103036, 2021，DOI `10.1016/j.jnca.2021.103036` と大学の出版情報で確認できる。参考文献には刊行版の書誌情報を使い，保存版のPDFページと刊行版のページ数を混同しない。

### 3. Zualkernan et al. (2022)

**An IoT System Using Deep Learning to Classify Camera Trap Images on the Edge**

[保存PDF](参考文献/computers-11-00013.pdf) ／ [DOI](https://doi.org/10.3390/computers11010013)

*Computers*, vol. 11, article 13, 2022。カメラトラップの画像をエッジで分類し，ラベル・時刻・端末IDをLoRaWAN経由でクラウドへ届ける構成を扱う。Raspberry Pi，Google Coral，Jetsonの比較と，モデルをエッジ用に変換した際の性能変化も検討している。

**重点箇所：** システム構成はPDFの9ページ，エッジへの配置結果は第5.3節（16ページ以降），制約は第6節。

**引用する論点：** 「現地で分類して小さな通知データを送る方式」と「画像を共有エッジへ集約し，選別後の画像をクラウドで再判定する本研究」の違い。モデル変換後の少数クラスの性能低下は，軽量化と検出性能を一緒に評価する必要性にも使える。

**既存文献との整理：** 既に引用した同グループの2020年会議論文と話題が重なる。2022年論文を詳しい比較の中心に置き，2020年論文は研究経緯や当時の構成を述べる場合に使う。両論文の機材・データ・数値を混ぜない。

**注意：** 広域側へ送るのは分類結果等であり，画像転送の実証として引用しない。また，表の電流値を電力や1画像当たりのエネルギーと同一視しない。

### 4. Redmon et al. (2016)

**You Only Look Once: Unified, Real-Time Object Detection**

[保存PDF](参考文献/Redmon_You_Only_Look_CVPR_2016_paper.pdf)

画像全体から検出枠とクラスを一つのネットワークで予測する，初代YOLOの原論文。第1節と第2節を使って，物体検出とYOLOの基本的な考え方を説明できる。

**本文への反映案：** 2.2.2の冒頭にYOLOの基本概念を置き，その後に実際に用いるYOLOv8nの説明を続ける。

**注意：** 初代YOLOのネットワーク，損失関数，精度・速度をYOLOv8nの仕様として書かない。YOLOv8固有の内容は既存のUltralytics公式資料を併用する。

### 5. Norouzzadeh et al. (2018)

**Automatically identifying, counting, and describing wild animals in camera-trap images with deep learning**

[保存PDF](参考文献/norouzzadeh-et-al-2018-automatically-identifying-counting-and-describing-wild-animals-in-camera-trap-images-with-deep.pdf) ／ [DOI](https://doi.org/10.1073/pnas.1719367115)

*PNAS*, vol. 115, no. 25, pp. E5716–E5725, 2018。Snapshot Serengetiの大規模画像を用い，動物種・個体数・行動などの情報抽出を扱う。

**引用する論点：** 大量画像の人手確認という課題と，信頼度に応じて自動処理と人手確認を組み合わせる考え方。

**本文への反映案：** 3.1で「大規模な自動解析」の代表例としてTabakらの前に短い段落を置く。Tabakは地域差，Beeryは検出と分類の分離，Fennellは目視分類との比較という役割を残す。

**注意：** 動物種の分類正解率を，空撮影画像の除去性能やシステム全体の再現率として扱わない。データセットと人手への振り分け条件を付けずに精度だけを比較しない。

### 6. Jocher et al. (2026)：現段階では補助候補

**Ultralytics YOLO26: Unified Real-Time End-to-End Vision Models**

[保存PDF](参考文献/2606.03748v1.pdf) ／ [arXiv](https://arxiv.org/abs/2606.03748)

YOLO26の構造と学習方法を説明した開発者によるプレプリント。2026年6月2日のv1を確認した。

**使う条件：** YOLOv8nとのモデル比較実験を行う場合，または今後のモデル更新を論じる場合。現在の研究がYOLOv8nを用いる構成なら，第2章の説明の中心には据えない。

GPU上のベンチマークをRaspberry Piでの速度とみなさない。採録済み論文とする根拠は今回確認していないため，登録する場合はarXiv論文として扱う。

### 7. Cunha et al. (2021)：新規6件以外で優先したい論文

**Filtering Empty Camera Trap Images in Embedded Systems**

[保存PDF](参考文献/Cunha_Filtering_Empty_Camera_Trap_Images_in_Embedded_Systems_CVPRW_2021_paper.pdf)

空撮影画像の除去を目的に，分類器と検出器，入力解像度，量子化などを比較している。動物を含むクラスの再現率を96%に合わせて閾値を調整し，除去性能と推論時間を比較する設計が，本研究の一次選別に直接対応する。

**重点箇所：** 評価方法と結果，特にPDFの5ページのPrecision–Recall曲線と表5，結論。

**本文への反映案：** 3.3で空撮影画像の選別に関する段落を追加する。5章では，単なる画像削減率だけでなく，見逃しを抑えた条件で削減率と処理時間を比較する評価設計の参考にする。

**注意：** 論文の96%を本研究の達成値として扱わない。また，TNR（空撮影画像のうち正しく除いた割合）と，全画像・全サイクルに対する削減率は分母が異なる。

## 本文に取り込む順序

1. **2.1.2にWelbourne，2.4にTianを追加する。** 現在の前提知識の出典を強化する。
2. **3.2・3.3にZualkernan 2022とCunhaを追加する。** 本研究との比較が最も具体的になる。
3. **2.2.2にRedmon，3.1にNorouzzadehを追加する。** 基礎技術と研究背景を補う。
4. **YOLO26は比較実験の予定に応じて判断する。** 採用モデルとの関係が生じるまでは，文献数を増やすだけの引用はしない。

この選定では，既存のSaito，Sato，Beery，Fennellなどは引き続き使用する。追加文献のために現在の関連研究を全面的に置き換える必要はない。
