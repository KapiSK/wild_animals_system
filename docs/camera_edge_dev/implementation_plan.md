# カメラエッジ (ESP32) 実装計画 (v2)

## Goal Description

ESP32カメラエッジの機能を大幅に強化し、堅牢なトレイルカメラシステムを構築する。
ネットワーク切断時でもデータをSDカードにバッファリングし、接続回復時に再送する機能(Offline Buffering)や、昼夜に応じたハードウェア制御(Day/Night Mode)を実装する。

## User Review Required
>
> [!WARNING]
> **Missing Implementations detected**
> ファイル `esp/camera.ino` 内の `elog` 名前空間にある関数 (`tsSuffix`, `countLines`, `rotate`, `appendWithRotate`) がプレースホルダー (`/* ... */`) のままになっています。コンパイルを通すにはこれらの実装が必要です。

## Current Implementation Details (Based on `es_cam.ino`)

### 1. Cycle & State Management

- **Wakeup Sources**: PIR Motion Sensor (GPIO 1) or Timer (20 min).
- **Cold Boot Handling**: If wake cause is Power-on, immediately sleep to save battery.
- **Sequence Number**: Persisted in `/seq.txt` on SD card.
- **Cycle ID**: `[MAC Address]-[SequenceNumber]` (e.g., `AABBCCDDEEFF-00000001`).

### 2. Capture Sequence

- **Resolution**: UXGA (1600x1200).
- **Burst Mode**: Takes 4 shots.
  - Shot 1: Discarded (AE/AWB stabilization).
  - Shot 2-4: Saved to SD card `/archive/[CycleID]/img[1-3].jpg`.
- **Day/Night Logic**:
  - **Sensor**: CDS Photoresistor on GPIO 5.
  - **Night Action**: Flash LED ON (GPIO 6), Motor Forward.
  - **Day Action**: Flash LED OFF, Motor Reverse.

### 3. Data Storage & Logging

- **Structure**:

    ```text
    /
    ├── seq.txt                 # Current Sequence Number
    ├── logs/
    │   ├── uploaded_cids.txt   # List of uploaded Cycle IDs
    │   ├── esp.log             # Rotating system log
    │   └── log_YYYYMMDD.txt    # Daily log
    └── archive/
        └── [CycleID]/          # Data for specific cycle
            ├── img1.jpg
            ├── img2.jpg
            ├── img3.jpg
            └── esp_chunk.log   # Log messages for this cycle
    ```

- **Garbage Collection**:
  - Triggered before sleep.
  - Deletes oldest cycles if count > 100 or Free Space < 30MB.

### 4. Upload Logic

- **Protocol**: HTTP POST (Multipart-like manual implementation or standard).
- **Target**: Raspberry Pi Edge Server (`wild-animal.local`).
- **Discovery**: mDNS to resolve IP.
- **Retry Mechanism**:
  - Scans `/archive` folder.
  - Prioritizes **Recent Cycles** (Current cycle + last 3 cycles).
  - Skips already uploaded cycles (checked against `/logs/uploaded_cids.txt`).
  - Uploads `img1-3.jpg` and `esp_chunk.log`.
- **Integrity**: Sends `X-Content-SHA256` header for validation.

### 5. Power Management

- **Deep Sleep**: Enters deep sleep after operations.
- **Cooldown**: 30s mandatory wait before sleep to prevent rapid loops.
- **LED Indications**:
  - **Solid ON**: Boot/Idle/Connected.
  - **Slow Blink**: Connecting/Resolving.
  - **Fast Blink**: Capturing/Uploading.
  - **Error Blink**: Hardware/Mount failure.

## Proposed Changes

### Fix Missing Logging Logic

#### [MODIFY] [esp/camera.ino](file:///c:/Users/kapib/vscodegit/wild_animals/test2/esp/camera.ino)

- `elog::tsSuffix`, `elog::countLines`, `elog::rotate`, `elog::appendWithRotate` の実装を追加する。

## Verification Plan

### Manual Verification

- コンパイル成功の確認。
- 実機での動作確認 (ログのローテーション、SDカードへの書き込み、アップロードの再試行動作)。
