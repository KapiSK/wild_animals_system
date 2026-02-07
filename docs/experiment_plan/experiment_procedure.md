# 実験手順書: 野生動物監視システム評価

このドキュメントでは、実装したログ機能 (`metrics.csv`, `edge_metrics.csv`, `cloud_metrics.csv`) を使用して、論文執筆に必要なデータを収集・分析する手順を説明します。

## 1. 実験準備

### 1-1. 機材配置

* **ESP32カメラ**: 監視対象エリア（またはテスト環境）に設置。電源を接続（またはバッテリー）。
* **Edge Server (Pi)**: カメラからのWi-Fiが届く範囲に設置。
* **External Server**: インターネット経由でアクセス可能な状態（ローカルPCでも可）。

### 1-2. 初期化

実験開始前に、過去のデータをクリアして混同を防ぎます。

1. **ESP32**:
    * SDカード内の `/archive/` フォルダを空にする（またはバックアップして削除）。
    * `/metrics.csv`, `/logs/esp.log` を削除またはリネームする。
    * `/logs/uploaded_cids.txt` を削除する（再送テストのため）。
2. **Edge Server**:
    * `edge_metrics.csv` を削除またはリネームする。
    * `uploads/` フォルダ内の画像を空にする。
3. **External Server**:
    * `cloud_metrics.csv` を削除またはリネームする。

## 2. データ収集（実験実行）

以下の条件でシステムを稼働させます。

1. **起動**: Server -> Pi -> ESP32 の順に起動を確認。
2. **トリガー**:
    * PIRセンサーの前で動作を行い、撮影をトリガーする。
    * または、タイマー（20分間隔）で動作するのを待つ。
3. **試行回数**:
    * 統計的な信頼性を得るため、**最低 10〜30 サイクル** 程度のデータを取得することを推奨します。
    * 動物が映っているケース（Positive）と、映っていないケース（Negative）の両方を含めてください。

## 3. データ回収

実験終了後、各ログファイルを回収します。

| デバイス | ファイルパス | 内容 | 回収方法 |
| :--- | :--- | :--- | :--- |
| **ESP32** | `SD:/metrics.csv` | サイクル時間, Wi-Fi信号強度(RSSI) | SDカードをPCに読み込む |
| **Pi** | `./edge_metrics.csv` | エッジ処理時間, 推論結果 | SCPまたはUSBメモリ等 |
| **Cloud** | `./cloud_metrics.csv` | クラウド処理時間, 通知遅延 | SCPまたは直接コピー |

## 4. 分析手順 (論文用データ算出)

回収した3つのCSVファイル (`metrics.csv`, `edge_metrics.csv`, `cloud_metrics.csv`) を `CycleID` をキーとして結合（ExcelやPython pandas等を使用）し、以下の数値を算出します。

### 4-1. 処理時間 (Latency)

* **エッジ側処理時間**: `metrics.csv` の `Total_ms` (Wake〜Sleep)
* **通信時間**: `metrics.csv` の `Wifi_ms` + `Upload_ms`
* **サーバー処理時間**: `edge_metrics.csv` の `total_inference_ms` (Pi) vs `cloud_metrics.csv` の `total_inference_ms` (Cloud)
* **エンドツーエンド遅延**: ESP32の撮影開始 〜 External Serverのメール送信 (`email_time_ms` 完了時刻) までの差分

### 4-2. 通信品質と電力

* **RSSI vs 転送成功率**: `metrics.csv` の `RSSI_dBm` と、Pi側で画像が受信できたかの相関。
* **消費電力 (推定)**:
  * `Total_ms` (稼働時間) × 平均消費電力 (別途ハードウェア測定値を使用) で、1サイクルあたりの消費エネルギー(J)を算出。

### 4-3. 検出精度 (Accuracy) & 削減率

1. **正解ラベル付け**:
    * 回収した画像 (`Pi/uploads/` または `ESP32/archive/`) を目視確認し、「動物あり(1)/なし(0)」の正解ラベルを手動で記録する。
2. **混同行列**:
    * Piの推論結果 (`edge_metrics.csv` の `animal_count` > 0) と正解ラベルを比較。
    * TP, FP, TN, FN を算出。
3. **削減率 (Reduction Ratio)**:
    * (Piで転送しなかったサイクル数) / (全サイクル数) × 100%

## 5. 次のアクション

まず **5サイクル程度の予備実験** を行い、全てのCSVにデータが正しく記録されているか確認してください。
問題なければ本番計測を行ってください。
