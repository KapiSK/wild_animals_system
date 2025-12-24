# カメラエッジ (ESP32) 実装計画 (v3)

## Goal Description

ESP32カメラエッジの機能を大幅に強化し、堅牢なトレイルカメラシステムを構築する。
ネットワーク切断時でもデータをSDカードにバッファリングし、接続回復時に再送する機能(Offline Buffering)や、昼夜に応じたハードウェア制御(Day/Night Mode)を実装する。
**追加要件**: GPSモジュール (GT-502MGG-N) を使用して、正確な時刻同期と位置情報の記録を行う。

## User Review Required
>
> [!WARNING]
> **Missing Implementations detected**
> ファイル `esp/camera.ino` 内の `elog` 名前空間にある関数 (`tsSuffix`, `countLines`, `rotate`, `appendWithRotate`) がプレースホルダー (`/* ... */`) のままになっています。コンパイルを通すにはこれらの実装が必要です。

> [!IMPORTANT]
> **GPS Wiring Proposal**
> XIAO ESP32S3の空きピン **D6 (RX)** と **D7 (TX)** をGPS接続に使用することを提案します。
>
> - GPS TX --> ESP32 D7 (GPIO 44)
> - GPS RX <-- ESP32 D6 (GPIO 43) (設定変更が必要な場合のみ接続)
> - GPS GND --> GND
> - GPS VCC --> 3.3V or 5V (モジュールの電圧に合わせてください)

## Current Implementation Details (Based on `es_cam.ino`)

(v2と同様の内容は省略)

## Proposed Changes

### 1. Fix Missing Logging Logic

#### [MODIFY] [esp/camera.ino](file:///c:/Users/kapib/vscodegit/wild_animals/test2/esp/camera.ino)

- `elog::tsSuffix`, `elog::countLines`, `elog::rotate`, `elog::appendWithRotate` の実装を追加する。

### 2. GPS Integration (New)

#### [MODIFY] [esp/camera.ino](file:///c:/Users/kapib/vscodegit/wild_animals/test2/esp/camera.ino)

- **Serial Interface**: HardwareSerial (Serial1) を D6/D7 ピンで初期化。
  - `Serial1.begin(9600, SERIAL_8N1, 44, 43);` (RX=44, TX=43)
- **NMEA Parser**:
  - `$GPRMC` または `$GNRMC` センテンスをパースする軽量ロジックを追加。
  - **Time Sync**: UTC時刻を取得し、システム時刻 (`settimeofday`) を更新（起動時および定期的に補正）。
  - **Location**: 緯度経度を取得し、メタデータとして保存（Exifへの埋め込み、またはログへの記録）。
- **Wakeup Sequence**:
  - GPSの測位には時間がかかるため、起動直後にGPS電源を入れ、撮影と並行して測位を試みる、または一定時間待機するロジックを検討する必要がある。
  - **省電力方針**: 毎回測位するとバッテリー消費が激しいため、「1日1回同期」や「コールドブート時のみ同期」などの運用を推奨。基本はRTCタイマーで運用。

## Verification Plan

### Manual Verification

- GPSモジュールからのNMEAデータ受信確認。
- システム時刻がGPS時刻に同期されることの確認。
- 撮影画像のログ等に正しい位置情報・時刻が記録されること。
