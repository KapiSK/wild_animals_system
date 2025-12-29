# 外部サーバー実装ウォークスルー

## 変更内容

### 外部サーバー (`original_server/`)

- **[更新] `server.py`**:
  - モデルを **MegaDetector v5a** (`md_v5a.0.0.pt`) に変更。
  - モデルの自動ダウンロード機能を追加。
  - クラスフィルタを動物 (`0`) のみに変更。
- **[更新] `requirements.txt`**: `requests` ライブラリを追加。
- **[更新] `README.md`**: Linux (Ubuntu等) での運用手順（インストール、Systemdによるサービス化、FW設定）を追加。

## 検証結果

### 自動テスト

- 未実行。

### 手動検証

- **コードレビュー**:
  - `requests` によるモデルダウンロードロジックの確認。
  - MegaDetector用のクラスIDマッピング変更の確認。
  - Linux用Systemd設定ファイルの記述の確認。

## 次のステップ (Linux環境)

1. サーバーへログイン (SSH等)。
2. `README.md` の "Linuxでの運用セットアップ" に従って環境構築。
3. サービスを起動し、ログ (`journalctl -u wild-server -f`) を確認しながらエッジサーバーから画像を送信してテスト。
