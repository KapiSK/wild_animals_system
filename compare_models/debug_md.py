import os
import glob
import argparse
import sys
import torch

# デフォルトの画像フォルダパス
DEFAULT_IMAGE_DIR = r"/home/satoko/project/hykecam_1010/ALL/night/"
# MegaDetectorのモデルパス
DEFAULT_MD_MODEL_PATH = r"md_v5a.0.0.pt"

def main():
    parser = argparse.ArgumentParser(description='Debug MegaDetector performance.')
    parser.add_argument('--images', type=str, default=DEFAULT_IMAGE_DIR, help='Path to image directory')
    parser.add_argument('--md', type=str, default=DEFAULT_MD_MODEL_PATH, help='Path to MegaDetector model (.pt)')
    args = parser.parse_args()

    image_dir = args.images
    md_path = args.md

    if not os.path.exists(md_path):
        print(f"Error: MegaDetector model not found at {md_path}")
        return

    print(f"Loading MegaDetector model from {md_path}...")
    try:
        model = torch.hub.load('ultralytics/yolov5', 'custom', path=md_path, trust_repo=True)
    except Exception as e:
        print(f"Error loading model: {e}")
        return

    # Check model classes
    print("Model Classes:", model.names)

    # Scan images
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

    print(f"Found {len(image_files)} images. Processing first 5...")

    for i, img_path in enumerate(image_files[:5]):
        print(f"\nProcessing: {os.path.basename(img_path)}")
        results = model(img_path)
        
        # Print raw detections
        # results.xyxy[0] = [x1, y1, x2, y2, conf, cls]
        detections = results.xyxy[0]
        if len(detections) == 0:
            print("  No detections.")
        else:
            for *xyxy, conf, cls in detections:
                cls_id = int(cls)
                label = model.names[cls_id] if cls_id < len(model.names) else "Unknown"
                print(f"  Detected: Class={cls_id} ({label}), Conf={conf:.4f}, BBox={xyxy}")

if __name__ == "__main__":
    main()
