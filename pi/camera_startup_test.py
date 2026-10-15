import cv2
import time
import os
from datetime import datetime

def main():
    # 動画と画像の保存先ディレクトリ
    output_dir = "startup_test_results"
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = os.path.join(output_dir, f"startup_{timestamp}.mp4")
    
    print("カメラを初期化します...")
    
    # 時間計測用（カメラオープン処理にかかる時間も見るため）
    init_start = time.time()
    
    # カメラを開く (0 はデフォルトカメラ。PiでUSBカメラやPiCameraを使う場合は適宜変更)
    cap = cv2.VideoCapture(0)
    
    init_end = time.time()
    print(f"カメラのオープン処理完了 ({init_end - init_start:.2f}秒)")
    
    if not cap.isOpened():
        print("エラー: カメラを開けませんでした。")
        return

    # 解像度とFPSの取得
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0 or fps != fps: # fpsが取得できない場合のフォールバック
        fps = 30.0
        
    print(f"解像度: {width}x{height}, FPS: {fps}")

    # 録画設定 (MP4形式)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(video_path, fourcc, fps, (width, height))

    print(f"録画を開始します（約10秒間）... (出力先: {video_path})")
    
    # 録画時間 (秒)
    record_duration = 10
    start_time = time.time()
    
    frame_count = 0
    saved_snapshots = []
    
    while (time.time() - start_time) < record_duration:
        ret, frame = cap.read()
        if not ret:
            print("フレームの取得に失敗しました。")
            break
            
        out.write(frame)
        elapsed = time.time() - start_time
        
        # 起動直後の輝度変化を詳細に追うため、0秒, 1秒, 2秒...のタイミングで静止画を保存
        # fpsベースで大体の秒数を計算
        target_sec = int(elapsed)
        if target_sec not in saved_snapshots:
            img_path = os.path.join(output_dir, f"frame_{timestamp}_{target_sec:02d}s.jpg")
            cv2.imwrite(img_path, frame)
            saved_snapshots.append(target_sec)
            print(f"  [{target_sec:02d}秒経過] スナップショットを保存しました: {os.path.basename(img_path)}")
            
        frame_count += 1

    print("録画が終了しました。")
    cap.release()
    out.release()
    print(f"結果は {output_dir}/ に保存されています。")

if __name__ == "__main__":
    main()
