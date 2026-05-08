import json
import pandas as pd
from typing import Dict, Any, Tuple
from src.utils import setup_logger

logger = setup_logger(__name__)

def load_coco_json(path: str) -> Dict[str, Any]:
    """COCO Camera Traps形式のJSONを読み込む"""
    logger.info(f"Loading COCO JSON from {path} ...")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def build_category_map(data: Dict[str, Any]) -> Dict[int, str]:
    """category_id -> category_name のマッピングを作成する"""
    cat_map = {}
    for cat in data.get("categories", []):
        cat_map[cat["id"]] = cat["name"]
    return cat_map

def build_image_table(data: Dict[str, Any]) -> pd.DataFrame:
    """imagesリストからデータフレームを作成する"""
    images = data.get("images", [])
    df_images = pd.DataFrame(images)
    # 必要なカラムだけ抽出 (id, file_name)
    if not df_images.empty:
        df_images = df_images[["id", "file_name"]]
        df_images.rename(columns={"id": "image_id"}, inplace=True)
    return df_images

def build_image_level_labels(data: Dict[str, Any]) -> pd.DataFrame:
    """annotationsを集約し、画像単位のGT(動物有無)データフレームを作成する"""
    logger.info("Building image-level labels from annotations...")
    cat_map = build_category_map(data)
    
    # "empty"カテゴリが存在するか確認
    empty_names = [name for name in cat_map.values() if str(name).lower() == "empty"]
    if not empty_names:
        logger.warning("No 'empty' category found in the categories section.")
        
    annotations = data.get("annotations", [])
    df_ann = pd.DataFrame(annotations)
    
    if df_ann.empty:
        logger.warning("No annotations found in the data.")
        return pd.DataFrame(columns=["image_id", "category_name", "animal_gt"])
    
    # カテゴリ名のマッピング
    df_ann["category_name"] = df_ann["category_id"].map(cat_map)
    
    # 動物かどうかのフラグ付け (empty以外はanimal=1とする)
    df_ann["animal_gt"] = df_ann["category_name"].apply(
        lambda x: 0 if str(x).lower() == "empty" else 1
    )
    
    # 同一画像に複数アノテーションがある場合、animal_gtの最大値（1匹でもいれば1）をとる
    # カテゴリ名も一応結合しておく
    grouped = df_ann.groupby("image_id").agg({
        "animal_gt": "max",
        "category_name": lambda x: ",".join(set([str(i) for i in x]))
    }).reset_index()
    
    return grouped

def sample_animal_empty(df: pd.DataFrame, n_animal: int, n_empty: int, seed: int = 42) -> pd.DataFrame:
    """animal画像とempty画像から指定枚数ずつサンプリングする"""
    df_animal = df[df["animal_gt"] == 1]
    df_empty = df[df["animal_gt"] == 0]
    
    logger.info(f"Available images: {len(df_animal)} animal, {len(df_empty)} empty.")
    
    if len(df_animal) < n_animal:
        logger.warning(f"Requested {n_animal} animal images, but only {len(df_animal)} are available. Using all available.")
        n_animal = len(df_animal)
        
    if len(df_empty) < n_empty:
        logger.warning(f"Requested {n_empty} empty images, but only {len(df_empty)} are available. Using all available.")
        n_empty = len(df_empty)
        
    sampled_animal = df_animal.sample(n=n_animal, random_state=seed)
    sampled_empty = df_empty.sample(n=n_empty, random_state=seed)
    
    df_subset = pd.concat([sampled_animal, sampled_empty]).sample(frac=1, random_state=seed).reset_index(drop=True)
    logger.info(f"Sampled {len(sampled_animal)} animal and {len(sampled_empty)} empty images.")
    
    return df_subset
