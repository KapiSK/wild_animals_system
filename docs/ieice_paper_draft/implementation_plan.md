# 論文執筆計画書 (Implementation Plan)

## 概要

「鳥獣害対策のための複数台カメラを用いた低コスト通信型警戒システムの開発」に関する論文をIEICEのテンプレートを用いて執筆する。

## 文書構成案

### 1. まえがき (Introduction)

- 現状の課題: 既存のトレイルカメラの誤検知、コスト、データ回収の手間
- 本研究の目的: 安価なデバイス(ESP32, RPi)を用いた階層的システムの提案
- 貢献: 低コスト化、誤検知削減、リアルタイム通知

### 2. 提案システム (Proposed System)

- **システムアーキテクチャ**
  - Edge Camera (ESP32): 撮影、一次バッファ
  - Edge Server (RPi): 画像集約、AI推論(YOLO)、フィルタリング
  - External Server: ユーザインターフェース、通知
- **ハードウェア構成**
  - カメラ: ESP32-S3 (XIAO), PIRセンサ
  - サーバ: Raspberry Pi 4
- **ソフトウェア・通信**
  - Wi-Fi, HTTP/MQT (プロトコル確認), mDNS

### 3. 実装 (Implementation)

- **Edge Camera (ESP32)**
  - Deep Sleep制御
  - GPSによる時刻同期
  - 画像撮影とアップロードロジック
- **Edge Server (RPi)**
  - APモード設定
  - 受信サーバ (`upload_server.py`)
  - 推論エンジン (YOLOv8)
- **External Server**
  - メール通知機能
  - データ蓄積

### 4. 実験と評価 (Experiments and Evaluation)

- **機能検証**: 撮影から通知までのフロー確認
- **精度評価**: 誤検知の削減率 (False Positive Rate)
- **電力評価**: ESP32の稼働時間予測

### 5. むすび (Conclusion)

- まとめと今後の課題 (Meshネットワーク化、太陽光発電導入など)

## 次のステップ

1. 著者情報（氏名、所属）の確認
2. 「実験と評価」のための具体的なデータ要件の洗い出し
3. コンパイル環境でのビルド確認
