from ultralytics import YOLO
import cv2

class Detector:
    def __init__(self):
        # 蒸留済みのモデルをRaspberry Piで非同期(マルチスレッド)かつ高速・安定に動かすため、
        # TFLite(.tflite) または ONNX(.onnx) 形式のモデルを使用します。
        self.model = YOLO("best.onnx") # .onnx の場合は "best.onnx" に変更してください

    def detect(self, image_path, save_path=None):
        # 推論の実行 (conf=0.50 は「AIの自信度が50%以上のときだけ検出する」という閾値設定です)
        # 誤検知が多い場合は0.60等に上げ、検知漏れが多い場合は0.25等に下げてください。
        results = self.model(image_path, conf=0.004)
        is_animal_detected = False
        label_detected = None

        for result in results:
            boxes = result.boxes
            for box in boxes:
                cls = int(box.cls[0])
                label = self.model.names[cls]
                # 独自の推論モデル（animal か empty の判定）に対応
                # COCOのID指定ではなく、ラベル名（文字）で直接判定するように変更します
                label_lower = label.lower()
                conf = float(box.conf[0])
                label_with_conf = f"{label} (conf: {conf:.2f})"
                
                # "empty"（空）以外の何かが検出されたら転送対象とする
                if "empty" not in label_lower and "none" not in label_lower:
                    is_animal_detected = True
                    label_detected = label_with_conf
                    break # Return first detected animal
                else:
                    # もし転送対象じゃなかった場合(empty等)もログに残すために保存しておく
                    if not is_animal_detected:
                        label_detected = label_with_conf
            
            # Save result image if requested
            if save_path:
                # plot() returns a numpy array (BGR)
                annotated_frame = result.plot()
                cv2.imwrite(save_path, annotated_frame)

            if is_animal_detected:
                break

        return is_animal_detected, label_detected

