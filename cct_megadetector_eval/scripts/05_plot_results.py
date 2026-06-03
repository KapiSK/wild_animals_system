import os
import argparse
import pandas as pd
from src.utils import load_config, ensure_dir, setup_logger
from src.plotting import plot_metric_vs_threshold

logger = setup_logger("05_plot_results")

def main():
    parser = argparse.ArgumentParser(description="Plot evaluation results.")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()
    
    cfg = load_config(args.config)
    output_dir = cfg["paths"]["output_dir"]
    plot_dir = os.path.join(output_dir, "plots")
    
    ensure_dir(plot_dir)
    
    summary_csv = os.path.join(output_dir, "image_level_threshold_summary.csv")
    if not os.path.exists(summary_csv):
        logger.error(f"Summary CSV not found: {summary_csv}. Run 04_evaluate_image_level.py first.")
        return
        
    df = pd.read_csv(summary_csv)
    
    metrics_to_plot = [
        "precision",
        "recall",
        "f1",
        "empty_false_positive_rate",
        "animal_false_negative_rate"
    ]
    
    for metric in metrics_to_plot:
        out_file = os.path.join(plot_dir, f"threshold_vs_{metric}.png")
        plot_metric_vs_threshold(df, metric, out_file)
        
    logger.info(f"All plots saved to {plot_dir}")

if __name__ == "__main__":
    main()
