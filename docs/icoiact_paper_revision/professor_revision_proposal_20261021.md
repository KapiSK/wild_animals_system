# 教授コメントに対するICOIACT原稿の修正案

作成日：2026年10月21日

対象：`../ieice_paper_draft/icoiact_draft/main_english.tex`。教授の指摘にある英文が一致するため，このファイルを基準とする。`main_english_with_authors.tex`には異なる旧記述が残っているため，ファイル名だけで最新版と判断しない。本書は修正案であり，原稿・図・PDFはまだ変更していない。

## 1. 修正方針と対応表

| 指摘 | 修正案 | 状態 |
| --- | --- | --- |
| 木曽町の昼夜画像を1枚ずつ掲載，夜は推論失敗例 | IV-Eに2枚組の図を追加。夜はYOLOv8nの見逃しを実際の評価ログと目視で確認する | 対象画像の確定が必要 |
| 昼間画像は4,284枚ではないか | 集計CSVは4,283枚。単純に4,284へ変更せず，画像一覧とイベントの対応を照合 | 集計値は確認済み，差の理由は未確定 |
| 図3のSencingと文字サイズ | `Sensing`への訂正に加え，意味を明確にするため`PIR triggered?`を推奨。2段幅のベクトル図として再作成 | 図の修正仕様を下記に記載 |
| Abstract・Conclusionのlow-costを削除 | 主張を通信効率と処理分担に統一 | 差し替え英文を作成済み |
| PIRの動体検知とAIの動物検出を区別 | PIRは`motion sensing`／`PIR trigger`，AIは`animal detection`とする | 差し替え英文を作成済み |
| verify deep-sleep entry | 未確認のスリープ移行不良を示唆するため削除。周辺回路の電源制御と実測を改善案として残す | 差し替え英文を作成済み |
| 式1・Table VのTrigger | 単位を`capture event`に統一。選別評価なので`selected for forwarding`とする | 式・表の案を作成済み |
| IV-Eのtendencyが冗長 | 数値のみ提示し，解釈はDiscussionへ集約 | 差し替え英文を作成済み |
| IV-Fの測定起点が不一致 | 撮影開始からメール送信処理完了へ統一する案。計測コードで境界を確認して確定 | 時間値と測定区間の照合が必要 |
| detectedをdetectsへ | 一般的な判定規則として現在形に変更 | 差し替え英文を作成済み |
| Conclusionの冒頭 | `This paper presents`で開始 | 差し替え英文を作成済み |

## 2. 評価データの画像追加

IV-Eのデータセット説明の後に，昼間1枚・夜間1枚を横並びで掲載する。現在のFig. 3の後に置けば，新しい図はFig. 4となる想定。図番号はLaTeXの参照で自動管理する。

- 昼間：木曽町の実際の評価対象から，動物が目視で確認できる例を選ぶ。成功例と説明する場合はYOLOv8nの検出ログも確認する。
- 夜間：同じ評価対象から，動物が目視で確認できるにもかかわらず，YOLOv8nが閾値0.05で検出しない画像を選ぶ。MegaDetector v5aの閾値0.25の結果も併記できるよう確認する。
- 表のイベント単位の見逃しを説明するには，その画像だけでなく，当該イベントの利用可能な画像すべてがYOLO陰性であることを確認する。他の画像で検出している場合は「画像単位の見逃し」であり，イベント単位の見逃しとは書かない。
- 写真の明るさやコントラストを加工して評価時の入力と異なる見え方にしない。検出枠を重ねる場合はモデル名と閾値を明示する。

本文追加案：

> Fig. \ref{fig:kiso_examples} shows daytime and nighttime examples from the Kiso Town evaluation dataset. The nighttime example contains a visible animal that YOLOv8n does not detect at a confidence threshold of 0.05.

キャプション案（夜間の目視・ログ確認後に使用）：

> Example images from the Kiso Town evaluation dataset: (a) a daytime image and (b) a nighttime image containing an animal missed by YOLOv8n at a confidence threshold of 0.05. These images were acquired using commercial trail cameras, not the prototype camera.

イベント単位の見逃しまで確認できた場合の追加文：

> The nighttime image belongs to an MD-positive event for which YOLOv8n detects no animal in any available image.

画像選定状況：今回確認した`ai_ex/results_benchmark/mismatch_list.csv`は2026年5月の画像に対するMegaDetector v5aとv6の比較であり，今回の2025年6〜11月のYOLOv8n評価の夜間見逃し例を裏付ける資料には使えない。既存の`ai_ex/results/`の描画済み画像も，評価対象との対応と検出条件を照合してから採用する。現時点では掲載する2枚のファイルは確定していない。

## 3. 昼間4,283枚と4,284枚の確認

確認元：`../ieice_paper_draft/データ/benchmark_summary_day.csv`と`benchmark_summary_night.csv`のYOLOv8n・閾値0.05の行。

| 項目 | 昼間 | 夜間 |
| --- | ---: | ---: |
| CSVの画像数 | 4,283 | 804 |
| CSVのイベント数（Total_Cycles） | 1,428 | 268 |
| イベント数×3 | 4,284 | 804 |
| MD陽性・YOLO陽性 | 195 | 104 |
| MD陽性・YOLO陰性 | 13 | 48 |
| MD陰性・YOLO陽性 | 73 | 28 |
| MD陰性・YOLO陰性 | 1,147 | 88 |
| 選別を通過したイベント数 | 268 | 132 |
| イベント削減率（再計算） | 81.2% | 50.7% |

混同行列の和は昼間1,428，夜間268で整合する。昼間の枚数は理論的な3枚組の総数より1枚少ないが，画像欠落，読み込み失敗，除外条件，グループ化の方法，CSVの記録誤りのいずれによるものかは要約CSVだけでは分からない。「1枚欠損した」ともまだ断定しない。

当面の英文案（原因を推定せず，記録に基づく枚数を明示）：

> The evaluation uses 1,428 daytime capture events and 268 nighttime capture events. The benchmark records list 4,283 daytime images and 804 nighttime images. A model labels an event positive if it detects an animal in at least one available image.

最終稿では，評価時のファイル一覧・読み込み成功数・イベントへの割当てを照合する。実際に1枚少ないことが確認できれば，その理由を短く追記する。4,284枚が正しいと分かった場合は枚数を訂正し，その1枚がイベント判定に影響しないかも再確認する。枚数の訂正だけを理由にイベント単位の指標を自動変更しない。

## 4. 図3の修正仕様

対象画像：`../ieice_paper_draft/img/system_flow_eng.png`。画像内の現在の綴りは`Sencing?`。文字の訂正だけなら`Sensing?`だが，PIRとAIを区別するため`PIR triggered?`を推奨する。

現在は横に3系統を並べた画像を1段幅に縮小している。LaTeXの`figure*`を用いて2段幅に配置し，TikZなどでベクトル図として再作成する案とする。最終PDFで主要文字を9〜10pt程度確保し，文言を短くする。解像度だけを上げても誌面上の文字は大きくならない。

| 現在の表記 | 修正候補 |
| --- | --- |
| Sencing? | PIR triggered? |
| Run animal detection | Run YOLOv8n |
| Run Advanced Animal Detection | Run MegaDetector v5a |
| Animal detected in any of images? | Animal detected in any image? |
| Capturing three images | Capture three images |
| Send e-mail to user | Send email alert |

3列の見出しを`Edge camera`，`Edge server`，`Cloud server`とする。PIRの判定とAIの判定にはそれぞれ上記の名称を付け，Yes/Noの分岐を明示する。保存先の内部ディレクトリ名は短縮し，クラウドが通知の有無によらず受信画像を保存することを読み取れる構成にする。夜間モードの分岐は実装に合わせて維持する。

## 5. AbstractとConclusion

Abstractの第2文を次に置き換える：

> This paper presents a communication-efficient edge--cloud monitoring system using multiple trail cameras for wildlife damage control.

`cost constraints`は背景の制約として残してよい。一方，費用比較を実施していない以上，提案・成果の呼び方から`low-cost`を外す。本文の機器説明にある`Although inexpensive`も，価格を主張しない次の文に簡略化すると一貫する。

> The prototype uses the Seeed Studio XIAO ESP32S3 Sense, which provides Wi-Fi connectivity and camera functionality.

Conclusionの第1段落の差し替え案：

> This paper presents a communication-efficient edge--cloud monitoring system for wildlife damage control. The system separates image acquisition, edge filtering, and cloud verification across capture-only cameras, a shared edge server, and a cloud server. Multiple cameras share an LTE uplink through a local WLAN. The prototype combines YOLOv8n-based edge filtering with MegaDetector v5a-based cloud verification. In the Kiso Town dataset evaluation, edge filtering reduced the number of capture events selected for forwarding by 81.2% during daytime and 50.7% at night. Recall relative to MegaDetector reference labels was 93.8% and 68.4%, respectively. Nighttime detection and power consumption remain key limitations.

LaTeXへ反映する際は`%`を`\%`とする。Future workの段落は維持する。

## 6. PIRとAIの用語の書き分け

| 対象 | 使用する語 | 意味 |
| --- | --- | --- |
| PIRセンサ | motion sensing / PIR trigger | 赤外線変化に対する反応。動物の存在を確定しない |
| 撮影単位 | capture event | 通常3枚の画像を含む，1回の検知に伴う撮影単位 |
| YOLOv8n | animal detection / edge filtering | 画像内の動物候補を検出し，転送対象を選ぶ |
| MegaDetector | animal detection / cloud verification | 転送画像から動物の有無を再判定する |

III-AのEdge Camera冒頭の差し替え案：

> Edge cameras are deployed throughout the monitoring area. A PIR sensor triggers image acquisition in response to motion-related changes in infrared radiation. The cameras capture images and transfer them to the edge server without performing AI inference. Animal presence is assessed by the detection models on the edge and cloud servers.

同節の`A PIR sensor is used as a trigger for motion detection`は次へ変更：

> A PIR sensor provides the trigger for image capture, and the images are transmitted to the edge server via HTTP over Wi-Fi.

III-Bのカメラ処理の末尾などに，評価単位の定義を追加：

> A capture event normally consists of three consecutive images acquired following a single PIR trigger.

`trigger`はPIRの反応を説明する場面では適切なので全面的には削除しない。集計単位に用いた`Triggers`を`Events`へ変更する。

## 7. Section Vのverify deep-sleep entry

この表現は「実際にDeep-sleepへ移行しているかを検証する」という意味で，測定された待機電力が大きい原因候補としてスリープ移行不良を挙げたものと読める。しかし現状の原稿には移行不良の実測根拠がなく，III-AのDeep Sleep使用の説明との関係も不明確なため，削除する。

該当2文の差し替え案：

> Potential improvements include switching off inactive peripherals, such as the SD card and camera, and shortening active capture and communication periods. Component-level power measurements are needed to quantify the contribution of each peripheral to standby consumption.

これにより，周辺回路が原因だと断定せず，検証可能な改善案としてDiscussionに残せる。

## 8. 式1・Table Vの評価単位

実データセットを使った選別の評価なので，`Transmitted Triggers`より`Events selected for forwarding`が正確である。実通信の成功件数や転送バイト数を測った指標とは区別する。

式案：

```latex
\begin{equation}
R_{\mathrm{event}} = \left(1-\frac{N_{\mathrm{selected}}}{N_{\mathrm{total}}}\right)\times100\%.
\label{eq:reduction}
\end{equation}
```

直後の説明：

> Here, $N_{\mathrm{total}}$ is the total number of evaluated capture events, and $N_{\mathrm{selected}}$ is the number of events selected for forwarding by YOLOv8n.

Table Vの案：

| Item | Daytime | Nighttime |
| --- | ---: | ---: |
| Total events | 1,428 | 268 |
| Selected events | 268 | 132 |
| Event reduction (%) | 81.2 | 50.7 |

キャプション案：`Reduction in capture events selected for forwarding.`

## 9. Section IVの結果とDiscussionの解釈を分ける

IV-Eの精度表の後：

> Relative to the MegaDetector reference labels, daytime recall and precision were 93.8% and 72.8%, respectively. Nighttime recall and precision were 68.4% and 78.8%, respectively.

`Conversely`と`showing a tendency ...`を削除する。

転送削減の定義文（教授指定のdetectsを使用）：

> This is the fraction of events not selected for forwarding because YOLOv8n detects no animal in any available image.

表の後：

> The event-based reduction rates were 81.2% during daytime and 50.7% at night.

`confirming a tendency ...`を削除する。昼夜差の意味，見逃しとの関係，夜間の低コントラストという仮説はDiscussionに残す。単一の失敗例の見た目だけで原因を確定しない。

同じ原則をIV-Dにも適用し，末尾の`Thus ... suggesting that repeaters ...`を削る。IV-Dは距離ごとのRSSIと転送・接続の観測結果までとし，中継や別方式が必要という設計上の判断はDiscussionに置く。

## 10. Section IV-Fの時間の定義

### 推奨する記述範囲

「動物を検出してから」はPIRとAIのどちらか不明であるため使用しない。原稿前半に合わせるなら，起点は`the start of image capture`，終点は`completion of email sending at the cloud server`とする案がよい。メール送信処理完了と利用者のメール受信は別なので，実際に受信まで測定していなければ`notification received by the user`とは書かない。

既存の20秒・13秒・11秒が重複しない区間で，この起点・終点と一致すると確認できた場合の英文案：

> Under stable communication conditions with an RSSI of approximately -35 dBm, processing from the start of image capture to completion of forwarding at the edge server took approximately 33 s: approximately 20 s for camera processing and 13 s for edge-server processing. Processing from cloud reception to completion of email sending took approximately 11 s. The corresponding total processing time was approximately 44 s, measured from the start of image capture to completion of email sending at the cloud server.

### 確認が必要な理由

保存されているCSVには，この英文と数値をそのまま確定できない点がある。

- `エッジカメラ処理時間.csv`の先頭イベント188は`Total_ms=12909`。原稿の約20秒との集計上の対応が不明。
- `エッジサーバー処理時間.csv`のイベント189は`total_time_ms=7248`に対して`forward_ms=7692`で，`wait_overhead_ms=-9518`。各列が排他的な経過時間とは限らず，単純加算できない。
- `クラウドサーバー処理時間.csv`の先頭行は`total_time_ms=11285.31`，`inference_time_ms=11242.48`，`email_time_ms=3364.17`。totalが推論とメール送信をともに含むとは判断できない。
- クラウドCSVとカメラ・エッジCSVのイベントIDが一致しておらず，同じイベントの一連の測定とは確認できない。

計測時のコード版，区間の開始・終了位置，対象イベント，平均等の集計方法を確認する。カメラ送信とエッジ受信，エッジ送信とクラウド受信が重なる場合，ノード別の処理時間を単純加算しない。44秒が独立区間の推定合計であれば，`measured`を使わず`estimated`とし，実測の端から端までの通知時間とは分ける。根拠が得られるまでは，44秒を新たな測定値として確定させない。

## 11. 反映時の確認順序

1. 用語・low-cost・現在形・重複する考察を修正する。
2. 式と表をcapture eventに統一し，本文・Abstract・Conclusionの数値と照合する。
3. 画像一覧から昼間枚数を確認し，昼夜の掲載画像と夜間の見逃しログを確定する。
4. 図3を2段幅で作り直し，実際の誌面サイズで文字と分岐を確認する。
5. 時間計測の区間と集計根拠を確認し，IV-FとDiscussionの44秒の表現を揃える。
6. LaTeXをビルドし，図の追加に伴うページ数，図表番号，引用参照と配置を確認する。
