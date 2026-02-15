import os
import glob
import argparse
import re
import csv
import sys
from collections import defaultdict
import datetime
import time

try:
    from ultralytics import YOLO
    from tqdm import tqdm
    import torch
except ImportError as e:
    print(f"Error: Missing required library: {e.name}")
    print("Please install the required packages using the following command:")
    print("pip install ultralytics tqdm torch torchvision")
    sys.exit(1)

# ==========================================
# デフォルト設定
# ==========================================
# 画像ディレクトリ (ユーザー指定)
DEFAULT_IMAGE_DIR = r"/home/satoko/project/hykecam_1010/ALL/night/"
# モデルパス (相対パスまたは絶対パス)
DEFAULT_MD_MODEL_PATH = "md_v5a.0.0.pt" 
DEFAULT_YOLO_MODEL_PATH = "yolov8n.pt"

# 信頼度閾値
DEFAULT_YOLO_CONF = 0.1  # エッジ側 (YOLO) の閾値
DEFAULT_MD_CONF = 0.25   # クラウド側 (MD) の閾値

# 出力先
DEFAULT_OUTPUT_DIR = "sequential_results"
# ==========================================

# YOLOv8 Animals + Person
# 0: person
# 14: bird, 15: cat, 16: dog, 17: horse, 18: sheep, 19: cow, 
# 20: elephant, 21: bear, 22: zebra, 23: giraffe
YOLO_ANIMAL_CLASSES = [0, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]

def extract_cycle_id(filename):
    """
    ファイル名からサイクルIDを抽出する。
    想定形式:
    1. pi/main.pyアップロード形式: TIMESTAMP_CycleID-Index.jpg
    2. ESP32オリジナル形式: CycleID-Index.jpg
    """
    stem = os.path.splitext(filename)[0]
    # 末尾の "-Index" パターン ("-1", "-2", "-3", etc.) を探す
    match = re.search(r"-(\d+)[nd]?$", stem)
    
    if match:
        return stem[:match.start()]
    return "unknown"

def run_yolo_inference(model, image_path, conf_threshold):
    """
    YOLOv8推論を実行
    Returns: (is_detected, max_conf, label)
    """
    try:
        results = model(image_path, verbose=False, conf=conf_threshold, imgsz=640)
        
        if len(results) == 0 or not results[0].boxes:
            return False, 0.0, ""
        
        max_conf = 0.0
        best_label = ""
        is_det = False
        
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            
            if cls_id in YOLO_ANIMAL_CLASSES:
                # 閾値判定はmodel()のconf引数でも行われるが念のため
                if conf >= conf_threshold:
                    if conf > max_conf:
                        max_conf = conf
                        best_label = results[0].names[cls_id]
                    is_det = True
        
        return is_det, max_conf, best_label
    except Exception as e:
        print(f"Error in YOLO inference for {image_path}: {e}")
        return False, 0.0, ""

def run_md_inference(model, image_path, conf_threshold):
    """
    MegaDetector (YOLOv5) 推論を実行
    Returns: (is_detected, max_conf, label)
    """
    try:
        results = model(image_path)
        # xyxy[0] = [x1, y1, x2, y2, conf, cls]
        # MD v5: 1=animal, 2=person, 3=vehicle
        # Note: ユーザー環境によっては 0=animal のケースもあるようなので 0も考慮
        
        try:
            detections = results.xyxy[0]
        except:
            return False, 0.0, ""

        if len(detections) == 0:
            return False, 0.0, ""
        
        max_conf = 0.0
        best_label = ""
        is_det = False
        
        for *xyxy, conf, cls in detections:
            c = float(conf)
            if c < conf_threshold:
                continue
                
            cls_id = int(cls)
            
            # Target: Animal (1 or 0) + Person (2) ??
            # MD standard: 1=animal, 2=person, 3=vehicle
            # Assuming we want to detect animals and people as 'targets'
            if cls_id in [0, 1, 2]: 
                if c > max_conf:
                    max_conf = c
                    # ラベル名取得
                    if hasattr(model, 'names') and cls_id < len(model.names):
                        best_label = model.names[cls_id]
                    else:
                        best_label = str(cls_id)
                is_det = True
                
        return is_det, max_conf, best_label

    except Exception as e:
        print(f"Error in MD inference for {image_path}: {e}")
        return False, 0.0, ""

def main():
    parser = argparse.ArgumentParser(description='Sequential Model Comparison: YOLOv8 -> MegaDetector')
    parser.add_argument('--images', type=str, default=DEFAULT_IMAGE_DIR, help='Path to image directory')
    parser.add_argument('--md', type=str, default=DEFAULT_MD_MODEL_PATH, help='Path to MegaDetector model (.pt)')
    parser.add_argument('--yolo', type=str, default=DEFAULT_YOLO_MODEL_PATH, help='Path to YOLOv8 model (.pt)')
    parser.add_argument('--yolo-conf', type=float, default=DEFAULT_YOLO_CONF, help='YOLO confidence threshold (Stage 1)')
    parser.add_argument('--md-conf', type=float, default=DEFAULT_MD_CONF, help='MegaDetector confidence threshold (Stage 2)')
    parser.add_argument('--output', type=str, default=DEFAULT_OUTPUT_DIR, help='Output directory for results')
    
    args = parser.parse_args()

    image_dir = args.images
    md_path = args.md
    yolo_path = args.yolo
    output_dir = args.output
    
    # ---------------------------------------------------------
    # 1. Setup
    # ---------------------------------------------------------
    if not os.path.exists(image_dir):
        print(f"Error: Image directory not found: {image_dir}")
        # Windows環境でのテスト用に、カレントディレクトリなどをフォールバックとして探す処理を入れても良いが
        # ここでは厳密にエラーとする
        return

    os.makedirs(output_dir, exist_ok=True)
    
    # CSV Writer
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"sequential_report_{timestamp_str}.csv"
    csv_path = os.path.join(output_dir, csv_filename)
    
    csv_file = open(csv_path, 'w', newline='', encoding='utf-8')
    csv_writer = csv.writer(csv_file)
    header = ["Filename", "CycleID", "Stage1_YOLO_Result", "Stage2_MD_Result", "Final_Status", "YOLO_Conf", "MD_Conf", "YOLO_Label", "MD_Label"]
    csv_writer.writerow(header)

    # ---------------------------------------------------------
    # 2. Load Models
    # ---------------------------------------------------------
    print(f"Loading Models...")
    try:
        # YOLO
        print(f"  Loading YOLOv8: {yolo_path}")
        model_yolo = YOLO(yolo_path)
        
        # MD
        print(f"  Loading MegaDetector: {md_path}")
        model_md = torch.hub.load('ultralytics/yolov5', 'custom', path=md_path, trust_repo=True)
    except Exception as e:
        print(f"Error loading models: {e}")
        return

    # ---------------------------------------------------------
    # 3. Process Images
    # ---------------------------------------------------------
    print(f"Scanning images in {image_dir}...")
    extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp']
    image_files = []
    for ext in extensions:
        image_files.extend(glob.glob(os.path.join(image_dir, ext)))
        image_files.extend(glob.glob(os.path.join(image_dir, ext.upper())))
    image_files = sorted(list(set(image_files)))
    
    total_images = len(image_files)
    print(f"Found {total_images} images.")
    if total_images == 0:
        return

    # Statistics
    stats = {
        'total': total_images,
        'yolo_found': 0,
        'md_recovered': 0,
        'missed_both': 0
    }
    
    cycle_results = defaultdict(lambda: {'yolo_found': False, 'md_recovered': False, 'count': 0})

    print(f"\nStarting Pipeline Processing...")
    print(f"  Stage 1: YOLOv8 (Conf >= {args.yolo_conf})")
    print(f"  Stage 2: MegaDetector (Conf >= {args.md_conf}) [Only if YOLO fails]")

    for img_path in tqdm(image_files):
        filename = os.path.basename(img_path)
        cycle_id = extract_cycle_id(filename)
        
        # --- Stage 1: YOLO ---
        yolo_det, yolo_conf, yolo_label = run_yolo_inference(model_yolo, img_path, args.yolo_conf)
        
        md_det = False
        md_conf = 0.0
        md_label = ""
        final_status = "" # "Found_by_YOLO", "Recovered_by_MD", "Missed"

        if yolo_det:
            # YOLO detected mechanism
            final_status = "Found_by_YOLO"
            stats['yolo_found'] += 1
            cycle_results[cycle_id]['yolo_found'] = True
        else:
            # --- Stage 2: MegaDetector ---
            # Run MD only if YOLO missed
            md_det, md_conf, md_label = run_md_inference(model_md, img_path, args.md_conf)
            
            if md_det:
                final_status = "Recovered_by_MD"
                stats['md_recovered'] += 1
                cycle_results[cycle_id]['md_recovered'] = True
            else:
                final_status = "Missed"
                stats['missed_both'] += 1
        
        cycle_results[cycle_id]['count'] += 1
        
        # Log to CSV
        csv_writer.writerow([
            filename, 
            cycle_id, 
            "Detected" if yolo_det else "Missed", 
            "Detected" if md_det else ("Skipped" if yolo_det else "Missed"),
            final_status,
            f"{yolo_conf:.4f}", 
            f"{md_conf:.4f}" if not yolo_det else "",
            yolo_label, 
            md_label if not yolo_det else ""
        ])

    csv_file.close()

    # ---------------------------------------------------------
    # 4. Summary Output
    # ---------------------------------------------------------
    
    # Cycle Stats Calculation
    total_cycles = len(cycle_results)
    cycle_stats = {
        'yolo_found': 0,
        'md_recovered': 0,
        'missed_both': 0
    }
    
    for cid, res in cycle_results.items():
        if res['yolo_found']:
            cycle_stats['yolo_found'] += 1
        elif res['md_recovered']:
            # YOLO didn't find any in this cycle, but MD found at least one
            cycle_stats['md_recovered'] += 1
        else:
            # Neither found anything in this cycle
            cycle_stats['missed_both'] += 1

    print("\n" + "="*50)
    print(" RESULTS SUMMARY")
    print("="*50)
    
    print("\n[Per Image Basis]")
    print(f"  Total Images:      {stats['total']}")
    print(f"  Found by YOLO:     {stats['yolo_found']:>5} ({stats['yolo_found']/stats['total']*100:.1f}%)")
    print(f"  Recovered by MD:   {stats['md_recovered']:>5} ({stats['md_recovered']/stats['total']*100:.1f}%) <== UN-DETECTED REDUCTION")
    print(f"  Missed / Empty:    {stats['missed_both']:>5} ({stats['missed_both']/stats['total']*100:.1f}%)")
    
    print("\n[Per Cycle Basis]")
    print(f"  Total Cycles:      {total_cycles}")
    print(f"  Found by YOLO:     {cycle_stats['yolo_found']:>5} ({cycle_stats['yolo_found']/total_cycles*100:.1f}%)")
    print(f"  Recovered by MD:   {cycle_stats['md_recovered']:>5} ({cycle_stats['md_recovered']/total_cycles*100:.1f}%) <== UN-DETECTED REDUCTION")
    print(f"  Missed / Empty:    {cycle_stats['missed_both']:>5} ({cycle_stats['missed_both']/total_cycles*100:.1f}%)")
    
    print("\n" + "="*50)
    print(f"Detailed report saved to: {csv_path}")

if __name__ == "__main__":
    main()
