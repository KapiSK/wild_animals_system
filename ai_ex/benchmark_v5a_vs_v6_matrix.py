import os
import sys
import time
import cv2
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from pathlib import Path
from sklearn.metrics import confusion_matrix
import torch
import yolov5
from PytorchWildlife.models import detection as pw_detection

# ==========================================
# 1. 設定ブロック (Configuration)
# ==========================================
# 画像フォルダのパス (このスクリプトからの相対パス、または絶対パス)
INPUT_DIR = Path(__file__).parent / "/home/satoko/project/hykecam_1010/ALL/day/"

# 出力先フォルダ
OUTPUT_DIR = Path(__file__).parent / "/home/satoko/project/hykecam_1010/ALL/day/"
MISMATCH_DIR = OUTPUT_DIR / "/home/satoko/project/hykecam_1010/ALL/day/mismatch"

# V5a モデルのパス (プロジェクトルート)
V5A_MODEL_PATH = Path(__file__).parent.parent / "md_v5a.0.0.pt"

# 各モデルの信頼度閾値
V5A_CONF_THRESHOLD = 0.25
V6_CONF_THRESHOLD = 0.25

# 対象クラス (V5a: 0=animal, 1=person / V6: 0=animal)
V5A_TARGET_CLASSES = [0, 1]
V6_TARGET_CLASSES = [0,1]

# ==========================================
# 2. 初期化処理
# ==========================================
def initialize():
    print("=" * 50)
    print("  MegaDetector V5a vs V6 Benchmark")
    print("=" * 50)
    print(f"[設定] 入力フォルダ: {INPUT_DIR}")
    print(f"[設定] V5a閾値: {V5A_CONF_THRESHOLD} | V6閾値: {V6_CONF_THRESHOLD}")
    print(f"[設定] 出力フォルダ: {OUTPUT_DIR}")
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(MISMATCH_DIR, exist_ok=True)

    if not INPUT_DIR.exists() or not any(INPUT_DIR.iterdir()):
        print(f"[エラー] 画像フォルダが見つからないか、空です: {INPUT_DIR}")
        sys.exit(1)

    print("\n[1/3] モデルを読み込んでいます (V5a & V6)...")
    
    # --- V5a の読み込み ---
    print("  -> Loading V5a (yolov5)...")
    if not V5A_MODEL_PATH.exists():
        print(f"[エラー] V5aモデルが見つかりません: {V5A_MODEL_PATH}")
        sys.exit(1)
        
    try:
        # PyTorch 2.6+ 対策
        _original_torch_load = torch.load
        def _patched_torch_load(*args, **kwargs):
            if 'weights_only' not in kwargs:
                kwargs['weights_only'] = False
            return _original_torch_load(*args, **kwargs)
        torch.load = _patched_torch_load
        
        v5a_model = yolov5.load(str(V5A_MODEL_PATH))
        v5a_model.conf = V5A_CONF_THRESHOLD
        torch.load = _original_torch_load
    except Exception as e:
        print(f"[エラー] V5aモデルの読み込みに失敗しました: {e}")
        sys.exit(1)

    # --- V6 の読み込み ---
    print("  -> Loading V6 (PytorchWildlife YOLOv10)...")
    try:
        v6_model = pw_detection.MegaDetectorV6(pretrained=True, version='MDV6-yolov10-c')
    except Exception as e:
        print(f"[エラー] V6モデルの読み込みに失敗しました: {e}")
        sys.exit(1)
        
    print("[完了] モデルの読み込み成功\n")
    return v5a_model, v6_model

# ==========================================
# 3. 横並び比較画像の生成
# ==========================================
def draw_boxes_v5a(img, df_results):
    img_draw = img.copy()
    for index, row in df_results.iterrows():
        cls_id = int(row['class'])
        conf = float(row['confidence'])
        if cls_id in V5A_TARGET_CLASSES and conf >= V5A_CONF_THRESHOLD:
            xmin, ymin, xmax, ymax = int(row['xmin']), int(row['ymin']), int(row['xmax']), int(row['ymax'])
            cv2.rectangle(img_draw, (xmin, ymin), (xmax, ymax), (0, 0, 255), 2)
            label = f"V5a:{row['name']} {conf:.2f}"
            cv2.putText(img_draw, label, (xmin, max(15, ymin - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return img_draw

def draw_boxes_v6(img, detections):
    img_draw = img.copy()
    if detections is not None:
        for i in range(len(detections)):
            cls_id = detections.class_id[i]
            conf = float(detections.confidence[i])
            if cls_id in V6_TARGET_CLASSES and conf >= V6_CONF_THRESHOLD:
                bbox = detections.xyxy[i]
                xmin, ymin, xmax, ymax = map(int, bbox)
                cv2.rectangle(img_draw, (xmin, ymin), (xmax, ymax), (0, 255, 0), 2)
                label = f"V6:Animal {conf:.2f}"
                cv2.putText(img_draw, label, (xmin, max(15, ymin - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    return img_draw

def save_mismatch_image(img_path, v5a_df, v6_detections):
    filename = Path(img_path).name
    img = cv2.imread(str(img_path))
    if img is None:
        return
    
    img_v5a = draw_boxes_v5a(img, v5a_df)
    img_v6 = draw_boxes_v6(img, v6_detections)
    
    # 水平方向に結合 (左: V5a, 右: V6)
    combined_img = cv2.hconcat([img_v5a, img_v6])
    
    # わかりやすくタイトルを付与
    h, w = combined_img.shape[:2]
    header = cv2.copyMakeBorder(combined_img, 40, 0, 0, 0, cv2.BORDER_CONSTANT, value=[0,0,0])
    cv2.putText(header, "MegaDetector V5a (YOLOv5)", (w//4 - 150, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    cv2.putText(header, "MegaDetector V6 (YOLOv10)", (3*w//4 - 150, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    
    save_path = MISMATCH_DIR / f"mismatch_{filename}"
    cv2.imwrite(str(save_path), header)

# ==========================================
# 4. メイン推論ループ
# ==========================================
def main():
    v5a_model, v6_model = initialize()
    
    image_paths = list(INPUT_DIR.glob("*.jpg")) + list(INPUT_DIR.glob("*.png"))
    total_imgs = len(image_paths)
    print(f"[2/3] 推論を開始します... (全 {total_imgs} 枚)")
    
    records = []
    
    # 混同行列用リスト (0: 検知なし, 1: 検知あり)
    y_true_v6 = []  # Ground Truth (擬似正解)
    y_pred_v5a = [] # Predictions
    
    for idx, img_path in enumerate(image_paths, 1):
        filename = img_path.name
        print(f"\r  [{idx}/{total_imgs}] 処理中: {filename} ...", end="")
        
        # --- V5a 推論 ---
        start_t = time.perf_counter()
        res_v5a = v5a_model(str(img_path))
        t_v5a = (time.perf_counter() - start_t) * 1000
        df_v5a = res_v5a.pandas().xyxy[0]
        
        v5a_detected = False
        v5a_max_conf = 0.0
        v5a_count = 0
        for _, row in df_v5a.iterrows():
            if int(row['class']) in V5A_TARGET_CLASSES and float(row['confidence']) >= V5A_CONF_THRESHOLD:
                v5a_detected = True
                v5a_count += 1
                v5a_max_conf = max(v5a_max_conf, float(row['confidence']))

        # --- V6 推論 ---
        start_t = time.perf_counter()
        res_v6 = v6_model.single_image_detection(str(img_path))
        t_v6 = (time.perf_counter() - start_t) * 1000
        det_v6 = res_v6.get('detections')
        
        v6_detected = False
        v6_max_conf = 0.0
        v6_count = 0
        if det_v6 is not None:
            for i in range(len(det_v6)):
                if det_v6.class_id[i] in V6_TARGET_CLASSES and float(det_v6.confidence[i]) >= V6_CONF_THRESHOLD:
                    v6_detected = True
                    v6_count += 1
                    v6_max_conf = max(v6_max_conf, float(det_v6.confidence[i]))
        
        # --- リスト記録 ---
        y_true_v6.append(1 if v6_detected else 0)
        y_pred_v5a.append(1 if v5a_detected else 0)
        
        mismatch_type = ""
        if v5a_detected != v6_detected:
            if v6_detected:
                mismatch_type = "False Negative (V5a missed)"
            else:
                mismatch_type = "False Positive (V5a over-detected)"
            
            # Mismatch画像の生成
            save_mismatch_image(img_path, df_v5a, det_v6)
            
        records.append({
            "Filename": filename,
            "V5a_Detected": v5a_detected,
            "V5a_Max_Conf": v5a_max_conf,
            "V5a_Count": v5a_count,
            "V5a_Time_ms": t_v5a,
            "V6_Detected": v6_detected,
            "V6_Max_Conf": v6_max_conf,
            "V6_Count": v6_count,
            "V6_Time_ms": t_v6,
            "Mismatch": mismatch_type
        })
        
    print("\n\n[3/3] 結果を集計しています...")
    
    df_records = pd.DataFrame(records)
    df_records.to_csv(OUTPUT_DIR / "benchmark_full_report.csv", index=False)
    
    df_mismatches = df_records[df_records["Mismatch"] != ""]
    df_mismatches.to_csv(OUTPUT_DIR / "mismatch_list.csv", index=False)
    
    # --- 混同行列の生成 ---
    cm = confusion_matrix(y_true_v6, y_pred_v5a, labels=[1, 0])
    
    print("\n" + "="*40)
    print("  Confusion Matrix (混同行列)")
    print("  ※ V6を「擬似正解」とした場合")
    print("="*40)
    print(f"               [V5a 予測]")
    print(f"               検知(1)   検知なし(0)")
    print(f"[V6 正解]  (1)  {cm[0][0]:<8}  {cm[0][1]:<8} (FN)")
    print(f"           (0)  {cm[1][0]:<8} (FP) {cm[1][1]:<8}")
    print("="*40)
    print(f" - True Positives (両方検知)  : {cm[0][0]}")
    print(f" - True Negatives (両方無視)  : {cm[1][1]}")
    print(f" - False Positives(V5a過検出) : {cm[1][0]} -> V5aがノイズを誤認した可能性")
    print(f" - False Negatives(V5a取こぼし): {cm[0][1]} -> V5aが動物を見落とした可能性")
    print(f" - Mismatch 合計              : {len(df_mismatches)} 枚")
    print("="*40)
    
    # ヒートマップ画像の保存
    plt.figure(figsize=(6, 5))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", xticklabels=["Detected(1)", "Not Detected(0)"], yticklabels=["Detected(1)", "Not Detected(0)"])
    plt.title("Confusion Matrix (V6 as Ground Truth)")
    plt.ylabel("V6 (Ground Truth)")
    plt.xlabel("V5a (Prediction)")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "confusion_matrix.png")
    
    print(f"\n✅ 全ての処理が完了しました！")
    print(f"  - フルレポート: {OUTPUT_DIR}/benchmark_full_report.csv")
    print(f"  - 食い違いリスト: {OUTPUT_DIR}/mismatch_list.csv")
    print(f"  - 食い違い比較画像: {MISMATCH_DIR}/")
    print(f"  - 混同行列画像: {OUTPUT_DIR}/confusion_matrix.png")

if __name__ == "__main__":
    main()
