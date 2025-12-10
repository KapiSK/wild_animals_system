from ultralytics import YOLO

class Detector:
    def __init__(self):
        # Load a model
        # The model will be downloaded automatically on first use
        self.model = YOLO("yolov8n.pt") 

    def detect(self, image_path):
        results = self.model(image_path)
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
                    return True, label
        return False, None
