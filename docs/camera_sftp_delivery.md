# カメラ → Pi → クラウドをSFTPにする

現在のカメラの既定値はSFTPです。画像と通信ログをPiへSFTPで送信し、Piからクラウドへの画像転送もSFTPを使います。
カメラ側ではPiのホスト鍵を照合してから公開鍵認証します。未設定・鍵不一致・保存確認なしの場合はSDにデータを残します。

```text
ESP32-S3 / SD ── SFTP :22 ──> Pi OpenSSH / incoming
                                  │ Pi内HTTPで既存の保存・推論へ取り込み
                                  └── SFTP :22 ──> original_server
```

クラウド側とPi→クラウドの設定は [既存のSFTP手順](ftp_sftp_delivery.md#1-クラウドのsftp受信) を使います。
この手順はカメラ→PiをFTPからSFTPへ変更する部分です。先にPiを設定し、最後にカメラを書き込みます。

## 1. Piの受信アカウントとフォルダー

Linux/OpenSSHを使います。以下の `wildcam` は既存Piアプリの実行ユーザーに置き換えます。
`camera-upload` はアップロード専用アカウントで、アプリの実行ユーザーとは分けます。
アカウントが存在する場合は再作成せず、ホーム・所属グループを合わせます。

```bash
sudo groupadd -f camera-transfer
sudo useradd -M -d /transfer -s /usr/sbin/nologin -g camera-transfer camera-upload
sudo usermod -aG camera-transfer wildcam
sudo install -d -o root -g root -m 0755 /srv/wild-animals-camera-sftp
sudo install -d -o wildcam -g camera-transfer -m 2750 /srv/wild-animals-camera-sftp/transfer
sudo install -d -o wildcam -g camera-transfer -m 2770 /srv/wild-animals-camera-sftp/transfer/incoming
sudo install -d -o wildcam -g camera-transfer -m 2750 /srv/wild-animals-camera-sftp/transfer/receipts
sudo install -d -o root -g root -m 0755 /etc/ssh/authorized_keys
```

`receipts/` と `status.json` はアプリ側のみが書き込み、カメラは読み取りだけ行います。
chrootのルートと祖先はroot所有で、グループ・他ユーザーの書き込みは禁止します。
[OpenSSHのchroot仕様](https://man.openbsd.org/sshd_config#ChrootDirectory)

Piの `sshd_config` 末尾、または読み込まれる設定ファイルへ追加します。

```text
Match User camera-upload
    ChrootDirectory /srv/wild-animals-camera-sftp
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

`sudo sshd -t` で検証してから、OSに応じて `ssh` または `sshd` をreloadします。
既存の管理用SSH接続は残して接続確認してください。カメラ用LANからPiのTCP 22を許可します。
SFTPではFTP用の2121・30000〜30009は不要です。旧FTPを使うカメラがある間はその待受を維持します。

## 2. カメラ専用の鍵とPiの指紋

管理PCでカメラごとの鍵を作成します。既存の同名鍵を上書きしない場所で実行します。

```bash
ssh-keygen -t ed25519 -f camera_ed25519
```

- `camera_ed25519.pub` の中身をPiの `/etc/ssh/authorized_keys/camera-upload` に登録（root所有、0644）。複数台なら各公開鍵を別の行へ追加。
- 秘密鍵 `camera_ed25519` はカメラのSDカードへ `/ssh/camera_ed25519` として配置。
- 鍵にパスフレーズを付けた場合は後述の私有ヘッダーに設定。秘密鍵はログ・リポジトリへ保存しない。

Piのコンソール等、信頼できる接続から次を実行します。

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

出力中の **`SHA256:...` の文字列だけ**を私有ヘッダーへ設定します。
カメラは `ssh-ed25519` のPiホスト鍵を指定して照合します。OS再インストール等で鍵が変わった場合は再確認して更新します。
不明な鍵を自動登録する処理や、パスワード認証へのフォールバックはありません。

## 3. Piの取り込みサービス

`KD_pi_server/.env.sftp-inbox.example` を `KD_pi_server/.env.transfer` にコピーし、
`API_TOKEN` をPiアプリの `.env` と一致させます。既存 `.env.transfer` がある場合は内容を比較して反映します。

```bash
chmod 0600 KD_pi_server/.env.transfer
# 既存のPiアプリを起動した上で、その仮想環境と実行ユーザーで実行
python transfer_receiver.py --transport sftp --role edge --env-file KD_pi_server/.env.transfer
```

アプリ実行ユーザーのグループ追加後はログインし直すかサービスを再起動します。
取り込みサービスは、Pi上の既存 `/upload` と `/esp_log` を使って保存を確認した後に受領確認を公開します。
APIを止めたままでは、ファイルがSFTPで到着してもカメラは完了扱いにしません。

常駐用の [systemd例](../deploy/wild-animal-edge-sftp-inbox.service.example) では、ユーザー・checkout・仮想環境のパスを置換して
`/etc/systemd/system/wild-animal-edge-sftp-inbox.service` へ配置します。
`systemctl daemon-reload`、`systemctl enable --now wild-animal-edge-sftp-inbox` で起動します。
同じ受信フォルダーを複数の取り込みプロセスで監視しないでください。
旧FTPカメラも併用する場合は、FTPとSFTPで受信フォルダー・設定ファイルを分け、同じPi APIへ取り込みます。

## 4. カメラの設定とビルド

`transfer_secrets.h.example` を同じディレクトリの `transfer_secrets.h` にコピーして設定します。
古い `CAMERA_USE_FTP` は取り除き、次の設定を使います。

```cpp
#define CAMERA_TRANSFER_MODE 2
#define CAMERA_SFTP_PORT 22
#define CAMERA_SFTP_USER "camera-upload"
#define CAMERA_SFTP_HOST_FINGERPRINT "SHA256:ここを実際のPiの指紋に置換"
#define CAMERA_SFTP_KEY_PATH "/ssh/camera_ed25519"
#define CAMERA_SFTP_KEY_PASSPHRASE ""
#define CAMERA_SFTP_REMOTE_ROOT "/transfer"
```

Wi-Fi設定とPiのmDNS名は従来どおりです。`SFTP_REMOTE_ROOT` はchroot内から見えるパスです。
Pi→クラウド用の秘密鍵をカメラに流用せず、それぞれの接続用の鍵を使います。

```bash
arduino-cli lib install "LibSSH-ESP32@5.9.0"
arduino-cli compile --jobs 4 --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi KD_edge_cam/esp/camera
```

[LibSSH-ESP32](https://github.com/ewpa/LibSSH-ESP32) のSSHチャネル機能を使います。
このライブラリにはSFTPモジュールが同梱されていないため、`sftp_protocol.h` が必要なSFTP v3操作
（open/read/write/close/rename）を実装しています。暗号化・鍵交換・認証はSSHライブラリが担当します。
ESP32 Arduino core 3.2.0とPSRAM有効のXIAO ESP32-S3をビルド検証対象とします。
SFTPビルドの結果はプログラム1,340,222バイト／3,342,336バイト、静的RAM69,792バイトです。
SSHセッションのヒープと64KiBタスクスタックは静的RAMの数値には含まれません。

画像は2048バイト単位で送信します。SSH用にArduinoのloop taskスタックを64KiBへ拡大します。
撮影終了後にカメラを解放してから通信する既存の順序を維持します。
接続・認証の結果、空きヒープ、送信・受領確認・失敗をSDの既存ログへ記録します。
1起動60秒目安の通信予算と1ファイル最大15秒の受領確認待ちを使います。
暗号処理・SD処理を含む起動全体の厳密な上限ではありません。

## 切り替えと検証

| `CAMERA_TRANSFER_MODE` | カメラ→Pi |
|---|---|
| `2`（既定） | SFTP / 公開鍵認証 / ホスト鍵指紋確認 |
| `1` | 以前のFTP設定 |
| `0` | 以前のHTTP設定 |

古い私有ヘッダー等で `CAMERA_USE_FTP=0/1` を明示している場合、その設定を引き継ぎます。
`CAMERA_TRANSFER_MODE` を明示すれば新設定を優先します。自動的な通信方式の切り替えはありません。
途中までのファイルは取り込まず、保存確認・SHA-256・画像IDが一致するまで送信元を残す仕様は共通です。

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

カメラと同じC++プロトコルのホストテストを含めるには、`tests/sftp_protocol_bridge.cpp` を共有ライブラリにビルドし、
環境変数 `CAMERA_SFTP_TEST_LIB` に絶対パスを設定して実行します。未設定ならそのテストのみskipします。
例（LinuxのC++コンパイラ、またはWindowsでZig 0.13.0の `zig c++` を使用）:

```bash
c++ -std=c++11 -O2 -shared -fPIC tests/sftp_protocol_bridge.cpp -o /tmp/camera_sftp.so
CAMERA_SFTP_TEST_LIB=/tmp/camera_sftp.so python -m unittest discover -s tests -p 'test_*.py' -v
```

テストではlocalhostのSSH/SFTPサーバーへ送信し、断片化された応答、受領確認、ファイル上書き禁止、
応答ID不一致、過大・途切れたパケット、権限エラーを確認します。
実機ではSD鍵読み取り、Piのホスト鍵不一致時の拒否、送信中のWi-Fi切断、消費電流・送信時間・最小空きヒープを確認してください。
PC上のテストとコンパイルだけではESP32上のメモリ余裕や電池への影響は確定できません。
