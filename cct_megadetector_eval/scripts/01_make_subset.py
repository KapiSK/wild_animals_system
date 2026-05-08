import os
import argparse
import pandas as pd
from src.utils import load_config, ensure_dir, setup_logger
from src.cct_io import load_coco_json, build_image_table, build_image_level_labels, sample_animal_empty

logger = setup_logger("01_make_subset")

def main():
    parser = argparse.ArgumentParser(description="Make subset from CCT annotations.")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()
    
    cfg = load_config(args.config)
    
    ann_path = cfg["paths"]["image_annotations"]
    out_csv = cfg["paths"]["subset_csv"]
    n_animal = cfg["dataset"]["n_animal"]
    n_empty = cfg["dataset"]["n_empty"]
    seed = cfg["dataset"]["random_seed"]
    
    if not os.path.exists(ann_path):
        logger.error(f"Annotation file not found: {ann_path}")
        return
        
    ensure_dir(os.path.dirname(out_csv))
    
    data = load_coco_json(ann_path)
    
    df_images = build_image_table(data)
    df_labels = build_image_level_labels(data)
    
    if df_images.empty or df_labels.empty:
        logger.error("Failed to extract images or labels from JSON.")
        return
        
    # merge to get file_name
    df_merged = pd.merge(df_images, df_labels, on="image_id", how="inner")
    
    df_subset = sample_animal_empty(df_merged, n_animal, n_empty, seed)
    
    df_subset.to_csv(out_csv, index=False)
    logger.info(f"Successfully saved subset to {out_csv} ({len(df_subset)} rows).")

if __name__ == "__main__":
    main()
