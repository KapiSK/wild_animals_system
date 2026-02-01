# 実装計画: GPS機能の廃止

## 目標

エッジカメラ (ESP32-S3) のファームウェアからGPSに関連する機能を完全に削除する。これに伴い、時刻同期機能も削除される（必要であれば別途NTP等を検討するが、今回は削除のみ行う）。

## 変更内容

### `esp/camera/camera.ino`

#### [DELETE] GPSピン定義

- `namespace hw` 内の以下の定義を削除する。
  - `PIN_GPS_RX`
  - `PIN_GPS_TX`

#### [DELETE] GPS制御ロジック

- `namespace gps` ブロック全体を削除する。
  - `BAUD_RATE`
  - `SYNC_TIMEOUT_MS`
  - `parseRMC()`
  - `begin()`
  - `pollAndTimeSync()`

#### [MODIFY] `setup()` 関数

- 以下の呼び出しを削除する。
  - `gps::begin();`
  - `gps::pollAndTimeSync();`

## 検証計画

- コード変更後、静的解析（目視）にて削除漏れや構文エラーがないか確認する。
- 物理的なGPSモジュールが接続されていなくても動作することを確認する（今回はコード削除のみ）。
