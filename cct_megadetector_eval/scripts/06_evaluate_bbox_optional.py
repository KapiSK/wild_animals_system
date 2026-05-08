import os
import argparse
import pandas as pd
from src.utils import load_config, ensure_dir, setup_logger
from src.cct_io import load_coco_json
from src.md_io import load_md_json
from src.metrics import greedy_match_boxes

logger = setup_logger("06_evaluate_bbox_optional")

def extract_gt_boxes(bbox_json, animal_category_id=None):
    """
    COCO BBox JSONから、画像ごとのGT bboxリストを抽出する。
    bbox format: [xmin, ymin, width, height] (絶対座標)
    戻り値: dict[image_id, list_of_bboxes]
    """
    logger.info("Extracting GT bounding boxes...")
    ann_dict = {}
    
    # カテゴリマッピングの構築
    # CCTでは "empty" 以外を全て動物として扱う
    cat_map = {}
    for cat in bbox_json.get("categories", []):
        cat_map[cat["id"]] = cat["name"]
        
    for ann in bbox_json.get("annotations", []):
        cat_name = cat_map.get(ann["category_id"], "")
        if str(cat_name).lower() == "empty":
            continue
            
        img_id = ann["image_id"]
        bbox = ann.get("bbox", [])
        if not bbox:
            continue
            
        if img_id not in ann_dict:
            ann_dict[img_id] = []
        ann_dict[img_id].append(bbox)
        
    return ann_dict

def extract_md_boxes(md_json, animal_category_id="1", threshold=0.1):
    """
    MegaDetector JSONから、画像ごとの予測bboxリストを抽出する。
    MegaDetector bbox format: [xmin, ymin, width, height] (正規化座標)
    戻り値: dict[file_name, list_of_bboxes]
    """
    logger.info("Extracting MD bounding boxes...")
    md_dict = {}
    for img in md_json.get("images", []):
        file_name = img.get("file", "")
        bboxes = []
        for det in img.get("detections", []):
            if str(det.get("category")) == str(animal_category_id):
                if det.get("conf", 0.0) >= threshold:
                    bboxes.append(det.get("bbox"))
        if bboxes:
            md_dict[file_name] = bboxes
    return md_dict

def main():
    parser = argparse.ArgumentParser(description="Evaluate MegaDetector bounding box performance.")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()
    
    cfg = load_config(args.config)
    
    bbox_json_path = cfg["paths"]["bbox_annotations"]
    md_results_dir = cfg["paths"]["md_results_dir"]
    output_dir = cfg["paths"]["output_dir"]
    
    thresholds = cfg["evaluation"]["thresholds"]
    animal_category_id = str(cfg["evaluation"]["animal_category_id_in_md"])
    iou_thresh = cfg["evaluation"]["iou_threshold"]
    models = cfg["megadetector"]["models"]
    
    if not os.path.exists(bbox_json_path):
        logger.warning(f"BBox annotations not found: {bbox_json_path}. Skipping BBox evaluation.")
        return
        
    logger.info("Loading CCT bbox annotations...")
    bbox_json = load_coco_json(bbox_json_path)
    
    # image_id -> file_name マッピング作成と、画像サイズ取得
    id_to_file = {}
    id_to_size = {} # image_id -> (width, height)
    for img in bbox_json.get("images", []):
        id_to_file[img["id"]] = img["file_name"]
        if "width" in img and "height" in img:
            id_to_size[img["id"]] = (img["width"], img["height"])
            
    gt_dict_id = extract_gt_boxes(bbox_json)
    
    # file_name に変換し、画像サイズで正規化を解除（GTが絶対座標、MDが正規化座標のため、MDを絶対座標に戻す）
    # 実装方針: GTもMDも絶対座標で比較する
    
    all_results = []
    
    for model_key, model_info in models.items():
        model_name = model_info["model_name"]
        output_json = os.path.join(md_results_dir, model_info["output_json"])
        
        if not os.path.exists(output_json):
            continue
            
        md_data = load_md_json(output_json)
        
        for th in thresholds:
            md_dict_file = extract_md_boxes(md_data, animal_category_id, th)
            
            total_tp, total_fp, total_fn = 0, 0, 0
            
            for img_id, gt_boxes in gt_dict_id.items():
                file_name = id_to_file.get(img_id, "")
                if not file_name:
                    continue
                    
                file_name_norm = file_name.replace("\\", "/")
                # md_dict_file のキーも正規化されているか確認
                matched_md_key = None
                for k in md_dict_file.keys():
                    if k.replace("\\", "/") == file_name_norm:
                        matched_md_key = k
                        break
                        
                md_norm_boxes = md_dict_file.get(matched_md_key, [])
                
                # MDの正規化座標を絶対座標に変換
                w, h = id_to_size.get(img_id, (1, 1))
                if w == 1 and h == 1 and len(md_norm_boxes) > 0:
                    # 画像サイズが取得できない場合はスキップ
                    continue
                    
                md_abs_boxes = []
                for b in md_norm_boxes:
                    # MD bbox: [xmin, ymin, w, h] (normalized)
                    abs_box = [b[0]*w, b[1]*h, b[2]*w, b[3]*h]
                    md_abs_boxes.append(abs_box)
                    
                tp, fp, fn = greedy_match_boxes(gt_boxes, md_abs_boxes, iou_thresh)
                total_tp += tp
                total_fp += fp
                total_fn += fn
                
            precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
            recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
            
            all_results.append({
                "model": model_name,
                "threshold": th,
                "bbox_precision": precision,
                "bbox_recall": recall,
                "bbox_f1": f1,
                "bbox_tp": total_tp,
                "bbox_fp": total_fp,
                "bbox_fn": total_fn
            })
            
    if all_results:
        df_bbox = pd.DataFrame(all_results)
        bbox_csv = os.path.join(output_dir, "bbox_threshold_summary.csv")
        df_bbox.to_csv(bbox_csv, index=False)
        logger.info(f"Saved BBox evaluation summary to {bbox_csv}")

if __name__ == "__main__":
    main()
