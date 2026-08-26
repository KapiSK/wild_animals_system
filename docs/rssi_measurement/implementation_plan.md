# RSSI連続測定および風景記録機能の実装計画

ユーザーからの要望である「エッジカメラを用いたWi-FiのRSSI測定、変化時の風景撮影と記録、LEDによる通知」に加え、新たに**BLE（Bluetooth Low Energy）を用いたリアルタイム状態通知機能**を追加します。

## Goal
現在の `esp/rssi_mapper/rssi_mapper.ino` にBLEサーバー機能を組み込み、スマートフォン（LightBlueアプリなど）からリアルタイムに接続状況やRSSI、撮影ステータスを確認できるようにします。

## Proposed Changes

### `esp/rssi_mapper/rssi_mapper.ino`
以下のBLE関連の実装を追加します。

1. **BLEライブラリのインクルードと設定**:
   - `<BLEDevice.h>`, `<BLEServer.h>`, `<BLEUtils.h>`, `<BLE2902.h>` の追加。
   - サービスUUIDおよびキャラクタリスティックUUID（Notify用）の定義。
2. **BLE初期化処理 (`setup` 内)**:
   - BLEデバイス名の設定（例: `ESP-RSSI`）。
   - BLEサーバーの作成と、接続状態を管理するコールバック関数の登録。
   - Notify（通知）プロパティを持ったキャラクタリスティックの作成とサービスの開始。
   - アドバタイズ（他の機器からの発見許可）の開始。
3. **通知ロジック (`loop` 等の各処理内)**:
   - Wi-Fi切断・再接続のタイミングで `[ERR] WiFi Disconnected` 等の文字列をBLEで通知。
   - 定期的なRSSI測定時（例: 1秒ごと）に `[OK] RSSI: -65dBm` 等の文字列を通知。
   - 写真撮影と記録成功時に `[REC] Photo Saved (RSSI: -70)` 等の文字列を通知。

## User Review Required
- **デバイス名**: Bluetoothでスキャンした際に表示される名前は `ESP-RSSI` としますが、よろしいでしょうか？
- 上記の実装方針で問題なければ、このままコーディングを進めます。

## Verification Plan

### Manual Verification
1. `esp/rssi_mapper/rssi_mapper.ino` をESP32に書き込んで起動する。
2. スマホでLightBlueアプリを開き、`ESP-RSSI` に接続する。
3. 提供されているキャラクタリスティックの `Listen for notifications` を有効にする。
4. 画面上に1秒ごとのRSSI値や、Wi-Fi切断時のエラーメッセージがリアルタイムに表示されることを確認する。
5. 移動してRSSIを変化させ、撮影が行われた際に通知が表示されることを確認する。
