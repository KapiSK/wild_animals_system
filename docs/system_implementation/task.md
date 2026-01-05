# システム実装タスクリスト

- [x] 準備フェーズ <!-- id: 0 -->
  - [x] 実装計画の作成 (YOLOv8n対応) <!-- id: 1 -->
- [x] **Phase 1: External Server Implementation** (Cloud/Linux)
  - [x] Basic setup (FastAPI)
  - [x] Receiving images (`POST /upload`)
  - [x] AI Inference (MegaDetector v5)
  - [x] Email Notification (SMTP)
  - [x] Service configuration (systemd) <!-- Completed -->
  - [x] `original_server/server.py`: BB描画・メール添付ロジックの確認 <!-- id: 3 -->
- [x] フェーズ 2: エッジサーバー (Pi / YOLOv8n) <!-- id: 4 -->
  - [x] `pi/detector.py`: YOLOv8nの実装と動物クラスフィルタリング <!-- id: 5 -->
  - [x] `pi/main.py`: 画像バッファリングと「3枚中2枚」ルールの実装 <!-- id: 6 -->
- [x] フェーズ 3: エッジデバイス (ESP32) <!-- id: 7 -->
  - [x] `esp/camera/camera.ino`: 新しい命名規則の実装 <!-- id: 8 -->
  - [x] `esp/camera/camera.ino`: アップロードロジックの適応 <!-- id: 9 -->
- [ ] 統合検証 <!-- id: 10 -->
  - [x] システム全体のデータフローテスト (Walkthrough作成) <!-- id: 11 -->
