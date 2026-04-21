# Wild Animals システム マルチ環境 (Prod/Test) 構築手順書（手動操作版）

本手順書は、クラウドサーバ (`original_server`)、統合サーバ (`satos`)、エッジサーバ (`pi`) の各ノードにおいて、本番とテスト環境を分離し、必要なソースコードのみを抽出（スパース・チェックアウト）するためのステップバイステップのマニュアルです。

> [!WARNING]
> 大規模なディレクトリ変更を伴います。クラウドサーバ上にすでに蓄積されている大切なアップロード画像（`received_images`, `processed_images`）や設定ファイル（`telemetry.json` 等）は、**実行前に必ず既存のパスから安全な場所へコピー・バックアップ・待避**を取ってください。

---

## 1. 事前準備：ノードディレクトリの確認

各ノードで以下のコマンドを実行する際、一番最後の操作で指定するディレクトリ名が異なります。ご自身の操作している端末（ノード）に合わせて、以下のどれを指定するか決めておいてください。

- クラウドサーバの場合: `original_server`
- 統合サーバの場合: `satos`
- エッジ用ラズパイの場合: `pi`

---

## 2. ex_env（テスト用検証環境）の構築

現在ログインしているサーバ（またはラズパイ）のターミナル（`~` ホームディレクトリ）で以下のコマンドを順番に実行します。

### 1) ディレクトリの作成とクローン

```bash
# 検証用の親ディレクトリを作成し移動
mkdir -p ~/ex_env
cd ~/ex_env

# 中身を展開せずに(メタデータだけ)クローンする
git clone --no-checkout git@github.com:KapiSK/wild_animals_system.git

# クローンしたディレクトリに入る
cd wild_animals_system
```

### 2) スパース・チェックアウトの有効化

```bash
# 特定のフォルダのみを抽出する機能を有効化
git sparse-checkout init --cone

# 「このノードに必要なフォルダ」だけを指定する（クラウドなら original_server、ラズパイなら pi を指定）
# 【重要】：以下は original_server の場合の例です。適宜読み替えてください。
git sparse-checkout set original_server
```

### 3) テストブランチの取得

```bash
# test ブランチのデータを取得して展開する
git checkout test
```

---

## 3. prod_env（本番稼働環境）の構築

続いて、同じノード内で本番用の環境も構築します。

### 1) ディレクトリの作成とクローン

```bash
# 本番用の親ディレクトリを作成し移動
mkdir -p ~/prod_env
cd ~/prod_env

# 同様に展開せずにクローン
git clone --no-checkout git@github.com:KapiSK/wild_animals_system.git

# ディレクトリに入る
cd wild_animals_system
```

### 2) スパース・チェックアウトの有効化

```bash
ｃ

# 先ほどと同じ「このノードに必要なフォルダ」を指定（例: original_server）
git sparse-checkout set original_server
```

### 3) メインブランチの取得

```bash
# 本番なので main または master ブランチを展開する
git checkout main
```

これで、１つのサーバ内に **「テスト機能用(ex_env)」** と **「本番用(prod_env)」** のディレクトリが独立して作られました。中には指定したノードのフォルダしか入っていません。

---

## 4. 各ノードの環境別 `.env` 設定手順

最後の仕上げとして、プログラムが参照する変数（ポート番号や通信先URL）をテスト用・本番用で完全に分けます。

### 4-A. クラウドサーバ (`original_server`) の `.env`

`~/ex_env/wild_animals_system/original_server/` と `~/prod_env/.../original_server/` にそれぞれ `.env` ファイルを作成（または編集）します。

- **`~/prod_env` 側（本番用）**

    ```ini
    # 本番は従来通り 8000 番ポート
    PORT=8000
    API_TOKEN="Production-Secure-Token-1234"
    # その他パスワードなどの本番情報
    ```

* **`~/ex_env` 側（検証用）**

    ```ini
    # テストは 8001 番ポート
    PORT=8001
    API_TOKEN="Experimental-Test-Token-5678"
    ```

### 4-B. 統合サーバ (`satos`) および エッジ (`pi`) の `.env`

これらは、クラウドの「どこへデータを送信するか」を決定するノードです。

- **`~/prod_env` 側（本番用）**

    ```ini
    # 本番の8000番(またはSSLの443番)に向けて送信
    CLOUD_SERVER_URL="https://[あなたのVPSのIP]/upload"
    CLOUD_API_KEY="Production-Secure-Token-1234"
    ```

- **`~/ex_env` 側（検証用）**

    ```ini
    # テストするために立ち上げた8001番(または8443)に向けて送信
    CLOUD_SERVER_URL="http://[あなたのVPSのIP]:8001/upload"
    CLOUD_API_KEY="Experimental-Test-Token-5678"
    ```

---

## 📝 完了と運用フェーズ

すべての設定が完了したら、元々稼働していたディレクトリにある「蓄積データ（ギャラリー画像・DB）」を、新しく作成した **`~/prod_env/...`** 内の然るべき位置へ移動させてください。

移行完了後は、ローカルでコードを改修 → GithubにPush → サーバの `ex_env` で `git pull` して新機能をテスト → 成功したら `main` ブランチに混ぜて `prod_env` を `git pull` して更新、という世界標準の安全なアップデートサイクルが実現します。
