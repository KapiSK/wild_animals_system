from ultralytics import YOLO
import cv2

class Detector:
    def __init__(self):
        # Load a model
        # The model will be downloaded automatically on first use
        self.model = YOLO("yolov8n.pt") 

    def detect(self, image_path, save_path=None):
        results = self.model(image_path)
        is_animal_detected = False
        label_detected = None

        for result in results:
            boxes = result.boxes
            for box in boxes:
                cls = int(box.cls[0])
                label = self.model.names[cls]
                # Filter for animals
                # COCO classes: 14: bird, 15: cat, 16: dog, 17: horse, 18: sheep, 
                # 19: cow, 20: elephant, 21: bear, 22: zebra, 23: giraffe
                animal_classes = [14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
                if cls in animal_classes: 
                    is_animal_detected = True
                    label_detected = label
                    break # Return first detected animal
            
            # Save result image if requested
            if save_path:
                # plot() returns a numpy array (BGR)
                annotated_frame = result.plot()
                cv2.imwrite(save_path, annotated_frame)

            if is_animal_detected:
                break

        return is_animal_detected, label_detected

