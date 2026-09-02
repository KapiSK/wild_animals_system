from ultralytics import YOLO
import cv2

class Detector:
    def __init__(self):
        # Load a model
        # The model will be downloaded automatically on first use
        self.model = YOLO("yolov8n.pt") 

    def detect(self, image_path, save_path=None):
        # Run inference specifying classes=[0] to ONLY detect persons
        results = self.model(image_path, classes=[0])
        is_person_detected = False
        max_confidence = 0.0

        for result in results:
            boxes = result.boxes
            for box in boxes:
                # Since classes=[0], all detected boxes are persons
                conf = float(box.conf[0])
                if conf > max_confidence:
                    max_confidence = conf
                    is_person_detected = True
            
            # Save result image if requested. 
            # Because we used classes=[0], result.plot() will ONLY draw boxes for persons!
            if save_path:
                annotated_frame = result.plot()
                cv2.imwrite(save_path, annotated_frame)

        return is_person_detected, max_confidence

