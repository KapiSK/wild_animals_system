# 統計ページ向けデータ収集機能の実装計画

将来の統計ページ開発に備え、カメラでの検知イベント発生時に「カメラ名、気温、日時、動物の種類」を永続的に記録・蓄積する機能を実装します。

## 背景と要件
- **要件**: 後からデータを参照できるよう、イベント発生時のメタデータ（カメラ名、気温、日時、動物）をまとめて保存する。
- **現状**: 
  - Satos（統合サーバ）などからアップロードされる際、メール本文などから気温（Temperature）が抽出され、`/api/telemetry` エンドポイント経由で最新のステータスとしてクラウドサーバに保持されています。
  - 動物の種類（labels）、日時（cycle_time）、カメラ名（camera_id）はすでに推論完了時のイベントメタデータとして算出されています。

## Proposed Changes

### original_server

#### [MODIFY] [server.py](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py)
`CycleManager.process_cycle` メソッド（1050〜1080行目付近）を修正し、以下の処理を追加します。
1. **気温データの取得**: 最新のテレメトリデータ（`load_telemetry()`）から対象カメラの `temperature` を取得します。
2. **メタデータへの気温追加**: 既存の `event_metadata` 辞書に `"temperature": temperature` を追加し、イベントごとの JSON にも気温を残します。
3. **統計用CSVへの追記**: `statistics.csv` を新たに作成・追記する処理を追加します。
   - カラム構成案: `timestamp,camera_id,temperature,labels,target_count`
   - 例: `2026-06-02T15:00:00,CAM_01,23.5,person|dog,2`

> [!NOTE]
> - 気温データが送信されていないカメラ（例: 現状の Pi など）の場合は、気温の項目は空欄（空文字）として記録されます。
> - 今後データベースに移行する可能性も考慮し、まずは最も汎用的で扱いやすい CSV (`statistics.csv`) 形式で時系列データを追記・蓄積していくアプローチを取ります。

## User Review Required

> [!IMPORTANT]
> 1. データの保存先として、ルートディレクトリへの `statistics.csv` の追記という方式でよろしいでしょうか？（より高度な SQLite 等を使用することも可能です）
> 2. `statistics.csv` に保存する日時（timestamp）は、画像の撮影日時（`cycle_time`）と、クラウドでの処理完了日時（`isoformat`）のどちらを優先して記録するべきでしょうか？（プランでは処理完了日時を想定しています）

## Verification Plan

### Manual Verification
- 実際にカメラから画像（およびダミーのテレメトリ温度データ）をアップロードまたは処理させます。
- `statistics.csv` が作成され、指定したカラムに正しいデータ（カメラ名、気温、日時、動物）が追記されていることを確認します。
- `event_metadata`（JSONファイル）内に `temperature` フィールドが保存されていることを確認します。
