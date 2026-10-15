# カメラ → FTP → Pi → SFTP → クラウド

現在のカメラの既定値はSFTPです。**両区間をSFTPにする構成は [カメラSFTP手順](camera_sftp_delivery.md)** を参照してください。
このページのカメラ→Pi部分は、FTPを明示的に選択する場合の手順です。

画像とカメラログをPiへFTPで送り、Piが転送対象と判定した画像をクラウドへSFTPで送ります。
既存のHTTP受信、推論、永続キュー、重複排除、画面・通知は継続して使います。
カメラログの保存先はPiです。この変更ではログをクラウドへ転送しません。

```mermaid
flowchart LR
  Camera[ESP32 / SD] -->|FTP 2121 + passive| FTP[Pi FTP受信]
  FTP -->|同じPi内のHTTP| Pi[Pi保存・推論・送信キュー]
  Pi -->|SFTP / SSH 22| SSH[クラウド OpenSSH]
  SSH --> Inbox[受信フォルダー監視]
  Inbox -->|同じクラウド内のHTTP| Cloud[保存・推論・通知]
```

FTP/SFTPの受信ファイルは、各ホスト内の `127.0.0.1:8000` にある既存APIへ取り込みます。
画像検証・DB登録を既存処理に集約するためです。機器間の画像転送はFTP/SFTPです。
既存APIを止めると、FTP/SFTPファイルは到着しても受領確認は発行されません。

## 送信完了の条件

1. `incoming/<ランダムID>.data.part` にバイナリを送信し、`.data` へrename。
2. ファイル名・サイクルID・画像番号・サイズ・SHA-256を含むJSONを `.json.part` に送信し、`.ready` へrename。
3. 受信サービスが `.ready` のみを取り込み、APIでハッシュ・画像内容・保存・DB登録を確認。
4. `receipts/<ランダムID>.json` を原子的に公開。送信側が `status=ok`、`receipt_id`、`sha256` を照合。

FTPの226応答やSFTPのアップロード成功だけでは完了扱いにしません。
受領確認を取得できない場合、カメラはSD上に画像を残し、Piは永続キューから再送します。
HTTPとFTP/SFTPで同じ画像を送っても、共通のサイクルID・画像番号で重複排除します。
同じIDで異なる画像はエラーになり、送信元のデータが残ります。

画像は最大16MiB、カメラログは最大2MiB、manifestは最大8KiBです。
受信済み確認ファイルと、未確定の古い一時ファイルは7日後に整理します。
取り込み未完了の `.ready` と対応する `.data` は自動削除しません。
長期障害時はSD・Pi・クラウドの容量を監視してください。

## 配置と更新順序

クラウド、Pi、カメラの順に更新します。既存のモデル・保存先・`.env` は維持します。
新しい共通モジュールも、両サーバーの親ディレクトリへ配置してください。

```text
/opt/wild_animals/                 # 以下の手順で使う例。実際のcheckout先に置換
  pipeline_common.py
  file_transfer.py
  transfer_receiver.py
  KD_pi_server/
    main.py, detector.py, requirements.txt, .env, .env.transfer
  original_server/
    server.py, requirements.txt, .env, .env.transfer
```

Python 3.10以上を使用します。各サーバーの既存仮想環境でrequirementsを更新します。
Piには `pyftpdlib` と `paramiko`、クラウド受信監視には `httpx` が追加で必要です。
SFTPの待受はクラウドOSのOpenSSHが担当します。

```bash
# Piの仮想環境
python -m pip install -r KD_pi_server/requirements.txt
# クラウドの仮想環境
python -m pip install -r original_server/requirements.txt
```

## 1. クラウドのSFTP受信

以下はLinux/OpenSSH用の例です。`wildcloud` は既存クラウドアプリの実行ユーザーに置換します。
SSH送信専用ユーザー `edge-upload` と、アプリ実行ユーザーは分けます。

```bash
sudo groupadd -f wild-transfer
sudo useradd -M -d /transfer -s /usr/sbin/nologin -g wild-transfer edge-upload
sudo usermod -aG wild-transfer wildcloud
sudo install -d -o root -g root -m 0755 /srv/wild-animals-sftp
sudo install -d -o wildcloud -g wild-transfer -m 2750 /srv/wild-animals-sftp/transfer
sudo install -d -o wildcloud -g wild-transfer -m 2770 /srv/wild-animals-sftp/transfer/incoming
sudo install -d -o wildcloud -g wild-transfer -m 2750 /srv/wild-animals-sftp/transfer/receipts
sudo install -d -o root -g root -m 0755 /etc/ssh/authorized_keys
```

ユーザーが既に存在する場合は再作成せず、所属グループとホームを確認します。
`receipts` はアップロードユーザーに書き込み権限を与えません。受領確認の作成はアプリ側のみです。
chrootの `/srv/wild-animals-sftp` とその祖先はroot所有・他ユーザー書き込み不可が必要です。
[OpenSSHのChrootDirectory仕様](https://man.openbsd.org/sshd_config#ChrootDirectory)

Pi側で送信用鍵を作成し、その**公開鍵のみ**をクラウドの
`/etc/ssh/authorized_keys/edge-upload` へ登録します（root所有、0644）。
秘密鍵はPiのサービス実行ユーザーのみが読める場所に置きます。

```bash
# Piで、サービス実行ユーザーとして実行。既存の同名鍵は上書きしない。
install -d -m 0700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/cloud_ed25519
chmod 0600 ~/.ssh/cloud_ed25519
```

クラウドの `sshd_config` 末尾、または読み込まれる設定ファイルに追加します。
`internal-sftp` の `-d` は開始ディレクトリ、`-u` はアップロード時のumaskです。
[OpenSSH SFTPサーバー仕様](https://man.openbsd.org/sftp-server)

```text
Match User edge-upload
    ChrootDirectory /srv/wild-animals-sftp
    AuthorizedKeysFile /etc/ssh/authorized_keys/%u
    AuthenticationMethods publickey
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    ForceCommand internal-sftp -d /transfer -u 0007
    DisableForwarding yes
    PermitTTY no
Match all
```

`sudo sshd -t` で設定を検証してから、OSに応じて `ssh` / `sshd` サービスをreloadします。
既存のSSH管理接続は残した状態で接続を検証してください。
クラウドのファイアウォールではSSHポート（通常TCP 22）をPi側から許可します。

`original_server/.env.transfer.example` を `.env.transfer` にコピーし、
`API_TOKEN` をクラウドアプリの `.env` と一致させます。
`INGEST_API_URL` はそのクラウドアプリのローカルポートです。テスト環境なら8001などに変更します。

```bash
chmod 0600 original_server/.env.transfer
# クラウドアプリを起動した上で、同じ仮想環境・アプリ実行ユーザーで起動
python transfer_receiver.py --transport sftp --role cloud --env-file original_server/.env.transfer
```

`--transport sftp` はフォルダー監視です。SSHサーバー自体を起動するコマンドではありません。

## 2. PiのSFTP送信

`KD_pi_server/.env.sftp.example` の設定を、既存 `KD_pi_server/.env` へ追記・反映します。
実際のクラウド名・SSHユーザー・鍵ファイル・known_hostsの絶対パスを指定します。
`SFTP_REMOTE_ROOT=/transfer` はchroot内のパスで、クラウドOS上の絶対パスとは異なります。

Piのサービス実行ユーザーとして、最初に手動で接続確認します。
接続時のホスト鍵指紋をクラウドの管理画面・コンソール等で確認してから登録してください。

```bash
sftp -o UserKnownHostsFile=~/.ssh/cloud_known_hosts \
     -o StrictHostKeyChecking=ask -i ~/.ssh/cloud_ed25519 edge-upload@cloud.example.com
```

プログラムは登録済みホスト鍵のみ許可し、不明な鍵・変更された鍵を拒否します。
秘密鍵にパスフレーズを付けた場合は `SFTP_KEY_PASSPHRASE` を設定し、`.env` を0600にします。
`LOCAL_MODE=False`、`CLOUD_TRANSFER_MODE=sftp` にしてPiの既存アプリを再起動します。
送信対象は従来と同じく陽性サイクルと設定割合の陰性サンプルです。

`MAIN_SERVER_URL` が残っている場合、既存のHTTP heartbeatは続きます。
クラウドへのHTTP通信を不要とする場合は、Piの `.env` で `MAIN_SERVER_URL=` と空にします。
SFTP画像転送にはこのURLは不要です。

## 3. PiのFTP受信

`KD_pi_server/.env.transfer.example` を `.env.transfer` にコピーして設定します。
`API_TOKEN` はPiアプリの `.env` に合わせ、`FTP_PASSWORD=CHANGE_ME` を実際の値に変更します。
初期値のパスワードではFTPサービスは起動しません。

```bash
# wildcamはPiアプリの実行ユーザーに置換
sudo install -d -o wildcam -m 0750 /srv/wild-animals/ftp
chmod 0600 KD_pi_server/.env.transfer
# Piアプリを起動した上で、その仮想環境・実行ユーザーで起動
python transfer_receiver.py --transport ftp --role edge --env-file KD_pi_server/.env.transfer
```

Piのファイアウォールでは、カメラ用LANからTCP 2121と30000〜30009を許可します。
FTPは暗号化しないため、この待受をインターネットに公開しない構成にします。
パッシブモードのため、制御ポート2121だけ開けても画像は転送できません。
同一LANを前提とし、Piの既存mDNS名を継続利用します。

## 4. カメラ

`KD_edge_cam/esp/camera/transfer_secrets.h.example` を同じフォルダーの
`transfer_secrets.h` にコピーし、`CAMERA_TRANSFER_MODE=1` とPiのFTPユーザー・パスワード・ポートを指定します。
この私有ヘッダーはGitの対象外です。Wi-FiとPiのmDNS名は既存設定を使います。
FTPクライアントは同梱の `ftp_transport.h` で、別のArduino FTPライブラリは不要です。

```bash
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi KD_edge_cam/esp/camera
```

接続・送信・受領確認・タイムアウトは既存のSD通信ログへ記録します。パスワードは出力しません。
FTP経由の `status.json` からPiの状態とUTC時刻を取得します。
通信処理は既存の1起動60秒目安の予算内で実行し、受領確認待ちは1ファイル最大15秒です。
撮影時刻はPiの時刻と起動後経過時間による推定です。

## 常駐起動とHTTPとの併用

`deploy/` の以下のsystemd例で、ユーザー・checkout・仮想環境のパスを実際の環境に合わせます。

- `wild-animal-edge-ftp.service.example`: PiのFTP受信＋取り込み
- `wild-animal-cloud-sftp-inbox.service.example`: クラウドのSFTP取り込み

拡張子 `.example` を外して `/etc/systemd/system/` へ配置し、
`systemctl daemon-reload`、`systemctl enable --now <サービス名>` で有効化します。
取り込みサービスは各ホスト1プロセス、既存アプリも従来の1 workerで使います。

| 区間 | FTP/SFTP | HTTPに切り替える設定 |
|---|---|---|
| カメラ→Pi | `CAMERA_TRANSFER_MODE=1`（FTP）、`2`（SFTP） | `CAMERA_TRANSFER_MODE=0` で再コンパイル・書き込み |
| Pi→クラウド | `CLOUD_TRANSFER_MODE=sftp` | `.env` を `CLOUD_TRANSFER_MODE=http` にしてPi再起動。`MAIN_SERVER_URL` が必要 |

受信側は両方式を同時に受け付けられます。送信側は各区間で1方式を選びます。
自動的な別方式への切り替えや同時二重送信は行わず、選択中の方式で永続再試行します。

## 確認と障害対応

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
sudo journalctl -u wild-animal-edge-ftp -f
sudo journalctl -u wild-animal-cloud-sftp-inbox -f
```

テストは一時ディレクトリとlocalhostを使い、FTP/SFTP転送、受領確認、鍵検証、
HTTPとの重複排除、ハッシュ破損、受信API停止・再起動、送信失敗時の保持を確認します。
モデル推論とメール送信はモックで、実機Wi-Fi・SD・OpenSSH本番設定は別途確認が必要です。

- FTPログイン不可: 私有ヘッダーとPi側の認証情報、mDNS、ポートを確認。
- ログイン後転送不可: Piのパッシブポート許可を確認。
- `.ready` が残り確認が出ない: 取り込みプロセス、ローカルAPI、API_TOKEN、空き容量を確認。
- SFTP権限エラー: chroot内パス、incomingのグループ書き込み、receiptsの読み取り権限を確認。
- SFTPホスト鍵エラー: クラウドの指紋を確認してknown_hostsを更新。検証を無効にしない。
- クラウド転送が止まる: Piの `LOCAL_MODE`、SFTP設定と `edge_server.log`、SQLiteのforwardジョブを確認。

DB・画像のバックアップ、再試行・保持・通知の詳細は [共通信頼性仕様](three_layer_delivery.md) を参照してください。
