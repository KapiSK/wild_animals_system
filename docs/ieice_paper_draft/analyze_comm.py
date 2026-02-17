import pandas as pd
import numpy as np

csv_file = r"c:/Users/kapib/vscodegit/wild_animals/test2/docs/ieice_paper_draft/データ/experiment_log.csv"

def analyze_log(file_path):
    try:
        df = pd.read_csv(file_path)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        
        # Detect sessions based on time gap or seq reset
        df['time_diff'] = df['timestamp'].diff().dt.total_seconds()
        df['seq_diff'] = df['seq'].diff()
        
        # Start a new session if time gap > 30s or seq decreases (reset)
        session_mask = (df['time_diff'] > 30) | (df['seq_diff'] < 0)
        df['session_id'] = session_mask.cumsum()
        
        results = []
        
        print(f"Total Sessions: {df['session_id'].max() + 1}")
        
        for session_id, group in df.groupby('session_id'):
            if len(group) < 2:
                continue
                
            start_time = group['timestamp'].min()
            end_time = group['timestamp'].max()
            duration = (end_time - start_time).total_seconds()
            
            min_seq = group['seq'].min()
            max_seq = group['seq'].max()
            expected_packets = max_seq - min_seq + 1
            received_packets = len(group)
            lost_packets = expected_packets - received_packets
            loss_rate = (lost_packets / expected_packets) * 100 if expected_packets > 0 else 0
            
            avg_rssi = group['rssi'].mean()
            min_rssi = group['rssi'].min()
            max_rssi = group['rssi'].max()
            
            # File size is constant 512000 bytes (approx 500KB)
            # Throughput = Total Bytes / Duration
            total_bytes = group['file_size'].sum()
            throughput_kbps = (total_bytes * 8) / duration / 1000 if duration > 0 else 0
            
            with open("analysis_report.txt", "a", encoding="utf-8") as f:
                f.write(f"Session {session_id}:\n")
                f.write(f"  Time: {start_time.strftime('%H:%M:%S')} - {end_time.strftime('%H:%M:%S')} ({duration:.1f}s)\n")
                f.write(f"  Seq: {min_seq} - {max_seq} (Exp: {expected_packets}, Recv: {received_packets})\n")
                f.write(f"  Loss: {loss_rate:.2f}% ({lost_packets} packets)\n")
                f.write(f"  RSSI: Avg {avg_rssi:.1f}, Min {min_rssi}, Max {max_rssi}\n")
                f.write(f"  Throughput: {throughput_kbps:.2f} kbps\n")
                f.write("-" * 30 + "\n")
            
            results.append({
                'session_id': session_id,
                'min_rssi': min_rssi,
                'avg_rssi': avg_rssi,
                'loss_rate': loss_rate,
                'throughput': throughput_kbps
            })
            
        return results

    except Exception as e:
        print(f"Error: {e}")
        return []

if __name__ == "__main__":
    analyze_log(csv_file)
