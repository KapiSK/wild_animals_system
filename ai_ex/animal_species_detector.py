import os
import cv2
from pathlib import Path
from PIL import Image
import kagglehub
import torch
from PytorchWildlife.models import detection as pw_detection
from speciesnet.classifier import SpeciesNetClassifier

# =====================================================================
# 1. AIモデルの初期化とダウンロード
# =====================================================================
print("モデルを読み込んでいます...")

# MegaDetectorV6の初期化（軽量・高速なYOLOv10モデル）
detector = pw_detection.MegaDetectorV6(pretrained=True, version='MDV6-yolov10-c')

# SpeciesNetの初期化（KaggleHubから最新のPyTorch v4モデルを自動取得）
print("SpeciesNetの重みを確認・取得しています...")
model_path = kagglehub.model_download("google/speciesnet/pyTorch/v4.0.2a/1")
classifier = SpeciesNetClassifier(model_path)

# =====================================================================
# 2. メイン処理パイプライン
# =====================================================================
def process_and_display_images(input_dir="animals", output_dir="results"):
    # 出力フォルダの作成
    os.makedirs(output_dir, exist_ok=True)
    
    # 処理対象の画像パスを取得
    image_paths = list(Path(input_dir).glob("*.jpg")) + list(Path(input_dir).glob("*.png"))
    
    if not image_paths:
        print(f"エラー: '{input_dir}' フォルダに画像が見つかりません。")
        return

    print(f"\n合計 {len(image_paths)} 枚の画像を処理します。\n" + "-"*30)

    # SpeciesNetに渡すための一時ファイル名
    temp_crop_path = "temp_crop.jpg"

    for img_path in image_paths:
        print(f"処理中: {img_path.name}")
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        
        display_img = img.copy()

        # MegaDetectorによる動物検出
        results = detector.single_image_detection(str(img_path))
        detections = results.get('detections')
        
        if detections is not None:
            # 検出されたオブジェクトの数だけループを回す
            for i in range(len(detections)):
                bbox = detections.xyxy[i]         # [xmin, ymin, xmax, ymax]
                conf = detections.confidence[i]   # 確信度
                class_id = detections.class_id[i] # 0:動物, 1:人, 2:車
                
                # クラスIDが0（動物）かつ、確信度が0.3以上の場合のみ処理
                if class_id == 0 and conf > 0.3:
                    xmin, ymin, xmax, ymax = map(int, bbox)
                    
                    # 画像の端で見切れている場合の座標補正
                    h, w = img.shape[:2]
                    crop_ymin, crop_ymax = max(0, ymin), min(h, ymax)
                    crop_xmin, crop_xmax = max(0, xmin), min(w, xmax)
                    
                    cropped_img = img[crop_ymin:crop_ymax, crop_xmin:crop_xmax]
                    if cropped_img.size == 0:
                        continue

                    # ===================================================
                    # 3. SpeciesNetによる種特定（生のAIエンジンとの連携）
                    # ===================================================
                    # 1. クロップ画像を一時ファイルとして保存
                    cv2.imwrite(temp_crop_path, cropped_img)

                    # 2. 保存した画像を PIL (Pillow) 形式で開く
                    pil_img = Image.open(temp_crop_path)

                    try:
                        # 3. エンジンの仕様に合わせて画像を前処理
                        preprocessed_img = classifier.preprocess(pil_img)

                        # 4. ファイルパスと前処理済み画像の両方を引数として渡し推論実行
                        prediction = classifier.predict(temp_crop_path, preprocessed_img)
                        
                        # リスト型で返ってきた場合は最初の要素を取得
                        result = prediction[0] if isinstance(prediction, list) and len(prediction) > 0 else prediction

                        species_name = "Unknown"
                        final_conf = 0.0

                        # ====================================================
                        # 【日本固有種フィルター＆日本語翻訳】
                        # ====================================================
                        # 長野周辺で想定される動物の英語名 -> 日本語名の辞書
                        JAPANESE_SPECIES = {
                            "asiatic black bear": "ツキノワグマ",
                            "japanese macaque": "ニホンザル",
                            "macaque": "ニホンザル",
                            "sika deer": "ニホンジカ",
                            "wild boar": "イノシシ",
                            "japanese serow": "ニホンカモシカ",
                            "serow": "ニホンカモシカ",
                            "red fox": "ホンドギツネ",
                            "raccoon dog": "タヌキ",
                            "japanese badger": "ニホンアナグマ",
                            "japanese hare": "ニホンノウサギ",
                            "japanese marten": "ホンドテン",
                            "masked palm civet": "ハクビシン",
                            "raccoon": "アライグマ",
                            "brown bear": "ヒグマ",
                            "bear family": "クマ（科）",
                            "deer family": "シカ（科）"
                        }

                        if isinstance(result, dict) and 'classifications' in result:
                            classifications = result['classifications']
                            
                            if 'classes' in classifications and 'scores' in classifications:
                                classes = classifications['classes']
                                scores = classifications['scores']
                                
                                # AIが弾き出した候補を確率が高い順に上からチェック
                                for cls_str, score in zip(classes, scores):
                                    # 英語の一般名を抽出（小文字に揃える）
                                    eng_name = cls_str.split(';')[-1].strip().lower()
                                    
                                    # 辞書に登録されている「日本の動物」が見つかったら即採用
                                    if eng_name in JAPANESE_SPECIES:
                                        species_name = JAPANESE_SPECIES[eng_name]
                                        final_conf = float(score)
                                        break
                                
                                # もし上位候補の中に日本の動物が1匹もいなかった場合の最終手段
                                if species_name == "Unknown":
                                    # 仕方がないので一番確率の高かった海外の動物名をそのまま出す
                                    species_name = classes[0].split(';')[-1].strip()
                                    final_conf = float(scores[0])

                    except Exception as e:
                        species_name = "Error"
                        final_conf = 0.0
                        print(f"    推論データ抽出エラー: {e}")
                    finally:
                        # 画像ファイルを確実に閉じてロックを解除
                        pil_img.close()

                    # ===================================================
                    # 4. 画像への描画処理
                    # ===================================================
                    # バウンディングボックス（緑色）
                    cv2.rectangle(display_img, (xmin, ymin), (xmax, ymax), (0, 255, 0), 2)
                    
                    # ラベルのテキストと背景帯を描画
                    label_text = f"{species_name} ({final_conf:.2f})"
                    (text_w, text_h), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                    cv2.rectangle(display_img, (xmin, ymin - 20), (xmin + text_w, ymin), (0, 255, 0), -1)
                    cv2.putText(display_img, label_text, (xmin, ymin - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
                    
                    print(f"  -> 検出: {species_name} (MD確信度: {conf:.2f}, SP確信度: {final_conf:.2f})")

        # 結果を results フォルダに保存
        output_path = os.path.join(output_dir, f"result_{img_path.name}")
        cv2.imwrite(output_path, display_img)

    # 全ての処理が終わったら一時ファイルを削除しておく
    if os.path.exists(temp_crop_path):
        os.remove(temp_crop_path)
        
    print("-" * 30 + f"\nすべての処理が完了しました。結果は '{output_dir}' フォルダに保存されています。")

# スクリプトの実行
if __name__ == "__main__":
    process_and_display_images()