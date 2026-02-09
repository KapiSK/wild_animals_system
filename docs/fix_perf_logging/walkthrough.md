# ログ記録の修正 (ESP32)

## 概要

ESP32カメラにおいて、処理時間（Performance Metrics）などの重要な情報がログファイル (`esp.log`, `esp_chunk.log`) に記録されていない問題に対処しました。

## 変更内容

### `esp/camera/camera.ino`

`goDeepSleepNow` 関数（スリープ移行処理）の最後に、メモリ上のログバッファに残っているデータをSDカードへ書き出す処理を追加しました。

```cpp
    // ... metrics.csv writing ...

    // --- Flush Remaining Logs (Wifi, Upload, Perf) ---
    // これまでのログ(Wi-Fi接続、アップロード、パフォーマンス計測結果など)を
    // ファイルに書き出してからスリープする
    String remainingLogs = makeEspLogChunkForCurrentCycle();
    if (remainingLogs.length() > 0) {
        // 1. メインのログファイル (/logs/esp.log) に追記
        updateEspLogAppendRotate(remainingLogs);

        // 2. サイクルアーカイブ (/archive/[CID]/esp_chunk.log) に追記
        if (g_cycleId.length() > 0) {
            String logChunkPath = "/archive/" + g_cycleId + "/esp_chunk.log";
            File file = SD.open(logChunkPath, FILE_APPEND); // 追記モード
            if (file) {
                file.print(remainingLogs);
                file.close();
                LOG_PRINTF("[SAVE] Flushed remaining logs to: %s\n", logChunkPath.c_str());
            } 
            // ...
        }
    }

    LOG_PRINTF("[SLEEP] Entering %u ms cooldown...\n", param::SLEEP_COOLDOWN_MS);
    // ...
```

## 効果

これにより、以下の情報が確実にログファイルに保存されるようになります。

1. **Wi-Fi 接続ログ**: 接続成功/失敗、IPアドレス、RSSIなど
2. **アップロードログ**: 各ファイルの送信結果
3. **パフォーマンス計測結果**: `[PERF] Cycle: ..., Total: ... ms` という形式での処理時間内訳

※ `metrics.csv` への記録は以前から行われていましたが、テキストログ (`esp.log`) にも詳細が残るようになります。
