import requests
import time
import os
import sys

# --- 設定 ---
# 実際のRaspberry Pi（エッジサーバー）のIPアドレスに変更してください
EDGE_SERVER_IP = "172.10.176.172"
EDGE_SERVER_PORT = 8000
EDGE_URL = f"http://{EDGE_SERVER_IP}:{EDGE_SERVER_PORT}/upload"

# テスト用画像のディレクトリ
# スクリプトと同じ階層の 'img' フォルダを探す
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(SCRIPT_DIR, "img")

def main():
    target_ip = EDGE_SERVER_IP
    
    # 引数処理: python simulate_camera.py [IP]
    args = sys.argv[1:]
    if len(args) >= 1:
        # IPっぽいかチェック
        if "." in args[0] and args[0][0].isdigit():
             target_ip = args[0]

    url = f"http://{target_ip}:{EDGE_SERVER_PORT}/upload"
    print(f"Target URL: {url}")
    print(f"Image Source Directory: {IMG_DIR}")

    # imgフォルダ確認
    if not os.path.exists(IMG_DIR):
        print(f"Error: 'img' directory not found at {IMG_DIR}")
        print("Please create 'img' folder and place img1.jpg, img2.jpg, img3.jpg inside.")
        return

    # 必須画像ファイル (JPEG想定)
    source_images = ["img1.jpg", "img2.jpg", "img3.jpg"]
    
    # 存在確認
    for source_name in source_images:
        path = os.path.join(IMG_DIR, source_name)
        if not os.path.exists(path):
            print(f"Error: Missing {source_name} in {IMG_DIR}")
            return

    # 疑似的な CycleID (簡潔なIDを自動生成: SIM-ランダム4桁)
    import random
    rand_id = random.randint(1000, 9999)
    cycle_id = f"SIM-{rand_id}"
    
    print(f"Starting upload simulation for Cycle: {cycle_id}")
    
    for i, source_name in enumerate(source_images):
        # Indexは 1, 2, 3
        idx = i + 1
        # ESP32の命名規則に従った送信ファイル名
        # {CycleID}-{Index}{n/d}.jpg
        # 例: WIN-SIM-CAM01-0001-1d.jpg (昼間の1枚目)
        target_filename = f"{cycle_id}-{idx}d.jpg"
        source_path = os.path.join(IMG_DIR, source_name)
        
        print(f"Uploading {source_name} as {target_filename} ...")
        try:
            with open(source_path, "rb") as f:
                # サーバーは 'file' フィールドで受け取る
                # ファイル名ヘッダーなどはrequestsが自動で処理するが、
                # ESP32コードでは X-File-Name ヘッダーも付けていた可能性があるため確認
                files = {'file': (target_filename, f, 'image/jpeg')}
                
                # ESP32は X-File-Name ヘッダーをつけている
                headers = {'X-File-Name': target_filename}
                
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
