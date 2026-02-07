# Edge Server ローカルモード実装計画

クラウドへの通信を行わない「ローカルモード」を実装します。これにより、インターネット接続がない環境や、クラウド連携を意図的に切りたい実験での運用が容易になります。

## 変更内容

### [pi/main.py](file:///c:/Users/kapib/vscodegit/wild_animals/test2/pi/main.py)

1. **環境変数の追加**:
    * `LOCAL_MODE` (デフォルト: `False`) を読み込むように変更。
2. **転送ロジックの変更**:
    * `forward_cycle` 関数内で `LOCAL_MODE` が `True` の場合、即座にログを出力してリターンする処理を追加。
    * `edge_metrics.csv` の `forwarded` フラグにもローカルモードであることを反映（常に False になるが、ログにその旨残すと親切かもしれない）。

## 検証方法

### 手動検証

1. `.env` ファイル（または環境変数設定）に `LOCAL_MODE=True` を追加する。
2. サーバーを起動する。
3. `/upload` エンドポイントに画像を3枚送信し、サイクルを完了させる。
    * 期待動作: `Forwarding...` ログが出ず、代わりに `Local mode enabled. Skipping forward.` 等のログが出ること。
    * 期待動作: `edge_metrics.csv` にレコードが追加されること。
