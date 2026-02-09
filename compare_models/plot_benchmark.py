import csv
import argparse
import os
import sys
import collections

try:
    import matplotlib.pyplot as plt
except ImportError:
    print("Error: matplotlib is required for this script.")
    print("Please install it running: pip install matplotlib")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Plot benchmark results from CSV.')
    parser.add_argument('--csv', type=str, required=True, help='Path to benchmark_summary.csv')
    parser.add_argument('--output', type=str, default='benchmark_plots', help='Output directory for plots')
    args = parser.parse_args()

    csv_path = args.csv
    output_dir = args.output
    
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        return

    os.makedirs(output_dir, exist_ok=True)

    # Read CSV
    data = collections.defaultdict(list)
    models = set()
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            model = row['Model']
            models.add(model)
            data[model].append({
                'threshold': float(row['Threshold']),
                'miss_rate': float(row['Miss_Rate (%)']),
                'recall': float(row['Recall (%)']),
                'fp': int(row['FP_Cycles (Over)'])
            })

    # Sort data by threshold for each model
    for model in data:
        data[model].sort(key=lambda x: x['threshold'])

    # 1. Miss Rate vs Threshold
    plt.figure(figsize=(10, 6))
    for model in sorted(list(models)):
        points = data[model]
        thresholds = [p['threshold'] for p in points]
        miss_rates = [p['miss_rate'] for p in points]
        plt.plot(thresholds, miss_rates, marker='o', label=model)
    
    plt.title('Miss Rate vs Confidence Threshold')
    plt.xlabel('Confidence Threshold')
    plt.ylabel('Miss Rate (%) (Lower is Better)')
    plt.grid(True)
    plt.legend()
    plt.savefig(os.path.join(output_dir, 'miss_rate_vs_threshold.png'))
    plt.close()
    
    # 2. Recall vs Threshold
    plt.figure(figsize=(10, 6))
    for model in sorted(list(models)):
        points = data[model]
        thresholds = [p['threshold'] for p in points]
        recalls = [p['recall'] for p in points]
        plt.plot(thresholds, recalls, marker='x', label=model)
    
    plt.title('Recall vs Confidence Threshold')
    plt.xlabel('Confidence Threshold')
    plt.ylabel('Recall (%) (Higher is Better)')
    plt.grid(True)
    plt.legend()
    plt.savefig(os.path.join(output_dir, 'recall_vs_threshold.png'))
    plt.close()

    # 3. Trade-off: Miss Rate vs False Positives (Over Detection)
    plt.figure(figsize=(10, 6))
    for model in sorted(list(models)):
        points = data[model]
        fps = [p['fp'] for p in points]
        miss_rates = [p['miss_rate'] for p in points]
        plt.plot(fps, miss_rates, marker='^', label=model)
        
        # Annotate thresholds on some points
        for i, p in enumerate(points):
             # Only annotate min/max or specific steps to avoid clutter
             if i % 2 == 0 or i == len(points)-1:
                plt.annotate(f"{p['threshold']}", (p['fp'], p['miss_rate']), 
                             textcoords="offset points", xytext=(0,10), ha='center', fontsize=8)

    plt.title('Trade-off: Miss Rate vs Over Detection (FP)')
    plt.xlabel('False Positive Cycles (Over Detected)')
    plt.ylabel('Miss Rate (%)')
    plt.grid(True)
    plt.legend()
    plt.savefig(os.path.join(output_dir, 'tradeoff_miss_vs_fp.png'))
    plt.close()

    print(f"Plots saved to {output_dir}/")

if __name__ == "__main__":
    main()
