# 実装計画: 処理時間の計測と記録 (ESP32)

## 目的

ESP32カメラの1サイクルの総処理時間と、各ステップ（撮影、Wi-Fi接続、アップロード等）の内訳を計測し、ログファイル (`esp.log` / `esp_chunk.log`) に記録する。これによりシステムのボトルネック分析を可能にする。

## 変更内容

### `esp/camera/camera.ino`

1. **時間計測用変数の追加 (Global or Namespace)**
    * `g_tWake`: 起床時刻 (既存)
    * `g_tCapStart`, `g_tCapEnd`: 撮影シーケンス開始・終了
    * `g_tWifiStart`, `g_tWifiEnd`: Wi-Fi接続開始・終了
    * `g_tUploadStart`, `g_tUploadEnd`: アップロード処理開始・終了
    * `g_tTotalEnd`: スリープ直前の時刻

2. **計測ポイントの挿入**
    * **撮影**: `beginCapture()` の前後
    * **Wi-Fi**: `initWiFi()` の前後
    * **アップロード**: `uploadPendingData()` の前後

3. **ログ出力の追加**
    * スリープに入る直前 (`goDeepSleepNow` または `setup` 末尾) に以下のフォーマットでログ出力する。
    * `[PERF] Cycle: <ID>, Total: <ms>, Cap: <ms>, Wifi: <ms>, Upload: <ms>, <Other...>`

## 検証計画

- `esp/camera/camera.ino` をコンパイル (今回はコード修正のみ)。
* `setup()` の最後にログ出力コードが追加されていることを確認する。
