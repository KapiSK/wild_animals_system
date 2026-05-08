import os
import time
import argparse
import pandas as pd
import requests
from tqdm import tqdm
from pathlib import Path
from src.utils import load_config, ensure_dir, setup_logger

logger = setup_logger("02_download_images")

def download_file(url: str, dest_path: str, retries: int = 2) -> bool:
    """ファイルをダウンロードする。リトライ機能付き。"""
    if os.path.exists(dest_path):
        return True
        
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, stream=True, timeout=15)
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except requests.RequestException as e:
            if attempt < retries:
                time.sleep(2)
            else:
                logger.error(f"Failed to download {url}: {e}")
    return False

def main():
    parser = argparse.ArgumentParser(description="Download images from CCT subset.")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()
    
    cfg = load_config(args.config)
    
    subset_csv = cfg["paths"]["subset_csv"]
    image_dir = cfg["paths"]["image_dir"]
    base_url = cfg["dataset"]["base_image_url"]
    
    if not os.path.exists(subset_csv):
        logger.error(f"Subset CSV not found: {subset_csv}")
        return
        
    df = pd.read_csv(subset_csv)
    logger.info(f"Loaded {len(df)} images to download.")
    
    ensure_dir(image_dir)
    
    failed_downloads = []
    
    # tqdmでプログレスバー表示
    for idx, row in tqdm(df.iterrows(), total=len(df), desc="Downloading images"):
        file_name = row["file_name"]
        file_name_clean = str(file_name).replace("\\", "/") # Windows対応
        
        url = f"{base_url}/{file_name_clean}"
        dest_path = os.path.join(image_dir, file_name_clean)
        
        # サブディレクトリが存在しない場合は作成
        ensure_dir(os.path.dirname(dest_path))
        
        success = download_file(url, dest_path)
        if not success:
            failed_downloads.append(file_name)
            
    if failed_downloads:
        failed_csv = os.path.join(os.path.dirname(subset_csv), "failed_downloads.csv")
        pd.DataFrame({"file_name": failed_downloads}).to_csv(failed_csv, index=False)
        logger.error(f"Failed to download {len(failed_downloads)} images. Saved list to {failed_csv}")
    else:
        logger.info("All images downloaded successfully.")

if __name__ == "__main__":
    main()
