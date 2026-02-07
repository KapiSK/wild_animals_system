import os
import glob
import argparse
import re
import csv
import shutil
import glob
import argparse
import re
import csv
import shutil
import sys

try:
    from ultralytics import YOLO
    from tqdm import tqdm
except ImportError as e:
    print(f"Error: Missing required library: {e.name}")
    print("Please install the required packages using the following command:")
    print("pip install ultralytics tqdm torch torchvision")
    sys.exit(1)

from collections import defaultdict
import datetime

# ==========================================
# 設定: モデルと画像のパス
# ==========================================
# デフォルトの画像フォルダパス
DEFAULT_IMAGE_DIR = r"/home/slab/project/data/hykecam_1010/ALL/night/"
# MegaDetectorのモデルパス (.ptファイル)
# ※ユーザー環境に合わせて変更してください。ここでは仮のパスを設定しています。
DEFAULT_MD_MODEL_PATH = r"md_v5a.0.0.pt" 
# YOLOv8のモデルパス
DEFAULT_YOLO_MODEL_PATH = "yolov8n.pt"
# 信頼度閾値
DEFAULT_CONF_THRESHOLD = 0.25

# デフォルト出力先フォルダ
DEFAULT_OUTPUT_DIR = "compare_results"
# ==========================================

# ... (extract_cycle_id and is_detected are unchanged) ...

def main():
    parser = argparse.ArgumentParser(description='Compare MegaDetector and YOLOv8 performance.')
    parser.add_argument('--images', type=str, default=DEFAULT_IMAGE_DIR, help='Path to image directory')
    parser.add_argument('--md', type=str, default=DEFAULT_MD_MODEL_PATH, help='Path to MegaDetector model (.pt)')
    parser.add_argument('--yolo', type=str, default=DEFAULT_YOLO_MODEL_PATH, help='Path to YOLOv8 model (.pt)')
    parser.add_argument('--conf', type=float, default=DEFAULT_CONF_THRESHOLD, help='Confidence threshold')
    parser.add_argument('--output', type=str, default=DEFAULT_OUTPUT_DIR, help='Output directory for results')
    args = parser.parse_args()

    image_dir = args.images
    md_path = args.md
    yolo_path = args.yolo
    conf_threshold = args.conf
    output_dir = args.output

    if not os.path.exists(image_dir):
        print(f"Error: Image directory not found: {image_dir}")
        return

    # MegaDetectorモデルの存在確認
    if not os.path.exists(md_path):
        # ... (error handling) ...
        print(f"Warning: MegaDetector model not found at {md_path}.")
        print("Please specify the correct path using --md argument or edit the script.")
        # テスト用に続行できないのでreturn
        return

    # Output directories
    os.makedirs(output_dir, exist_ok=True)
    md_out_dir = os.path.join(output_dir, "md_detected")
    yolo_out_dir = os.path.join(output_dir, "yolo_detected")
    os.makedirs(md_out_dir, exist_ok=True)
    os.makedirs(yolo_out_dir, exist_ok=True)
    
    csv_path = os.path.join(output_dir, "detailed_log.csv")
    csv_file = open(csv_path, 'w', newline='', encoding='utf-8')
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["Filename", "CycleID", "YOLO_Detected", "MD_Detected", "YOLO_Conf", "MD_Conf"])


    print(f"Loading Models...")
    print(f"  MegaDetector: {md_path}")
    print(f"  YOLOv8: {yolo_path}")

    print(f"Loading Models...")
    print(f"  MegaDetector: {md_path}")
    print(f"  YOLOv8: {yolo_path}")

    try:
        # YOLOv8 Load
        model_yolo = YOLO(yolo_path)
        
        # MegaDetector (YOLOv5) Load using torch.hub
        import torch
        # force_reload=False to use cache if available, trust_repo=True required for recent torch versions
        model_md = torch.hub.load('ultralytics/yolov5', 'custom', path=md_path, trust_repo=True) 
    except Exception as e:
        print(f"Error loading models: {e}")
        return

    # 画像リスト取得
    print(f"Scanning images in {image_dir}...")
    extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp']
    image_files = []
    for ext in extensions:
        image_files.extend(glob.glob(os.path.join(image_dir, ext)))
        image_files.extend(glob.glob(os.path.join(image_dir, ext.upper())))
    image_files = sorted(list(set(image_files)))
    
    total_images = len(image_files)
    if total_images == 0:
        print("No images found.")
        return

    print(f"Processing {total_images} images...")

    # 結果保持用
    img_results = [] # {filename, md_det, yolo_det, cycle_id}
    
    # tqdmあれば使用
    try:
        from tqdm import tqdm
        iterator = tqdm(image_files)
    except ImportError:
        iterator = image_files

    for img_path in iterator:
        try:
            filename = os.path.basename(img_path)
            
            # YOLO Inference (YOLOv8)
            res_yolo = model_yolo(img_path, verbose=False, conf=conf_threshold)
            det_yolo = is_detected(res_yolo, conf_threshold, 'yolo')
            # Get max conf for logging
            yolo_conf = 0.0
            if det_yolo:
                 # is_detected just returns bool, need to extract conf again or modify is_detected?
                 # Simpler to re-extract here or modify is_detected to return conf.
                 # Let's simple re-extract max conf for animal classes
                 # YOLOv8 (COCO):
                 # 14: bird, 15: cat, 16: dog, 17: horse, 18: sheep, 19: cow, 
                 # 20: elephant, 21: bear, 22: zebra, 23: giraffe
                 animal_classes = [14, 15, 16, 17, 18, 19, 20, 21, 22, 23] 
                 for box in res_yolo[0].boxes:
                     if int(box.cls[0]) in animal_classes:
                         yolo_conf = max(yolo_conf, float(box.conf[0]))

            # MD Inference (YOLOv5)
            # YOLOv5 returns a generic Models object, distinct from YOLOv8 Results
            res_md = model_md(img_path) 
            # res_md.xyxy[0] contains detections: [x1, y1, x2, y2, conf, cls]
            det_md = is_detected(res_md, conf_threshold, 'md')
            # Get max conf for logging
            md_conf = 0.0
            if det_md:
                try:
                    for *xyxy, conf, cls in res_md.xyxy[0]:
                        if int(cls) == 1: # MegaDetector: 1=animal
                            md_conf = max(md_conf, float(conf))
                except: pass

            cycle_id = extract_cycle_id(filename)
            
            img_results.append({
                'filename': filename,
                'md': det_md,
                'yolo': det_yolo,
                'cycle': cycle_id
            })
            
            # Log to CSV
            csv_writer.writerow([filename, cycle_id, det_yolo, det_md, f"{yolo_conf:.4f}", f"{md_conf:.4f}"])

            # Save Images
            if det_yolo:
                shutil.copy2(img_path, os.path.join(yolo_out_dir, filename))
            if det_md:
                shutil.copy2(img_path, os.path.join(md_out_dir, filename))
            
        except Exception as e:
            print(f"Error processing {os.path.basename(img_path)}: {e}")

    csv_file.close()

    # --- 集計 ---
    
    # 1. 画像ごとの比較
    img_stats = {
        'both': 0,
        'md_only': 0,
        'yolo_only': 0,
        'neither': 0
    }
    
    for r in img_results:
        if r['md'] and r['yolo']:
            img_stats['both'] += 1
        elif r['md'] and not r['yolo']:
            img_stats['md_only'] += 1
        elif not r['md'] and r['yolo']:
            img_stats['yolo_only'] += 1
        else:
            img_stats['neither'] += 1

    # 2. サイクルごとの比較
    # サイクル内で1枚でも検知されれば「検知あり」とする
    cycle_data = defaultdict(lambda: {'md': False, 'yolo': False, 'count': 0})
    for r in img_results:
        cid = r['cycle']
        if r['md']: cycle_data[cid]['md'] = True
        if r['yolo']: cycle_data[cid]['yolo'] = True
        cycle_data[cid]['count'] += 1
        
    cycle_stats = {
        'both': 0,
        'md_only': 0,
        'yolo_only': 0,
        'neither': 0
    }
    
    for cid, data in cycle_data.items():
        if data['md'] and data['yolo']:
            cycle_stats['both'] += 1
        elif data['md'] and not data['yolo']:
            cycle_stats['md_only'] += 1
        elif not data['md'] and data['yolo']:
            cycle_stats['yolo_only'] += 1
        else:
            cycle_stats['neither'] += 1

    # --- 結果出力 ---
    print("\n" + "="*40)
    print(" SUMMARY")
    print("="*40)
    
    print("\n[Per Image] Total:", len(img_results))
    print(f"  Both Detected:   {img_stats['both']:>5}")
    print(f"  MD Only:         {img_stats['md_only']:>5}")
    print(f"  YOLO Only:       {img_stats['yolo_only']:>5}")
    print(f"  Neither:         {img_stats['neither']:>5}")

    print("\n[Per Cycle] Total:", len(cycle_data))
    print(f"  Both Detected:   {cycle_stats['both']:>5}")
    print(f"  MD Only:         {cycle_stats['md_only']:>5}")
    print(f"  YOLO Only:       {cycle_stats['yolo_only']:>5}")
    print(f"  Neither:         {cycle_stats['neither']:>5}")

if __name__ == "__main__":
    main()
