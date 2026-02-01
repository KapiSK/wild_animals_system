# 修正内容の確認: 外部サーバー処理時間の計測

## 変更概要

外部サーバー (`original_server/server.py`) に、1サイクル（3枚の画像）の処理時間を計測し、ログ出力する機能を追加しました。

### 主な変更点

1. **`CycleManager` の拡張**:
    * サイクルの開始時刻 (`start_time`) を記録するように変更。
    * 各画像の処理時間（受信〜保存、推論）を収集する仕組みを追加。
    * サイクル完了時に、合計時間と内訳（保存、推論、メール送信）を計算。

2. **`process_and_notify` 関数の変更**:
    * 引数に `receive_start` と `save_duration` を追加。
    * 推論にかかる時間を計測。
    * 計測した時間を `CycleManager` に渡す。

3. **パフォーマンスログの出力**:
    * サイクル完了時に `[PERF]` タグ付きで計測結果を出力します。

## 検証結果

自動検証スクリプト `original_server/verify_perf_external.py` を作成しました。
現在の環境ではライブラリ (`fastapi` 等) が不足しているため実行できませんでしたが、コードの構文チェックは完了しています。

### 手動検証手順

以下の手順で検証を行ってください。

1. **依存ライブラリのインストール**:

    ```bash
    cd original_server
    pip install -r requirements.txt
    ```

2. **サーバーの起動**:

    ```bash
    python server.py
    ```

3. **検証スクリプトの実行**:
    別のターミナルを開き、テスト用画像（`test.jpg` など）を用意してから以下を実行します。
    ※ `test.jpg` がない場合は、`pi/test.jpg` などをコピーしてください。

    ```bash
    cd original_server
    # テスト画像をコピー (例)
    copy ..\pi\test.jpg .\test.jpg
    
    python verify_perf_external.py
    ```

4. **ログの確認**:
    `original_server/server.log` に以下のようなログが出力されていることを確認します。

    ```text
    [PERF] Cycle EXT_PERF_TEST Finished. Total Time: 1234.56ms
    [PERF] Breakdown: Save=100.00ms, Inference=800.00ms, Email=300.00ms
    ```
