from ultralytics import YOLO
import os
import argparse
import glob

# ==========================================
# 設定: 画像フォルダのパスをここに記述してください
DEFAULT_SOURCE_PATH = r"C:\Users\kapib\OneDrive - 信州大学\Lab\hykecam_1010\hykecam_1010\ALL\night"
# ==========================================

def main():
    parser = argparse.ArgumentParser(description='Count images with YOLOv8 detections.')
    parser.add_argument('source', type=str, nargs='?', default=DEFAULT_SOURCE_PATH, help='Path to the image folder')
    args = parser.parse_args()

    source_dir = args.source
    if not source_dir:
         print("Error: No source directory specified. Please set DEFAULT_SOURCE_PATH or provide it as an argument.")
         return

    if not os.path.isdir(source_dir):
        print(f"Error: Directory not found: {source_dir}")
        return

    # Initialize YOLOv8n model
    try:
        model = YOLO('yolov8n.pt')
    except Exception as e:
        print(f"Error loading model: {e}")
        return

    # Get list of images
    image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.webp']
    image_files = []
    for ext in image_extensions:
        image_files.extend(glob.glob(os.path.join(source_dir, ext)))
        # Also check uppercase extensions
        image_files.extend(glob.glob(os.path.join(source_dir, ext.upper())))
    
    # Remove duplicates if any (e.g. casing differences on some OS)
    image_files = sorted(list(set(image_files)))

    total_images = len(image_files)
    if total_images == 0:
        print(f"No images found in {source_dir}")
        return

    detected_count = 0
    print(f"Processing {total_images} images in {source_dir}...")

    # Try to import tqdm for progress bar
    try:
        from tqdm import tqdm
        iterator = tqdm(image_files, desc="Processing")
    except ImportError:
        print("tqdm not found, using simple progress printing.")
        iterator = image_files

    try:
        for i, img_path in enumerate(iterator):
            # If tqdm is not available, print progress every 100 images
            if isinstance(iterator, list) and i % 100 == 0:
                 print(f"Processing {i}/{total_images}...")

            try:
                # Run inference
                results = model(img_path, verbose=False) # verbose=False to reduce output clutter
                
                # Check if any objects were detected
                if len(results) > 0 and len(results[0].boxes) > 0:
                    detected_count += 1
                
            except Exception as e:
                print(f"Error processing {os.path.basename(img_path)}: {e}")
                
    except KeyboardInterrupt:
        print("\nProcessing interrupted by user.")
        # Re-calculate total based on how many were actually processed if needed, 
        # but simpler to just show what we found so far out of total attempted.
        # Since we use 'for img_path in ...', we might not know exactly 'i' if we blindly break.
        # But we can assume 'detected_count' is accurate for the ones we finished.
        print("Showing partial results...")


    # Output results
    percentage = (detected_count / total_images) * 100 if total_images > 0 else 0
    print("-" * 30)
    print(f"Total Images: {total_images}")
    print(f"Images with Detections: {detected_count}")
    print(f"Detection Rate: {percentage:.2f}%")
    print("-" * 30)

if __name__ == "__main__":
    main()
