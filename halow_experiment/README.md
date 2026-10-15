# Wi-Fi HaLow 画像伝送実験

`HaLow性能評価_実験手法と実装計画.md`（2026-10-08）のE0～E4に使う独立した実験用プログラムです。
対応Pythonは3.9以上。PiのLinuxで実測し、WindowsでもローカルE0を実行できます。
実機JPEG・HaLow機材・ドライバは同梱していません。ローカルデモの結果は無線性能の測定値ではありません。

## 1. まずPC上で動作確認

このディレクトリへ移動して実行します。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python demo.py
```

デモは専用ディレクトリに合成JPEGを3枚生成し、ローカルHTTP受信・3イベント送信・ファイル照合・グラフ作成まで実行します。
出力先は `results/LOCAL_DEMO_*/`。グラフは `analysis/summary.png`、集計は `analysis/summary.json` です。
デモ用サーバは処理終了時に停止します。

## 2. 実機を準備

対応HaLow HATを装着したPiを2台使い、受信側AP、送信側STAにします。
先に型番、HAT枚数、Pi機種、対応OS、指定アンテナ、ドライバ・ファームウェア版を確認してください。
メーカーの機種別手順で接続を確立してから、本プログラムを起動します。
このコードは無線設定・OS・電源制御を変更しません。型番未確認のまま他モデルの設定を流用しないでください。

BC-11AH-A2の無線設定は[メーカー案内](https://www.beatcraft.com/labs/2026/03/bc-11ah-a2-2.html)と購入品の資料で照合します。
添付計画のJP、指定アンテナ、Duty制御を有効にする方針を維持してください。
`config.yaml` の送信出力・Duty等は**測定条件の記録欄**であり、無線へ適用する設定ではありません。

IP例：受信側 `192.168.200.1/24`、送信側 `192.168.200.2/24`。管理Ethernetは別サブネットにします。

```bash
ip -br addr
ip route get 192.168.200.1 from 192.168.200.2
iw dev
ethtool -i wlan0
ping -c 20 -I 192.168.200.2 192.168.200.1
```

`wlan0` は例です。実際のHaLowドライバ・IF名を確認して `sender.interface` を変更してください。
送信元IPを固定し、各イベント前に経路のIF名を照合します。IF名自体がHaLowであるかは実機で確認が必要です。
経路確認失敗は送信せず失敗試行として残します。接続不能地点を集計から除外しません。
測定中の経路変更は避け、前後の全IFカウンタも点検します。

両Piへこのディレクトリをコピーし、各Piで以下を実行します。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# E1にはOSのパッケージ管理でiperf3を導入してください。
```

依存パッケージは互換範囲指定です。実測前に `.venv/bin/python -m pip freeze > versions.txt` を保存し、
両端の環境を固定します。`hardware` に型番・版・アンテナ・時計同期状態を記入します。

## 3. 実画像コーパス

送信Piの `corpus/` に昼・夜・草木等のJPEGを置きます。初期ファイル名は
`day.jpg`、`night.jpg`、`vegetation.jpg`。別名なら `sender.image_ids` も変更します。

```bash
.venv/bin/python prepare_corpus.py corpus
```

manifestに解像度・実バイト数・SHA-256を記録します。元JPEGを改変しません。
計測条件ごとに同じ画像を使います。画像容量を変える場合は別コーパス／別condition_idにします。
変更されたファイルは送信前照合で検出します。

## 4. E0 / E2：受信と30イベント送信

受信Pi：

```bash
.venv/bin/python server.py --config config.yaml
```

送信Pi：

```bash
.venv/bin/python run_experiment.py --config config.yaml
```

全パスは設定ファイルの位置が基準です。実行ごとに新しい `results/run_<UUID>/` を作成します。
送信前に `jobs/000001.json` 等を保存し、結果を `trials.jsonl` に追記します。
強制終了で結果がないjobも解析時に `interrupted_unknown` として試行分母に残します。
まだ開始していない予定試行は分母に含みません。Ctrl+Cは実行中の試行を記録して停止します。

HTTPの `/upload` へJPEGバイナリを順番に送り、`/complete` で全画像のサイズ・ハッシュを再確認します。
1イベント内の接続再利用が既定です。`reuse_connection: false` で各リクエストを新規接続にします。
イベント間では接続を閉じます。初期のアプリ再送は0回。別条件として `max_retries` を変更します。
再送は通信例外だけに適用し、競合・不正応答では止めます。
親プロセスの単調時計で全体期限を管理し、期限到達で送信子プロセスを終了します。
`complete_ms` は子プロセス起動と送信準備を含む送信呼出開始から完了応答までです。
`connect_ms` は無線開始の時点を観測できないためnullです。TCP接続時間を無線接続時間として扱いません。

有線比較は設定を別ファイルへコピーし、host/source_ip/interface/condition_idを有線用に変更します。
PCのlocalhost以外で `enforce_route` を安易に無効化しないでください。

## 5. E1：TCP / UDP

受信PiでHTTPとは別ターミナルから：

```bash
iperf3 -s -B 192.168.200.1
```

送信Pi：

```bash
.venv/bin/python run_iperf.py --config config.yaml
.venv/bin/python run_iperf.py --config config.yaml --udp 100K
```

各条件3回、30秒が初期値です。生JSONと受信側統計を `results/iperf_*/` に保存します。
100Kの結果を確認してから250K、500K、1Mと**1負荷ずつ**測定します。
受信速度が増えず損失が増える条件で停止してください。自動の全負荷掃引はしません。
受信側統計を判別できないiperf版ではnullとし、生JSONを確認します。
実機の `iperf3 --help` と[公式オプション資料](https://software.es.net/iperf/invoking.html)で対応を確認します。
Duty停止区間は除外しません。測定長を変えるときは別条件にします。

## 6. E3：屋外測定

`config.yaml` を条件ごとにコピーし、`condition_id` を一意にします。
初めは高さ2mと対応チャネル幅を固定し、10→50→100→200→300→500mで各30イベント。
距離移動・無線設定は人が実施し、その後に各設定ファイルでrunを開始します。
重要条件・限界付近では `trials: 100` 以上。日や試行順を変えて繰り返します。
`site`、天候・植生・向き（notes）、高さ、チャネル、幅、出力、Duty実設定を記録してください。
設置写真・位置情報・メーカー設定の控え・versions.txtは該当runへ保存します。

`before.json` / `after.json` は全IF通信量、ドライバ、時計同期等の生情報です。
`radio.jsonl` に `iw station dump` の時系列を保存します。ドライバ非対応はエラーを残し、
RSSI/MCSを0で代用しません。正式な値・方向・単位の抽出は型番／ドライバの出力確認後に合わせます。
受信側でも必要に応じ `collect_radio.py --config config.yaml --output radio_rx.jsonl --samples 0` を起動します。

## 7. 集計

測定後、受信Piの `received/` 全体をPCの `received_snapshot/` 等へコピーします。
途中のコピーや欠けたスナップショットを渡すと受信失敗と誤判定するため、転送停止後に完全な控えを使います。

```bash
python analyze.py results/run_実際のID --received received_snapshot --output results/analysis_001
```

複数runは空白区切りで指定します。出力ディレクトリは毎回新しい名前にしてください。
画像受信率・イベント受信率・完了応答到達率、Wilsonの95%信頼区間、失敗数、
成功時間の中央値・p95、距離／容量／条件比較グラフを出力します。日付（UTC）・場所別集計も作成します。
`--received` を省略すると受信率はnullです。送信側タイムアウトから画像喪失を断定しません。
ファイルが全て揃っていてACKがない場合は `ack_lost_after_storage` に計上します。
これは最終的な保存状態の照合であり、受信側での期限内保存を証明するものではありません。
期限内成功率は送信側で完了応答を期限内に受けた割合です。
画像の独立性・連続試行の独立性は保証されないため、CIは探索的な二項近似です。
100/100成功でも99%以上の信頼性保証にはなりません。

## 8. E4：長期運用と電力測定

常時接続の24時間の例は `trials: 73`、`interval_s: 1200`。開始間隔が20分で、
最初から最後の開始まで24時間です。過負荷試験は別condition_idで間隔を短くします。
元画像と失敗jobは削除されません。後日の再送は同じイベントIDを保持します。

```bash
python sender.py --config config.yaml --job results/run_ID/jobs/000001.json --output results/retry_000001.json
```

再送の出力は元trialと分離し、基礎測定結果を上書きしません。再送後の受信スナップショットを
基礎測定の解析へ混ぜると成功率が変わるため、**再送前に受信スナップショットを保存**してください。

電源を実際に切る間欠運用、PIC/PIR制御、ESPからの画像取得は機器固有の接続が必要です。
現段階では自動制御を実装していません。電源投入～IP通信可能～停止の時点を外部ロガーで記録し、
撮影したJPEGをcorpusへ搬入したうえで同じ送受信を使ってください。
`power_mode: intermittent` と書くだけでは電源は切り替わりません。

電流ロガーのCSVを次の形へ変換します。時刻は各イベント内の単調な秒、電流はA（mAは1000で割る）です。
成功／失敗を選別せず、電源投入から停止まで、同じdevice_id/cycle_idを付けます。

```csv
device_id,cycle_id,time_s,voltage_v,current_a
cam01,run_ID_000001,0,5.0,0.2
cam01,run_ID_000001,0.1,5.0,0.5
cam01,run_ID_000001,0.2,5.0,0.3
```

```bash
python energy.py power.csv --output results/energy_001.json
```

台形積分によるイベントJと総Jを出力します。欠測区間・測定レンジ・標本化周期は別途点検してください。
電力と無線接続時間の自動取得、および電池寿命推定は未実装です。

測定済みの電力量は `analyze.py ... --energy results/energy_001.json` で試行へ結合し、
失敗を含む測定総電力量と条件別グラフ `power_connection.png` を作成できます。
無線開始からIP疎通までを同一機器の単調時計で測定できた場合は、次のJSONを作り
`--connections connections.json` で読み込めます。未測定のイベントはnullのままです。

```json
{"events": [{"device_id": "cam01", "cycle_id": "run_ID_000001", "connect_ms": 2300.0}]}
```

上記値は入力形式の例で、実測値ではありません。

## 保存と測定上の制約

- 同一イベント・画像番号・内容の再送は既存JPEGを再利用し、異なる内容は409競合です。
- 一時ファイルへ書き、検証後に正式名へ置換します。既定はclose/renameまでの保存確認です。
- `server.fsync: true` はファイルとLinuxの画像格納ディレクトリをfsyncする比較条件です。
  新規親ディレクトリ・媒体キャッシュを含む電源断耐性は保証しません。耐電源断試験が別途必要です。
- 実験用HTTPサーバです。認証・TLSはなく、管理された実験ネットワークで使います。
- 同時クライアントの書込みはロックで直列化します。多カメラ負荷の公平性評価は対象外です。
- 試行間の再接続、OSスケジューリング、プロセス起動、ハッシュと保存処理もアプリ測定に含まれます。
  有線E0で測定系の寄与を確認してください。
