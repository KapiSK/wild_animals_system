# 実装計画: 外部サーバー処理時間の計測

## 目的

外部サーバー (`original_server/server.py`) が1サイクル（3枚の画像）を処理するのにかかる時間を計測し、記録する。
各主要ステップ（保存、推論、集約・通知）の所要時間と、サイクルの合計時間をミリ秒単位で把握できるようにする。

## 変更内容

### `original_server/server.py`

#### [MODIFY] [server.py](file:///c:/Users/kapib/vscodegit/wild_animals/test2/original_server/server.py)

以下のステップに計測用のコードを追加する：

1. **画像の受信と保存 (`upload_image`)**:
    * リクエスト受信時刻 (`receive_start`) を記録。
    * ファイル保存完了までの時間を計測 (`save_duration`)。
    * これらの時間情報をバックグラウンドタスク `process_and_notify` に渡す。

2. **推論 (`process_and_notify`)**:
    * YOLOv5/MegaDetector の推論 (`model(image_path)`) にかかる時間を計測 (`inference_duration`)。
    * `cycle_manager.add_result` にタイミング情報を渡す。

3. **サイクル管理と集約 (`CycleManager`)**:
    * **データ構造の変更**:
        * `self.cycles[cycle_id]` に `start_time` (最初の画像の受信時刻) と `timings` (各画像の処理時間リスト) を追加。
    * **合計時間の計算 (`process_cycle`)**:
        * サイクル処理完了時（3枚揃ってメール送信完了後）に終了時刻を記録。
        * 合計時間 = 終了時刻 - 開始時刻。
        * 内訳（合計保存時間、合計推論時間、メール送信時間）を計算。
    * **ロギング**:
        * `[PERF]` タグを使用して、サイクルID、合計時間、内訳をログ出力する。

## 検証計画

### 自動テスト

`pi/verify_perf.py` をベースにしたテストスクリプト `original_server/verify_perf_external.py` を作成・実行する。

1. ローカルで `server.py` を起動する (`uvicorn original_server.server:app ...`)。
2. テストスクリプトから、同じサイクルIDを持つ3枚の画像を順次アップロードする。
3. `server.log` を確認し、以下のログが出力されていることを確認する：
    * `[PERF] Cycle ... Finished. Total Time: ...ms`
    * `[PERF] Breakdown: Save=...ms, Inference=...ms, Email=...ms`

### 手動検証

* ログファイルを目視確認し、計算された時間が妥当（負の値になっていない、極端に短すぎない/長すぎない）であることを確認する。
