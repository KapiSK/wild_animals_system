import json
import pandas as pd
from typing import Dict, Any, List
from src.utils import setup_logger

logger = setup_logger(__name__)

def load_md_json(path: str) -> Dict[str, Any]:
    """MegaDetectorの推論出力JSONを読み込む"""
    logger.info(f"Loading MegaDetector JSON from {path} ...")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_max_conf_by_image(image_data: Dict[str, Any], category_id: str = "1") -> float:
    """1つの画像データ（JSONエントリ）から、特定カテゴリの最大confidenceを取得する"""
    max_conf = 0.0
    detections = image_data.get("detections", [])
    if not detections:
        return 0.0
        
    for det in detections:
        if str(det.get("category")) == str(category_id):
            conf = float(det.get("conf", 0.0))
            if conf > max_conf:
                max_conf = conf
    return max_conf

def extract_image_level_predictions(md_json: Dict[str, Any], animal_category_id: str = "1") -> pd.DataFrame:
    """MD出力全体から画像ごとの最大confidenceを抽出してデータフレームを作成する"""
    images = md_json.get("images", [])
    records = []
    
    for img in images:
        file_name = img.get("file", "")
        max_conf = get_max_conf_by_image(img, animal_category_id)
        records.append({
            "file_name": file_name,
            "max_conf": max_conf
        })
        
    df = pd.DataFrame(records)
    logger.info(f"Extracted predictions for {len(df)} images.")
    return df
