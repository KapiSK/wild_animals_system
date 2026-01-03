import os
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from dotenv import load_dotenv
from ultralytics import YOLO
import cv2
import asyncio

# Load environment variables
load_dotenv()

# Configuration
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "received_images")
PROCESSED_DIR = os.getenv("PROCESSED_DIR", "processed_images")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "your_email@example.com")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "your_password")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "recipient@example.com")

# MegaDetector v5a Configuration
MODEL_URL = "https://github.com/ecology-tech/MegaDetector/releases/download/v5.0/md_v5a.0.0.pt"
MODEL_PATH = "md_v5a.0.0.pt"

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

def download_model_if_needed():
    """Download MegaDetector model if not present."""
    if not os.path.exists(MODEL_PATH):
        logger.info(f"Model not found. Downloading from {MODEL_URL}...")
        import requests
        try:
            response = requests.get(MODEL_URL, stream=True)
            response.raise_for_status()
            with open(MODEL_PATH, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info("Model downloaded successfully.")
        except Exception as e:
            logger.error(f"Failed to download model: {e}")
            raise

# Load Model (MegaDetector)
# Note: Ultralytics YOLOv8 can load valid YOLOv5 models.
download_model_if_needed()
try:
    model = YOLO(MODEL_PATH) 
    logger.info(f"Model loaded. Classes: {model.names}")
except Exception as e:
    logger.error(f"Failed to load model: {e}")
    raise

# MegaDetector v5 classes:
# 0: animal (detection)
# 1: person
# 2: vehicle
# dynamic check for 'animal' class
ANIMAL_CLASSES = []
for k, v in model.names.items():
    if 'animal' in v.lower():
        ANIMAL_CLASSES.append(k)
        
if not ANIMAL_CLASSES:
    logger.warning("'animal' class not found in model names. Defaulting to class 0.")
    ANIMAL_CLASSES = [0]
    
logger.info(f"Animal classes set to: {ANIMAL_CLASSES}")

def send_email(subject: str, body: str, attachment_path: str = None):
    """
    Send an email notification with an optional image attachment.
    """
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECIPIENT_EMAIL
    msg.set_content(body)

    if attachment_path:
        try:
            with open(attachment_path, 'rb') as f:
                file_data = f.read()
                file_name = os.path.basename(attachment_path)
            
            msg.add_attachment(file_data, maintype='image', subtype='jpeg', filename=file_name)
        except Exception as e:
            logger.error(f"Failed to attach image: {e}")

    try:
        if SENDER_EMAIL == "your_email@example.com":
            logger.warning("Email configuration not set. Skipping email send.")
            return

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
            smtp.send_message(msg)
        logger.info(f"Email sent to {RECIPIENT_EMAIL}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

def process_and_notify(image_path: str, filename: str):
    """
    Perform inference on the image and send notification if animals are detected.
    """
    logger.info(f"Processing {filename}...")
    
    # Run inference with confidence threshold
    results = model(image_path, conf=0.25)
    
    detected_animals = {}
    animal_found = False
    
    for result in results:
        boxes = result.boxes
        for box in boxes:
            cls = int(box.cls[0])
            if cls in ANIMAL_CLASSES:
                animal_found = True
                label = model.names[cls]
                detected_animals[label] = detected_animals.get(label, 0) + 1
        
        # Save annotated image if animal found
        if animal_found:
            processed_filename = f"processed_{filename}"
            processed_path = os.path.join(PROCESSED_DIR, processed_filename)
            
            # plot() returns the image as a numpy array. 
            # We filter by passing only the classes we want to visualize? 
            # Ultralytics plot() doesn't always support class filtering directly in all versions, 
            # but we can try to rely on the fact that result contains all boxes.
            # To be safe and clean, we just plot all detections (including people/vehicles) as that can be useful context.
            annotated_frame = result.plot()
            
            cv2.imwrite(processed_path, annotated_frame)
            logger.info(f"Animal detected! Saved annotated image to {processed_path}")
            
            # Prepare email body
            counts_str = ", ".join([f"{label}: {count}" for label, count in detected_animals.items()])
            subject = f"Wild Animal Detected: {counts_str}"
            body = f"Detected animals:\n{counts_str}\n\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            # Send email
            send_email(subject, body, processed_path)
        else:
            logger.info(f"No animals detected in {filename}")

@app.post("/upload")
async def upload_image(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    Receive image, save it, and trigger processing.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    logger.info(f"Receiving image: {filename}")
    
    try:
        with open(file_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                buffer.write(content)
        
        # Trigger background processing
        background_tasks.add_task(process_and_notify, file_path, filename)
        
        return {"status": "ok", "message": "Image received and processing started"}
    except Exception as e:
        logger.error(f"Failed to save image: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
