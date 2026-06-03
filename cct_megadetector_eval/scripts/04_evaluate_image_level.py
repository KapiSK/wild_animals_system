import os
import argparse
import pandas as pd
from src.utils import load_config, ensure_dir, setup_logger
from src.md_io import load_md_json, extract_image_level_predictions
from src.metrics import evaluate_thresholds

logger = setup_logger("04_evaluate_image_level")

def main():
    parser = argparse.ArgumentParser(description="Evaluate MegaDetector image-level performance.")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()
    
    cfg = load_config(args.config)
    
    subset_csv = cfg["paths"]["subset_csv"]
    md_results_dir = cfg["paths"]["md_results_dir"]
    output_dir = cfg["paths"]["output_dir"]
    
    thresholds = cfg["evaluation"]["thresholds"]
    animal_category_id = str(cfg["evaluation"]["animal_category_id_in_md"])
    models = cfg["megadetector"]["models"]
    
    ensure_dir(output_dir)
    
    if not os.path.exists(subset_csv):
        logger.error(f"Subset CSV not found: {subset_csv}")
        return
        
    df_gt = pd.read_csv(subset_csv)
    
    all_results = []
    
    for model_key, model_info in models.items():
        model_name = model_info["model_name"]
        output_json = os.path.join(md_results_dir, model_info["output_json"])
        
        if not os.path.exists(output_json):
            logger.warning(f"Results file for {model_name} not found: {output_json}. Skipping.")
            continue
            
        logger.info(f"Evaluating {model_name} ...")
        md_data = load_md_json(output_json)
        df_pred = extract_image_level_predictions(md_data, animal_category_id)
        
        # Evaluate at multiple thresholds
        df_metrics = evaluate_thresholds(df_gt, df_pred, thresholds)
        df_metrics.insert(0, "model", model_name)
        all_results.append(df_metrics)
        
    if not all_results:
        logger.error("No models were evaluated. Check JSON files.")
        return
        
    df_summary = pd.concat(all_results, ignore_index=True)
    
    summary_csv = os.path.join(output_dir, "image_level_threshold_summary.csv")
    df_summary.to_csv(summary_csv, index=False)
    logger.info(f"Saved threshold summary to {summary_csv}")
    
    # ---------------------------------------------------------
    # Best Thresholdsの抽出
    # ---------------------------------------------------------
    best_records = []
    for model_name in df_summary["model"].unique():
        df_m = df_summary[df_summary["model"] == model_name]
        
        # F1最大のthreshold
        best_f1_row = df_m.loc[df_m["f1"].idxmax()]
        
        # Recall >= 0.98 の中で FP最小のthreshold
        high_recall_df = df_m[df_m["recall"] >= 0.98]
        if not high_recall_df.empty:
            best_high_recall_row = high_recall_df.loc[high_recall_df["fp"].idxmin()]
            hr_th = best_high_recall_row["threshold"]
            hr_fp = best_high_recall_row["fp"]
            hr_msg = "Found"
        else:
            hr_th = None
            hr_fp = None
            hr_msg = "No threshold achieved recall >= 0.98"
            
        best_records.append({
            "model": model_name,
            "best_f1_threshold": best_f1_row["threshold"],
            "max_f1": best_f1_row["f1"],
            "recall_98_status": hr_msg,
            "recall_98_threshold": hr_th,
            "recall_98_fp": hr_fp
        })
        
    df_best = pd.DataFrame(best_records)
    best_csv = os.path.join(output_dir, "best_thresholds.csv")
    df_best.to_csv(best_csv, index=False)
    logger.info(f"Saved best thresholds to {best_csv}")

if __name__ == "__main__":
    main()
