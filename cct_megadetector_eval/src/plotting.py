import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path
from src.utils import setup_logger

logger = setup_logger(__name__)

def plot_metric_vs_threshold(summary_df: pd.DataFrame, metric: str, output_path: str, title_override: str = None):
    """複数モデルの閾値ごとの推移をプロットする"""
    plt.figure(figsize=(10, 6))
    
    models = summary_df["model"].unique()
    for model in models:
        df_model = summary_df[summary_df["model"] == model].sort_values("threshold")
        plt.plot(df_model["threshold"], df_model[metric], marker='o', label=model)
        
    title = title_override if title_override else f"Threshold vs {metric}"
    plt.title(title, fontsize=14)
    plt.xlabel("Confidence Threshold", fontsize=12)
    plt.ylabel(metric.replace("_", " ").title(), fontsize=12)
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.7)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    logger.info(f"Saved plot to {output_path}")
