import requests
import time
import os
import sys

# --- 設定 ---
# 実際のRaspberry Pi（エッジサーバー）のIPアドレスに変更してください
EDGE_SERVER_IP = "192.168.X.X" 
EDGE_SERVER_PORT = 8000
EDGE_URL = f"http://{EDGE_SERVER_IP}:{EDGE_SERVER_PORT}/upload"

# テスト用の画像ファイル
# カレントディレクトリに test.jpg がある想定、なければ作成または指定
IMAGE_FILE = "test.jpg"

def main():
    if len(sys.argv) > 1:
        target_ip = sys.argv[1]
    else:
        target_ip = EDGE_SERVER_IP
        
    url = f"http://{target_ip}:{EDGE_SERVER_PORT}/upload"
    print(f"Target URL: {url}")
    
    # 疑似的な CycleID (MACアドレス-シーケンス番号)
    cycle_id = "WIN-SIM-CAM01-0001"
    
    # ESP32の命名規則に従ったファイル名
    # {CycleID}-{Index}{n/d}.jpg
    # 例: WIN-SIM-CAM01-0001-1d.jpg (昼間の1枚目)
    files_to_send = [
        f"{cycle_id}-1d.jpg",
        f"{cycle_id}-2d.jpg",
        f"{cycle_id}-3d.jpg"
    ]
    
    # テスト画像の準備
    if not os.path.exists(IMAGE_FILE):
        print(f"Creating dummy image: {IMAGE_FILE}")
        # 空のファイルだとサーバー側検出でエラーになる可能性があるため、ダミーデータを入れる
        # ただ、YOLO検出させるなら本物の動物画像を用意するか、
        # Pi側で「動物なし」と判定されて転送されないことを確認するテストになる。
        with open(IMAGE_FILE, "wb") as f:
            f.write(os.urandom(1024)) # ランダムデータ
            
    print(f"Starting upload simulation for Cycle: {cycle_id}")
    
    for filename in files_to_send:
        print(f"Uploading {filename} ...")
        try:
            with open(IMAGE_FILE, "rb") as f:
                # サーバーは 'file' フィールドで受け取る
                # ファイル名ヘッダーなどはrequestsが自動で処理するが、
                # ESP32コードでは X-File-Name ヘッダーも付けていた可能性があるため確認
                # pi/main.py は UploadFile.filename を見るので、multipart/form-dataのfilenameが重要
                files = {'file': (filename, f, 'image/jpeg')}
                
                # ESP32は X-File-Name ヘッダーをつけている (pi/main.pyはこれを見ていないが念のため)
                headers = {'X-File-Name': filename}
                
                response = requests.post(url, files=files, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    print(f"  Success: {response.json()}")
                else:
                    print(f"  Error: Status {response.status_code}, Body: {response.text}")
                    
        except Exception as e:
            print(f"  Upload Failed: {e}")
            
        # ESP32は連続送信するが、少しウェイトを入れても良い
        time.sleep(1)

    print("--- Upload Complete ---")
    print("Check Raspberry Pi logs for 'Cycle WIN-SIM-CAM01-0001 complete'.")
    print("If animal detected (2/3), check External Server logs for forwarding.")

if __name__ == "__main__":
    if "192.168.X.X" in EDGE_URL and len(sys.argv) <= 1:
        print("Error: Please set EDGE_SERVER_IP in the script or pass IP as argument.")
        print("Usage: python simulate_camera.py <PI_IP_ADDRESS>")
        sys.exit(1)
    main()
