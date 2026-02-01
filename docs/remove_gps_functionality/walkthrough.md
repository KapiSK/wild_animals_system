# Walkthrough: GPS機能の廃止

## 変更されたファイル

- `esp/camera/camera.ino`

## 実施した変更

エッジカメラのファームウェアからGPS機能を削除しました。

1. **ピン定義の削除**: `hw::PIN_GPS_RX`, `PIN_GPS_TX` を削除。
2. **ロジックの削除**: `namespace gps` 以下のNMEA解析、初期化、時刻同期処理を削除。
3. **呼び出しの削除**: `setup()` 関数内でのGPS初期化と同期呼び出しを削除。

## 検証結果

- `camera.ino` 内を "GPS" で検索し、関連コードが完全に削除されていることを確認しました。
