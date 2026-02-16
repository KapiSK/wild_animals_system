import pandas as pd
import matplotlib.pyplot as plt
import sys
import os

def plot_experiment_results(csv_file):
    if not os.path.exists(csv_file):
        print(f"Error: File {csv_file} not found.")
        return

    try:
        df = pd.read_csv(csv_file)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    # Convert timestamp to datetime
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Calculate elapsed time from start (seconds)
    start_time = df['timestamp'].min()
    df['elapsed'] = (df['timestamp'] - start_time).dt.total_seconds()
    
    # Calculate Packet Loss (Moving Window)
    # We look at sequence numbers. If seq jumps from 1 to 3, we lost 1.
    # A simple way involves checking the difference between consecutive seq numbers.
    # Ideally diff should be 1.
    df = df.sort_values('seq')
    df['seq_diff'] = df['seq'].diff().fillna(1)
    # Packets lost is (diff - 1). e.g., if diff is 1, lost 0. if diff is 2, lost 1.
    df['lost'] = df['seq_diff'] - 1
    
    # Analyze in windows of, say, 10 packets or 10 seconds?
    # Let's plot raw RSSI vs Time (or Seq)
    
    fig, ax1 = plt.subplots(figsize=(12, 6))

    color = 'tab:blue'
    ax1.set_xlabel('Sequence Number (Time ->)')
    ax1.set_ylabel('RSSI (dBm)', color=color)
    ax1.plot(df['seq'], df['rssi'], color=color, marker='o', label='RSSI')
    ax1.tick_params(axis='y', labelcolor=color)
    ax1.grid(True)

    # Highlight Packet Loss
    # If lost > 0, mark it
    lost_packets = df[df['lost'] > 0]
    if not lost_packets.empty:
        # vertical lines where loss occurred
        for seq in lost_packets['seq']:
            ax1.axvline(x=seq, color='red', alpha=0.3, linestyle='--')
        
        # Add a dummy line for legend
        ax1.plot([], [], color='red', linestyle='--', label='Packet Loss Event')

    plt.title('Communication Range Experiment: RSSI & Packet Loss')
    plt.legend()
    plt.tight_layout()
    
    output_img = csv_file.replace('.csv', '.png')
    plt.savefig(output_img)
    print(f"Plot saved to {output_img}")
    plt.show()

if __name__ == "__main__":
    csv_path = "experiment_log.csv"
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    
    # Check if inside server dir specific path
    if not os.path.exists(csv_path):
        # try default relative path
        csv_path = os.path.join(os.path.dirname(__file__), "experiment_log.csv")
        
    print(f"Analyzing {csv_path}...")
    plot_experiment_results(csv_path)
