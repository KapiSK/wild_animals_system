# 第2章〜第4章の執筆元と確認事項

2026年10月7日：ICOIACT原稿を基に第2章「前提知識」を執筆。本文の単純な翻訳ではなく，合意済みの5節に合わせて説明を再構成した。

2026年10月8日：指定により旧2.4「エッジ・クラウド連携と無線通信」と旧2.5「システムの評価に必要な基礎」を削除。その後，合意した新構成に従い第2章を以下の4節に再編し，第3章の本文を追加した。

## 基にした原稿

- `../ieice_paper_draft/icoiact_draft/main_english.tex`
- 題目：Development of a Communication-Efficient Edge–Cloud Monitoring System for Wildlife Damage Control in Rural and Mountainous Areas
- 著者情報の確認元：同ディレクトリの `main_english_with_authors.tex`
- 文献情報の出発点：同ディレクトリの `refs_english.bib`

ローカルにある論文原稿として扱い，採録・発表・刊行の状況は断定していない。第2章・第3章を執筆し，第4章は原稿で確認できる範囲を記述した。第4章の未確定仕様とその他の章には記入案内を残している。

## 原稿と第2章の対応

| 第2章 | 主な執筆元 | 補足した内容 |
| --- | --- | --- |
| 2.1 トレイルカメラの概要 | Introduction / Edge Camera | 概要，PIRによる動体検知，昼夜撮影，画像回収型と通信型の順に再配置 |
| 2.2 画像認識による動物検出 | Related Work / Edge Server / Cloud Server | 物体検出（閾値の説明を含む），YOLO，MegaDetectorの3項 |
| 2.3 マイコンとシングルボードコンピュータ | System Architecture / メーカー一次資料 | 両者の特徴，ESP32，Raspberry Piの3項 |
| 2.4 Wi-Fi HaLow | メーカー一次資料（ICOIACT原稿外の基礎説明） | 概要と従来のWi-Fiとの比較の2項 |

Wi-Fi HaLowについて，本研究で既に採用・実証済みとは記述していない。ESP32-S3内蔵の2.4GHz無線LANとの違いを説明し，具体的な接続構成・評価結果は推定していない。旧2.4・旧2.5の削除した節は復元していない。

## 第3章の構成と確認元

ICOIACT原稿のRelated Workを基に，関係する研究を選んで以下の4節に再構成した。原稿の引用を網羅的に列挙するのではなく，各研究の目的・処理配置・本研究との関係を記述した。

| 節 | 主な文献 | 原論文で確認した内容 |
| --- | --- | --- |
| 3.1 トレイルカメラ画像の自動解析 | Tabak 2019，Beery 2019，Fennell 2022 | 種分類，汎用検出と分類の分離，目視確認との比較 |
| 3.2 通信型の監視・通知システム | Whytock 2023，Patkar 2025，Zualkernan 2020 | 衛星でのラベル通知，Raspberry PiとYOLOv8nによるSMS通知，エッジ分類結果とクラウドDBの連携 |
| 3.3 省電力化と通信量削減 | Saito 2020，Sato 2022，Monburinon 2019，Velasco-Montero 2024，Rahman 2025 | 処理省略・機能分離，階層型ゲートウェイ，現地推論と継続学習，追跡による重複転送の削減 |
| 3.4 本研究の位置付け | 上記研究の比較 | 撮影専用カメラ・共有エッジ・クラウド再判定の組合せと検証課題 |

追加で確認したローカルPDF（`../ieice_paper_draft/参考文献/`）：

- `Methods Ecol Evol - 2018 - Tabak - Machine learning to classify animal species in camera trap images  Applications in.pdf`
- `1-s2.0-S2351989422001068-main.pdf`（Fennell）
- `SSC_25209.pdf`（Patkar）
- `Towards_an_IoT-based_Deep_Learning_Architecture_for_Camera_Trap_Image_Classification.pdf`
- `A_Novel_Hierarchical_Edge_Computing_Solution_Based_on_Deep_Learning_for_Distributed_Image_Recognition_in_IoT_Systems.pdf`
- `1-s2.0-S1574954124003571-main.pdf`（Velasco-Montero）
- `computers-14-00307-v2.pdf`（Rahman）

Tabakの98%は米国内の評価条件とともに記載し，カナダの別データの82%と区別した。Fennellの動物画像に対する適合率82%・再現率92%は閾値0.9の条件を付した。Whytockの7.35分は通知受信までの中央値と明示した。これらは本研究の実験結果ではない。

「既存研究はすべてカメラ側で推論する」「階層構成は未検討」「衛星通信は極めて高額」などの一律の断定は採用していない。比較表は実測性能の優劣ではなく，構成と目的を整理したもの。

後続章への参照は，その章の執筆が完了していることを意味しない。原稿中の81.2%／50.7%，電流値，通信距離，通知時間などの実験結果は第2章には転記していない。

## 出典の確認

ICOIACT原稿で引用される以下の原論文を，`../ieice_paper_draft/参考文献/` のPDFで確認した。

- `EfficientPipeline.pdf`：動物の位置検出と種分類の分離，空撮影画像の確認負荷，夜間画像・誤検出の例。
- `2020_IEICE_Trans_Saito.pdf`：野生動物検出・通知と屋外電源の課題。巻号と掲載ページを確認。
- `Energy_Reduction_Methods_for_Wild_Animal_Detection_Devices.pdf`：機能分離，待機・動作時の電力，無用な処理の削減。DOIを確認。
- `Methods Ecol Evol - 2023 - Whytock - Real‐time alerts from AI‐enabled camera traps using the Iridium satellite network  A.pdf`：衛星回線では判定ラベルとメタデータを通知する点を確認。

ICOIACTのBibTeXにあるWhytock論文のページ範囲 `823–830` は，保存されている原論文の `867–874` と異なる。修士論文の参考文献には原論文の値を使用した。元のBibTeXは変更していない。

以下の一次資料は2026年10月7日にオンラインで補足確認した。

- [Panasonic PaPIRs仕様書](https://industrial.panasonic.com/cdbs/www-data/pdf/EWA0000/ast-ind-384882.pdf)：6-1 Basic Principles。PIR一般の動作原理・検知条件の説明に使用。この仕様書の型番を研究の採用機材とみなしてはいない。
- [Ultralytics YOLOv8公式文書](https://docs.ultralytics.com/models/yolov8/)：モデル系列，YOLOv8n，COCOの80クラス。
- [MegaDetector開発元リポジトリ](https://github.com/agentmorris/MegaDetector)：動物・人・車両の検出と，動物種識別との違い。

初稿に含めた処理分担の概念図と混同行列の定義表は，2.4・2.5の削除に伴い削除した。

2026年10月8日に追加確認した機器・通信技術の一次資料：

- [ESP32-S3データシート v2.2](https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf)：無線方式，GPIO，カメラインタフェース，電力モード。
- [Raspberry Pi 4 Model B仕様](https://www.raspberrypi.com/products/raspberry-pi-4-model-b/specifications/)：基板の入出力機能。
- [Raspberry Pi OS公式文書](https://www.raspberrypi.com/documentation/computers/os.html)：OSの基盤。
- [Morse Micro Wi-Fi HaLow概要](https://www.morsemicro.com/products/chips)と[MM6108製品説明](https://www.morsemicro.com/products/chips/mm6108)：IEEE 802.11ah，sub-GHz，IP対応と省電力機能。製品の最大距離や速度の広告値は一般的な保証として転記していない。

## 後続章の執筆時に照合する事項

- ICOIACT原稿の精度表と削減率表には，画像と撮影サイクルの用語が混在する。元データと集計処理を確認して評価単位を確定する。
- MegaDetectorの出力による参照評価は，人手の正解ラベルに対する性能と区別する。
- COCO事前学習YOLOv8n／閾値0.05の原稿と，現在のコード・モデル・通信方式を混同しない。
- 夜間撮影の照明・設定や，電池の接続構成・使用可能容量は，第2章の一般的な説明から推定せず実装資料で確認する。
- 自律稼働，誤通知防止，低コストなどは設計目標と達成結果を分ける。第2章に追加した定義や注意事項は，新しい実験結果ではない。

## 2026年10月8日：追加文献の反映と第4章の執筆

`literature_selection.md`の選定に基づき，Welbourne 2016，Redmon 2016，Tian 2021，Norouzzadeh 2018，Zualkernan 2022，Cunha 2021の6件を引用付きで追加した。本文は`参考文献/`の保存PDFを参照。Tianの刊行書誌は選定メモに記載した著者所属大学の出版情報で確認した。参考文献は25件を本文の初出順に並べ直した。YOLO26は今回のモデルの根拠として使用していない。

- 第2章：WelbourneによるPIRの検知原理・誤トリガーの説明，RedmonによるYOLOの基本的な発想，TianによるRAW・TWTの説明を追加。
- 第3章：Norouzzadehによる大量画像の解析と人手確認，Zualkernan 2022のLoRaWANによるラベル通知と機器比較，Cunhaによる空画像除外・再現率・推論時間の関係を追加。比較表にも反映。
- 第4章：ICOIACT原稿のProposed Systemと実験用機器表から，設計要件，3層構成，機器一覧，各層の処理，通信経路を記述。日本語の構成図は原稿の処理を基にLaTeXで新規作成。

第4章の記述基準はICOIACT用原稿の試作構成。作業中の最新コードに存在する別モデル・FTP/SFTP等の機能を，原稿の評価条件へ混在させていない。YOLOv8nの閾値0.05は原稿のAI評価節に記載された設定。3枚のうち1枚以上が動物候補なら画像群を転送する規則を数式化したが，実際の転送枚数と評価表の集計単位はコード・元データとの照合を残す。

主な未確定事項は，第4章の灰色の記入案内として残した：数値目標，センサ・カメラ型番，配線と電池の接続，夜間照明，撮影設定，保存方法，OS・ライブラリ版，画像とサイクルの識別，対象クラス，クラウドの閾値と通知単位，再送・重複・容量不足への対応。

原稿の単3形電池8本・6Vという記載と，消費電流測定時の5.0Vは区別して記述した。約200Wのパネル・100Ahの電池は原稿上も推定値であり，実装済みの電源仕様としては転記していない。Deep-sleepの利用をもって長期稼働が達成されたとは記述していない。Wi-Fi HaLowは基礎技術・今後の検討対象として扱い，試作構成の2.4GHz Wi-Fiと区別した。
