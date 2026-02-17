import pandas as pd
import os

base_dir = r"c:/Users/kapib/vscodegit/wild_animals/test2/docs/ieice_paper_draft/データ"

files = {
    "camera": os.path.join(base_dir, "エッジカメラ処理時間.csv"),
    "edge_server": os.path.join(base_dir, "エッジサーバー処理時間.csv"),
    "cloud_server": os.path.join(base_dir, "クラウドサーバー処理時間.csv")
}

results = {}

# Camera
try:
    df_cam = pd.read_csv(files["camera"])
    results["camera"] = {
        "capture_avg": df_cam["Capture_ms"].mean(),
        "wifi_avg": df_cam["Wifi_ms"].mean(),
        "upload_avg": df_cam["Upload_ms"].mean(),
        "total_avg": df_cam["Total_ms"].mean()
    }
except Exception as e:
    print(f"Error reading camera csv: {e}")

# Edge Server
try:
    df_edge = pd.read_csv(files["edge_server"])
    # Only consider forwarded cycles for full latency? Or all?
    # Inference covers all cycles.
    results["edge_server"] = {
        "inference_avg": df_edge["total_inference_ms"].mean(),
        "recv_save_avg": df_edge["total_recv_save_ms"].mean()
    }
except Exception as e:
    print(f"Error reading edge server csv: {e}")

# Cloud Server
try:
    df_cloud = pd.read_csv(files["cloud_server"])
    results["cloud_server"] = {
        "inference_avg": df_cloud["inference_time_ms"].mean(),
        "email_avg": df_cloud["email_time_ms"].mean(),
        "total_avg": df_cloud["total_time_ms"].mean()
    }
except Exception as e:
    print(f"Error reading cloud server csv: {e}")

print("--- Calculation Results ---")
for key, val in results.items():
    print(f"[{key}]")
    for k, v in val.items():
        print(f"  {k}: {v:.2f} ms")
