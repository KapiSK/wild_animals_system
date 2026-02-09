import os
import glob
import argparse
import re
import csv
import shutil
import sys
from collections import defaultdict
import datetime

try:
    from ultralytics import YOLO
    from tqdm import tqdm
except ImportError as e:
    print(f"Error: Missing required library: {e.name}")
    print("Please install the required packages using the following command:")
    print("pip install ultralytics tqdm torch torchvision")
    sys.exit(1)

# ==========================================
# 設定: モデルと画像のパス
# ==========================================
# デフォルトの画像フォルダパス
DEFAULT_IMAGE_DIR = r"/home/satoko/project/hykecam_1010/ALL/night/"
# MegaDetectorのモデルパス (.ptファイル)
# ※ユーザー環境に合わせて変更してください。ここでは仮のパスを設定しています。
DEFAULT_MD_MODEL_PATH = r"md_v5a.0.0.pt" 
# YOLOv8のモデルパス
DEFAULT_YOLO_MODEL_PATH = "yolov8n.pt"
# 信頼度閾値
# 信頼度閾値 (パイプラインシミュレーション用)
DEFAULT_YOLO_CONF = 0.1  # エッジ側は低めに設定して取りこぼしを防ぐ
DEFAULT_MD_CONF = 0.25   # クラウド側は標準的な閾値

# デフォルト出力先フォルダ
DEFAULT_OUTPUT_DIR = "compare_results"
# ==========================================

def extract_cycle_id(filename):
    """
    ファイル名からサイクルIDを抽出する。
    想定形式:
    1. pi/main.pyアップロード形式: TIMESTAMP_CycleID-Index.jpg
    2. ESP32オリジナル形式: CycleID-Index.jpg
    """
    # 拡張子を除去
    stem = os.path.splitext(filename)[0]
    
    # 末尾の "-Index" パターン ("-1", "-2", "-3", etc.) を探す
    # Indexの後ろに 'n' や 'd' がつく場合もある (-1n.jpg)
    match = re.search(r"-(\d+)[nd]?$", stem)
    
    if match:
        # Indexより前の部分を取得
        prefix = stem[:match.start()]
        
        # main.py形式の場合、TIMESTAMP_部分を除去したい
        # しかし、CycleID自体にアンダースコアが含まれる可能性があるため、単純なsplitは危険。
        # ここでは、「末尾のIndexを除いたもの」をサイクルIDとして扱う簡易実装とする。
        # 厳密にTIMESTAMPを除くには、"YYYYMMDD_HHMMSS_ffffff_" のパターン詳細が必要だが、
        # 比較目的では「同じサイクルかどうか」が重要なので、プレフィックス込みでもグルーピングは可能。
        return prefix
        
    return "unknown"

def is_detected(results, conf_threshold, model_type='yolo'):
    """
    推論結果から動物が検知されたか判定する
    """
    if model_type == 'md':
        # MegaDetector (YOLOv5 via torch.hub) returns a Detections object
        # results.xyxy[0] is a tensor of shape (N, 6) [x1, y1, x2, y2, conf, cls]
        try:
             # results.xyxy is a list of tensors (one per image in batch)
             # We processed one image, so take index 0
             detections = results.xyxy[0] 
        except:
             return False

        if len(detections) == 0:
            return False

        for *xyxy, conf, cls in detections:
            if conf < conf_threshold:
                continue
                
            cls_id = int(cls)
            # MegaDetector v5 usually uses 1=animal, but some versions/loaders might map it to 0.
            # We treat 0 and 1 as potentially 'animal' if we are unsure, 
            # but usually 2=person, 3=vehicle.
            # If user report says only 0 is detected, likely 0 is animal in this context.
            if cls_id == 1 or cls_id == 0: 
                return True
        return False

    else:
        # YOLOv8 (ultralytics) returns a list of Results objects
        if len(results) == 0:
            return False
        
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return False

        # YOLOv8 (COCO):
        # 0: person
        # 14: bird, 15: cat, 16: dog, 17: horse, 18: sheep, 19: cow, 
        # 20: elephant, 21: bear, 22: zebra, 23: giraffe
        animal_classes = [0, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23] 
        
        for box in boxes:
            if box.conf[0] < conf_threshold:
                continue
                
            cls_id = int(box.cls[0])
            if cls_id in animal_classes:
                return True
        
        return False

def main():
    parser = argparse.ArgumentParser(description='Compare MegaDetector and YOLOv8 performance.')
    parser.add_argument('--images', type=str, default=DEFAULT_IMAGE_DIR, help='Path to image directory')
    parser.add_argument('--md', type=str, default=DEFAULT_MD_MODEL_PATH, help='Path to MegaDetector model (.pt)')
    parser.add_argument('--yolo', type=str, default=DEFAULT_YOLO_MODEL_PATH, help='Path to YOLOv8 model (.pt)')
    parser.add_argument('--yolo-conf', type=float, default=DEFAULT_YOLO_CONF, help='YOLO confidence threshold (Edge)')
    parser.add_argument('--md-conf', type=float, default=DEFAULT_MD_CONF, help='MegaDetector confidence threshold (Cloud)')
    parser.add_argument('--output', type=str, default=DEFAULT_OUTPUT_DIR, help='Output directory for results')
    args = parser.parse_args()

    image_dir = args.images
    md_path = args.md
    yolo_path = args.yolo
    yolo_conf_threshold = args.yolo_conf
    md_conf_threshold = args.md_conf
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
    csv_writer.writerow(["Filename", "CycleID", "YOLO_Detected", "MD_Detected", "YOLO_Conf", "MD_Conf", "YOLO_Label", "MD_Label"])


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
        print(f"MD Model Classes: {model_md.names}") 
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
            res_yolo = model_yolo(img_path, verbose=False, conf=yolo_conf_threshold, imgsz=640)
            det_yolo = is_detected(res_yolo, yolo_conf_threshold, 'yolo')
            # Get max conf and label for logging
            yolo_conf = 0.0
            yolo_label = ""
            if len(res_yolo) > 0 and res_yolo[0].boxes and len(res_yolo[0].boxes) > 0:
                 # Find the box with highest confidence
                 max_conf_box = max(res_yolo[0].boxes, key=lambda x: x.conf[0])
                 yolo_conf = float(max_conf_box.conf[0])
                 yolo_label = res_yolo[0].names[int(max_conf_box.cls[0])]

            # MD Inference (YOLOv5)
            # YOLOv5 returns a generic Models object, distinct from YOLOv8 Results
            res_md = model_md(img_path) 
            # res_md.xyxy[0] contains detections: [x1, y1, x2, y2, conf, cls]
            det_md = is_detected(res_md, md_conf_threshold, 'md')
            # Get max conf and label for logging
            md_conf = 0.0
            md_label = ""
            try:
                detections = res_md.xyxy[0]
                if len(detections) > 0:
                    # Find detection with highest confidence
                    best_det = max(detections, key=lambda x: x[4])
                    best_conf = float(best_det[4])
                    best_cls = int(best_det[5])
                    
                    md_conf = best_conf
                    
                    # Try to use model names if available
                    if hasattr(model_md, 'names') and best_cls < len(model_md.names):
                        md_label = model_md.names[best_cls]
                    else:
                        # MegaDetector v5 fallback: 1=animal, 2=person, 3=vehicle
                        # But user says 0 is detected.
                        md_names = {1: 'animal', 2: 'person', 3: 'vehicle', 0: 'animal?'}
                        md_label = md_names.get(best_cls, str(best_cls))
            except: pass

            cycle_id = extract_cycle_id(filename)
            
            img_results.append({
                'filename': filename,
                'md': det_md,
                'yolo': det_yolo,
                'cycle': cycle_id
            })
            
            # Log to CSV
            csv_writer.writerow([filename, cycle_id, det_yolo, det_md, f"{yolo_conf:.4f}", f"{md_conf:.4f}", yolo_label, md_label])

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

    # --- Edge-Cloud Simulation Analysis ---
    print("\n" + "="*40)
    print(" EDGE-CLOUD PIPELINE SIMULATION")
    print("="*40)
    print(f"Edge Threshold (YOLO): {yolo_conf_threshold}")
    print(f"Cloud Threshold (MD):  {md_conf_threshold}")
    
    lost_at_edge_count = img_stats['md_only']
    print("\n[Analysis]")
    print(f"Lost at Edge (MD detected, YOLO missed): {lost_at_edge_count}")
    if lost_at_edge_count > 0:
        print(f"  -> WARNING: {lost_at_edge_count} images would be lost at the edge.")
        print("     Consider lowering the YOLO threshold (--yolo-conf).")
    else:
        print("  -> EXCELLENT: No images lost at the edge with current settings.")

    # Calculate reduction rate (how many images are filtered out by Edge)
    filtered_at_edge = img_stats['neither'] + img_stats['md_only'] # simple approximation if we assume only yolo detects pass
    # Actually, filtered at edge = (total - yolo_detected)
    # yolo_detected = both + yolo_only
    yolo_detected_count = img_stats['both'] + img_stats['yolo_only']
    reduction_rate = (1 - (yolo_detected_count / len(img_results))) * 100
    
    print(f"\nEdge Filter Rate: {reduction_rate:.1f}%")
    print(f"  - Total Images: {len(img_results)}")
    print(f"  - Sent to Cloud: {yolo_detected_count}")
    print(f"  - Filtered Out: {len(img_results) - yolo_detected_count}")

if __name__ == "__main__":
    main()
