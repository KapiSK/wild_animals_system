import os
import sys
from pathlib import Path
import torch
import yolov5

# ==========================================
# 設定
# ==========================================
# プロジェクトルートにある md_v5a.0.0.pt を参照
MODEL_PATH = Path(__file__).parent.parent / "md_v5a.0.0.pt"
INPUT_DIR = Path(__file__).parent / "animals"
CONF_THRESHOLD = 0.1 # クラウドサーバーと同じ閾値

def main():
    print(f"[{'設定確認':^10}]")
    print(f"- モデルパス: {MODEL_PATH}")
    print(f"- 画像フォルダ: {INPUT_DIR}")
    print(f"- 信頼度閾値: {CONF_THRESHOLD}")
    print("-" * 30)

    if not MODEL_PATH.exists():
        print(f"[エラー] モデルファイルが見つかりません: {MODEL_PATH}")
        sys.exit(1)

    if not INPUT_DIR.exists() or not any(INPUT_DIR.iterdir()):
        print(f"[エラー] 画像フォルダが見つからないか、空です: {INPUT_DIR}")
        sys.exit(1)

    # ==========================================
    # モデルの読み込み (server.py と同じ処理)
    # ==========================================
    print("\n[INFO] MegaDetector v5a を読み込んでいます...")
    try:
        # PyTorch 2.6+ 対策
        _original_torch_load = torch.load
        def _patched_torch_load(*args, **kwargs):
            if 'weights_only' not in kwargs:
                kwargs['weights_only'] = False
            return _original_torch_load(*args, **kwargs)
        torch.load = _patched_torch_load

        # モデルのロード
        model = yolov5.load(str(MODEL_PATH))
        model.conf = CONF_THRESHOLD
        
        # 復元
        torch.load = _original_torch_load
        
        print("[INFO] モデルの読み込み完了\n")
    except Exception as e:
        print(f"[エラー] モデルの読み込みに失敗しました: {e}")
        sys.exit(1)

    # クラス定義 (MegaDetector v5)
    # 0: animal, 1: person, 2: vehicle
    classes_map = model.names
    
    # ==========================================
    # 推論実行
    # ==========================================
    image_paths = list(INPUT_DIR.glob("*.jpg")) + list(INPUT_DIR.glob("*.png"))
    
    for img_path in image_paths:
        print(f"▶ ファイル: {img_path.name}")
        
        # 推論
        results = model(str(img_path))
        df = results.pandas().xyxy[0]
        
        detected = False
        for index, row in df.iterrows():
            cls_id = int(row['class'])
            conf = float(row['confidence'])
            name = row['name']
            
            # animal(0) か person(1) かつ 閾値以上をクラウドでは対象としている
            if cls_id in [0, 1] and conf >= CONF_THRESHOLD:
                detected = True
                print(f"  - [検知] クラス: {name:<10} | 信頼度: {conf:.4f} ({conf*100:.1f}%)")
            elif cls_id in [0, 1]:
                # 閾値未満で弾かれたもの
                print(f"  - [除外] クラス: {name:<10} | 信頼度: {conf:.4f} ({conf*100:.1f}%) -> 閾値({CONF_THRESHOLD})未満のため")
                
        if not detected:
            print("  - 検知なし (No targets >= 0.25)")
        print()

if __name__ == "__main__":
    main()
