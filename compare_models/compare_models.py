import os
import glob
import argparse
import re
import matplotlib.pyplot as plt
from ultralytics import YOLO
from collections import defaultdict
import datetime

# ==========================================
# 設定: モデルと画像のパス
# ==========================================
# デフォルトの画像フォルダパス
DEFAULT_IMAGE_DIR = r"C:\Users\kapib\OneDrive - 信州大学\Lab\hykecam_1010\hykecam_1010\ALL\day"
# MegaDetectorのモデルパス (.ptファイル)
# ※ユーザー環境に合わせて変更してください。ここでは仮のパスを設定しています。
DEFAULT_MD_MODEL_PATH = r"md_v5a.0.0.pt" 
# YOLOv8のモデルパス
DEFAULT_YOLO_MODEL_PATH = "yolov8n.pt"

# 出力先フォルダ
OUTPUT_DIR = "compare_results"
# ==========================================

def setup_fonts():
    # 日本語フォントの設定（matplotlib用）
    # Windowsの代表的な日本語フォントを試行
    fonts = ['Meiryo', 'Yu Gothic', 'MS Gothic']
    for font in fonts:
        try:
            plt.rcParams['font.family'] = font
            break
        except:
            continue

def extract_cycle_id(filename):
    """
    ファイル名からサイクルIDを抽出する。
    想定形式:
    1. pi/main.pyアップロード形式: TIMESTAMP_CycleID-Index.jpg
    2. ESP32オリジナル形式: CycleID-Index.jpg
    """
    # 拡張子を除去
    stem = os.path.splitext(filename)[0]
    
    # 末尾の "-Index" パターン ("-1", "-2", "-3") を探す
    # Indexの後ろに 'n' や 'd' がつく場合もある (-1n.jpg)
    match = re.search(r"-(1|2|3)[nd]?$", stem)
    
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

def is_detected(results, model_type='yolo'):
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
            cls_id = int(cls)
            # MegaDetector: 1=animal
            if cls_id == 1: 
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
        # 14: bird, 15: cat, 16: dog, 17: horse, 18: sheep, 19: cow, 
        # 20: elephant, 21: bear, 22: zebra, 23: giraffe
        animal_classes = [14, 15, 16, 17, 18, 19, 20, 21, 22, 23] 
        
        for box in boxes:
            cls_id = int(box.cls[0])
            if cls_id in animal_classes:
                return True
        
        return False

def main():
    parser = argparse.ArgumentParser(description='Compare MegaDetector and YOLOv8 performance.')
    parser.add_argument('--images', type=str, default=DEFAULT_IMAGE_DIR, help='Path to image directory')
    parser.add_argument('--md', type=str, default=DEFAULT_MD_MODEL_PATH, help='Path to MegaDetector model (.pt)')
    parser.add_argument('--yolo', type=str, default=DEFAULT_YOLO_MODEL_PATH, help='Path to YOLOv8 model (.pt)')
    args = parser.parse_args()

    image_dir = args.images
    md_path = args.md
    yolo_path = args.yolo

    if not os.path.exists(image_dir):
        print(f"Error: Image directory not found: {image_dir}")
        return

    # MegaDetectorモデルの存在確認
    if not os.path.exists(md_path):
        print(f"Warning: MegaDetector model not found at {md_path}.")
        print("Please specify the correct path using --md argument or edit the script.")
        # テスト用に続行できないのでreturn
        return

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
            res_yolo = model_yolo(img_path, verbose=False)
            det_yolo = is_detected(res_yolo, 'yolo')
            
            # MD Inference (YOLOv5)
            # YOLOv5 returns a generic Models object, distinct from YOLOv8 Results
            res_md = model_md(img_path) 
            # res_md.xyxy[0] contains detections: [x1, y1, x2, y2, conf, cls]
            det_md = is_detected(res_md, 'md')
            
            cycle_id = extract_cycle_id(filename)
            
            img_results.append({
                'filename': filename,
                'md': det_md,
                'yolo': det_yolo,
                'cycle': cycle_id
            })
            
        except Exception as e:
            print(f"Error processing {os.path.basename(img_path)}: {e}")

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

    # --- 可視化 ---
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    setup_fonts()
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))
    
    labels = ['Both', 'MD Only', 'YOLO Only', 'Neither']
    colors = ['#2ca02c', '#1f77b4', '#ff7f0e', '#7f7f7f'] # Green, Blue, Orange, Gray
    
    # Image Pie Chart
    sizes_img = [img_stats['both'], img_stats['md_only'], img_stats['yolo_only'], img_stats['neither']]
    ax1.pie(sizes_img, labels=labels, autopct='%1.1f%%', startangle=90, colors=colors)
    ax1.set_title(f'Per Image (n={len(img_results)})')

    # Cycle Pie Chart
    sizes_cycle = [cycle_stats['both'], cycle_stats['md_only'], cycle_stats['yolo_only'], cycle_stats['neither']]
    ax2.pie(sizes_cycle, labels=labels, autopct='%1.1f%%', startangle=90, colors=colors)
    ax2.set_title(f'Per Cycle (n={len(cycle_data)})')

    plt.suptitle("MegaDetector vs YOLOv8 Performance Comparison")
    
    save_path = os.path.join(OUTPUT_DIR, 'comparison_chart.png')
    plt.savefig(save_path)
    print(f"\nChart saved to: {save_path}")
    # plt.show() # CLI実行時は表示しない方が安全な場合が多い

if __name__ == "__main__":
    main()
