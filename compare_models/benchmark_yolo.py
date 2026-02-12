import os
import glob
import argparse
import re
import csv
import sys
import time
from collections import defaultdict
import torch
from ultralytics import YOLO
import datetime
from ultralytics import YOLO
from tqdm import tqdm

# Default paths (can be overridden by args)
DEFAULT_IMAGE_DIR = r"/home/satoko/project/hykecam_1010/ALL/night/"
DEFAULT_MD_MODEL_PATH = r"md_v5a.0.0.pt"
DEFAULT_OUTPUT_DIR = "benchmark_results"

# YOLOv8 Animals + Person
# 0: person
# 14: bird, 15: cat, 16: dog, 17: horse, 18: sheep, 19: cow, 
# 20: elephant, 21: bear, 22: zebra, 23: giraffe
YOLO_ANIMAL_CLASSES = [0, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]

def extract_cycle_id(filename):
    """
    Extract Cycle ID from filename.
    Handles 'CycleID-Index.jpg' format.
    """
    stem = os.path.splitext(filename)[0]
    # Look for -(digits) at the end
    match = re.search(r"-(\d+)[nd]?$", stem)
    if match:
        return stem[:match.start()]
    return "unknown"

def get_md_detections(model, image_path):
    """
    Run MegaDetector inference on a single image.
    Returns: bool (is_detected), float (max_conf)
    MegaDetector Class 1=Animal, but check 0 too just in case.
    """
    try:
        results = model(image_path)
        # xyxy[0] = [x1, y1, x2, y2, conf, cls]
        detections = results.xyxy[0]
        if len(detections) == 0:
            return False, 0.0
        
        max_conf = 0.0
        is_det = False
        
        for *xyxy, conf, cls in detections:
            c = float(conf)
            cls_id = int(cls)
            # Check for animal class (1 or 0)
            if cls_id == 1 or cls_id == 0:
                if c > max_conf:
                    max_conf = c
                # MD has no threshold here, we apply it later or rely on default
                is_det = True 
        
        return is_det, max_conf
    except Exception as e:
        print(f"Error in MD inference for {image_path}: {e}")
        return False, 0.0

def get_yolo_detections(model, image_path, conf_threshold):
    """
    Run YOLO inference on a single image.
    Returns: bool (is_detected), float (max_conf)
    """
    try:
        results = model(image_path, verbose=False, conf=conf_threshold, imgsz=640)
        if len(results) == 0 or not results[0].boxes:
            return False, 0.0
        
        max_conf = 0.0
        is_det = False
        
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            
            if cls_id in YOLO_ANIMAL_CLASSES:
                if conf >= conf_threshold:
                    if conf > max_conf:
                        max_conf = conf
                    is_det = True
        
        return is_det, max_conf
    except Exception as e:
        print(f"Error in YOLO inference for {image_path}: {e}")
        return False, 0.0

def main():
    parser = argparse.ArgumentParser(description='Benchmark YOLO models against MegaDetector.')
    parser.add_argument('--images', type=str, default=DEFAULT_IMAGE_DIR, help='Path to image directory')
    parser.add_argument('--md', type=str, default=DEFAULT_MD_MODEL_PATH, help='Path to MegaDetector model (.pt)')
    parser.add_argument('--yolo-models', nargs='+', required=True, help='List of YOLO model paths (e.g. yolov8n.pt yolov8s.pt)')
    parser.add_argument('--confs', nargs='+', type=float, default=[0.05, 0.1, 0.15, 0.2, 0.25, 0.3], help='List of confidence thresholds to test')
    parser.add_argument('--output', type=str, default=DEFAULT_OUTPUT_DIR, help='Output directory')
    
    args = parser.parse_args()
    
    image_dir = args.images
    md_path = args.md
    yolo_models = args.yolo_models
    confs = args.confs
    output_dir = args.output
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Load Image List
    print(f"Scanning images in {image_dir}...")
    extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp']
    image_files = []
    for ext in extensions:
        image_files.extend(glob.glob(os.path.join(image_dir, ext)))
        image_files.extend(glob.glob(os.path.join(image_dir, ext.upper())))
    image_files = sorted(list(set(image_files)))
    
    if not image_files:
        print("No images found.")
        return
        
    print(f"Found {len(image_files)} images.")

    # 2. Prepare MD Detection (Teacher)
    # Since MD inference is heavy, we run it once and store results.
    # We use a standard threshold for MD (e.g., 0.25) to define "Truth".
    MD_THRESHOLD = 0.25
    
    print(f"\nLoading MegaDetector: {md_path}")
    try:
        model_md = torch.hub.load('ultralytics/yolov5', 'custom', path=md_path, trust_repo=True)
    except Exception as e:
        print(f"Failed to load MD model: {e}")
        return

    print("Running MegaDetector inference to establish Ground Truth...")
    md_results = {} # filename -> {'is_detected': bool, 'conf': float, 'cycle': str}
    cycle_map = {}  # cycle_id -> list of filenames
    
    for img_path in tqdm(image_files, desc="MD Inference"):
        filename = os.path.basename(img_path)
        cycle_id = extract_cycle_id(filename)
        
        is_det, conf = get_md_detections(model_md, img_path)
        
        # Apply MD threshold immediately
        is_positive = (is_det and conf >= MD_THRESHOLD)
        
        md_results[filename] = {
            'is_positive': is_positive,
            'conf': conf,
            'cycle': cycle_id
        }
        
        if cycle_id not in cycle_map:
            cycle_map[cycle_id] = []
        cycle_map[cycle_id].append(filename)
        
    # Aggegate MD results per cycle
    md_positive_cycles = set()
    for cid, files in cycle_map.items():
        # If ANY image in cycle is positive, the cycle is positive
        if any(md_results[f]['is_positive'] for f in files):
            md_positive_cycles.add(cid)
            
    print(f"Total Cycles: {len(cycle_map)}")
    print(f"MD Positive Cycles (Ground Truth): {len(md_positive_cycles)}")
    
    # Free up MD model memory if possible
    del model_md
    torch.cuda.empty_cache()

    # 3. Benchmark YOLO Models
    run_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    benchmark_data = [] # List of dicts for CSV output
    
    for yolo_path in yolo_models:
        model_name = os.path.basename(yolo_path)
        print(f"\nBenchmarking YOLO Model: {model_name}")
        
        try:
            model_yolo = YOLO(yolo_path)
        except Exception as e:
            print(f"Failed to load YOLO model {yolo_path}: {e}")
            continue
            
        # Run inference for all images ONCE with a very low threshold (min of test confs)
        # Then we can filter results for different thresholds without re-running inference.
        min_conf = min(confs)
        print(f"  Running inference with min_conf={min_conf}...")
        
        yolo_raw_results = {} # filename -> max_conf
        
        for img_path in tqdm(image_files, desc=f"YOLO {model_name}"):
            filename = os.path.basename(img_path)
            # We get max_conf for animal classes
            _, max_conf = get_yolo_detections(model_yolo, img_path, min_conf)
            yolo_raw_results[filename] = max_conf
            
        # Analysis for each threshold
        print("  Analyzing thresholds...")
        for conf in confs:
            yolo_detected_cycles = set()
            
            # Determine which cycles are detected by YOLO at this threshold
            for cid, files in cycle_map.items():
                is_cycle_detected = False
                for f in files:
                    if yolo_raw_results[f] >= conf:
                        is_cycle_detected = True
                        break
                if is_cycle_detected:
                    yolo_detected_cycles.add(cid)
            
            # Calculate Metrics
            # TP: MD says Yes, YOLO says Yes
            tp_cycles = md_positive_cycles.intersection(yolo_detected_cycles)
            # FN (Lost at Edge): MD says Yes, YOLO says No
            fn_cycles = md_positive_cycles - yolo_detected_cycles
            # FP (Over Detection): MD says No, YOLO says Yes
            fp_cycles = yolo_detected_cycles - md_positive_cycles
            
            tp_count = len(tp_cycles)
            fn_count = len(fn_cycles)
            fp_count = len(fp_cycles)
            
            md_pos_count = len(md_positive_cycles)
            total_cycles = len(cycle_map)
            tn_cycles = total_cycles - md_pos_count - fp_count
            
            miss_rate = (fn_count / md_pos_count * 100) if md_pos_count > 0 else 0.0
            recall = (tp_count / md_pos_count * 100) if md_pos_count > 0 else 0.0
            
            print(f"    Conf {conf:.2f}: Miss Rate={miss_rate:.2f}% ({fn_count}/{md_pos_count}), FP={fp_count}")
            
            benchmark_data.append({
                'Run_Date': run_date,
                'Model': model_name,
                'Threshold': conf,
                'Total_Images': len(image_files),
                'Total_Cycles': total_cycles,
                'MD_Positive_Cycles': md_pos_count,
                'YOLO_Detected_Cycles': len(yolo_detected_cycles),
                'TP_Cycles': tp_count,
                'FN_Cycles (Missed)': fn_count,
                'FP_Cycles (Over)': fp_count,
                'TN_Cycles': tn_cycles,
                'Miss_Rate (%)': f"{miss_rate:.2f}",
                'Recall (%)': f"{recall:.2f}"
            })
            
        del model_yolo
        torch.cuda.empty_cache()

    # 4. Save Results
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = os.path.join(output_dir, f'benchmark_summary_{timestamp_str}.csv')
    keys = benchmark_data[0].keys() if benchmark_data else []
    
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(benchmark_data)
        
    print(f"\nBenchmark complete. Results saved to {csv_file}")

if __name__ == "__main__":
    main()
