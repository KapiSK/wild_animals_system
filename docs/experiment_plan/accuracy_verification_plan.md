# AI精度評価（階層アーキテクチャ）の実施計画

階層アーキテクチャ（Edge: YOLO → Cloud: MegaDetector）における「取りこぼし（False Negative）」や「過検出（False Positive）」を正確に評価するための手順をまとめました。

## 課題の整理

このシステムでは、Edge側（YOLO）が「動物なし」と判断した画像は送信されないため、そのままでは**「Edgeが本当は動物がいたのに見逃した画像（False Negative）」をクラウド側で確認することができません。**

## 解決策: 全画像保存モードでのデータ収集

精度の検証を行う期間だけ、**Pi（Edge Server）ですべての画像を保存し、それらに対してオフラインで検証を行う**必要があります。

### 手順

1. **データ収集**
    * Pi の `main.py` はデフォルトで全ての受信画像を `uploads/` フォルダに保存する仕様になっています（転送するかどうかに関わらずファイルは保持されます）。
    * したがって、実験期間中に撮影された画像は、PiのSDカード内にすべて残っています。
    * 実験終了後、Piから全ての画像（`uploads/` 内）をPCにコピーしてください。

2. **比較スクリプトの実行 (`compare_models.py`)**
    * PC上で `compare_models/compare_models.py` を実行します。
    * このスクリプトは、同一の画像セットに対して **YOLOv8** と **MegaDetector** の両方で推論を行い、結果を比較します。

    ```bash
    python compare_models/compare_models.py --images "C:/path/to/pi_images" --md "md_v5a.0.0.pt" --yolo "yolov8n.pt"
    ```

3. **結果の解釈**
    スクリプトが出力する4つのカテゴリを確認します。

    | カテゴリ | Edge (YOLO) | Cloud (MD) | 意味 |
    | :--- | :--- | :--- | :--- |
    | **Both Detected** | 〇 | 〇 | 正常動作（正しく検出し、正しく転送された） |
    | **MD Only** | × | 〇 | **Edgeでの取りこぼし (False Negative)** <br> ※これが「システムの精度低下」の主因となります。 |
    | **YOLO Only** | 〇 | × | **Edgeでの過検出 (False Positive)** <br> ※無駄な通信が発生したが、Cloudで正しく棄却されたケース。 |
    | **Neither** | × | × | 正常動作（何もいないので、何も送らなかった） |

### 補足: 真の正解ラベル (Ground Truth)

`compare_models.py` はあくまで「MegaDetectorを先生（正解）」とした場合の比較です。
より厳密な評価を行うには、**「MD Only」や「YOLO Only」となった画像を目視確認**し、本当に動物がいたのかどうかを人間が判断する必要があります。

* **MD Only の画像に本当に動物がいた場合**: YOLOの精度不足（要モデル再学習 or 閾値調整）。
* **MD Only の画像が実は誤検知だった場合**: YOLOが正しかった（MDの誤検知）。

このスクリプトの結果（グラフや数値）を論文の「精度評価」セクションに使用できます。
