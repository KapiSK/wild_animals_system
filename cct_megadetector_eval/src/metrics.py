import numpy as np
import pandas as pd
from typing import Dict, Any, List
from sklearn.metrics import precision_score, recall_score, f1_score, confusion_matrix
from src.utils import setup_logger

logger = setup_logger(__name__)

def compute_binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """2値分類（Animal vs Empty）のメトリクスを計算する"""
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    
    precision = precision_score(y_true, y_pred, zero_division=0)
    recall = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    
    empty_fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    animal_fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
    
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": int(tp),
        "fp": int(fp),
        "fn": int(fn),
        "tn": int(tn),
        "empty_false_positive_rate": empty_fpr,
        "animal_false_negative_rate": animal_fnr,
        "n_images_evaluated": len(y_true)
    }

def evaluate_thresholds(gt_df: pd.DataFrame, pred_df: pd.DataFrame, thresholds: List[float]) -> pd.DataFrame:
    """複数の閾値に対してメトリクスを計算する"""
    # file_name で結合（パス区切り文字の違いを吸収するため正規化しておく）
    gt_df = gt_df.copy()
    pred_df = pred_df.copy()
    
    gt_df["file_name_norm"] = gt_df["file_name"].apply(lambda x: x.replace("\\", "/"))
    pred_df["file_name_norm"] = pred_df["file_name"].apply(lambda x: x.replace("\\", "/"))
    
    merged = pd.merge(gt_df, pred_df, on="file_name_norm", how="inner")
    
    if len(merged) != len(gt_df):
        logger.warning(f"Merge size mismatch: GT has {len(gt_df)}, merged has {len(merged)}. Check file names.")
        
    y_true = merged["animal_gt"].values
    max_confs = merged["max_conf"].values
    
    results = []
    for th in thresholds:
        y_pred = (max_confs >= th).astype(int)
        metrics = compute_binary_metrics(y_true, y_pred)
        metrics["threshold"] = th
        results.append(metrics)
        
    return pd.DataFrame(results)

def compute_iou(box_a: List[float], box_b: List[float]) -> float:
    """IoUを計算する (box: [xmin, ymin, width, height] 形式を想定)"""
    # 座標変換: [xmin, ymin, xmax, ymax]
    a_x1, a_y1 = box_a[0], box_a[1]
    a_x2, a_y2 = a_x1 + box_a[2], a_y1 + box_a[3]
    
    b_x1, b_y1 = box_b[0], box_b[1]
    b_x2, b_y2 = b_x1 + box_b[2], b_y1 + box_b[3]
    
    inter_x1 = max(a_x1, b_x1)
    inter_y1 = max(a_y1, b_y1)
    inter_x2 = min(a_x2, b_x2)
    inter_y2 = min(a_y2, b_y2)
    
    inter_area = max(0, inter_x2 - inter_x1) * max(0, inter_y2 - inter_y1)
    
    box_a_area = box_a[2] * box_a[3]
    box_b_area = box_b[2] * box_b[3]
    
    union_area = box_a_area + box_b_area - inter_area
    
    if union_area == 0:
        return 0.0
    return inter_area / union_area

def greedy_match_boxes(gt_boxes: List[List[float]], pred_boxes: List[List[float]], iou_threshold: float = 0.5) -> Tuple[int, int, int]:
    """IoUベースでGreedyにBoxをマッチングし、TP, FP, FNを返す"""
    tp = 0
    matched_gt = set()
    matched_pred = set()
    
    # 全組み合わせのIoUを計算
    ious = []
    for i, gbox in enumerate(gt_boxes):
        for j, pbox in enumerate(pred_boxes):
            iou = compute_iou(gbox, pbox)
            if iou >= iou_threshold:
                ious.append((iou, i, j))
                
    # IoUが高い順にソートしてマッチング
    ious.sort(key=lambda x: x[0], reverse=True)
    
    for iou, i, j in ious:
        if i not in matched_gt and j not in matched_pred:
            tp += 1
            matched_gt.add(i)
            matched_pred.add(j)
            
    fp = len(pred_boxes) - len(matched_pred)
    fn = len(gt_boxes) - len(matched_gt)
    
    return tp, fp, fn
