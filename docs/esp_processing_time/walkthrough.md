# Walkthrough: 処理時間の計測と記録 (ESP32)

## 変更されたファイル

- `esp/camera/camera.ino`

## 実施した変更

ESP32カメラの動作サイクルにおける各ステップの処理時間を計測し、ログ出力する機能を追加しました。

1. **時間計測用変数の追加**: `g_tCapStart`, `g_tWifiStart` などのグローバル変数を追加。
2. **計測ポイントの挿入**: `beginCapture`, `initWiFi`, `uploadPendingData` 関数の開始・終了時刻をこれらの変数に記録。
3. **ログ出力**: Deep Sleepへ移行する直前 (`goDeepSleepNow`) に、以下のフォーマットでパフォーマンスログを出力するようにしました。

    ```text
    [PERF] Cycle: AABBCC-001, Total: 15300 ms, Cap: 2500 ms, Wifi: 5000 ms, Upload: 4500 ms
    ```

## 検証結果

- `camera.ino` 内に `[PERF]` タグを含むログ出力行が存在することを確認しました。
