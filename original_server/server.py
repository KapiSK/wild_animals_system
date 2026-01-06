import os
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from dotenv import load_dotenv
import yolov5
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
MODEL_URL = "https://github.com/agentmorris/MegaDetector/releases/download/v5.0/md_v5a.0.0.pt"
MODEL_PATH = "md_v5a.0.0.pt"

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)

# Logging setup
# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("server.log"),
        logging.StreamHandler()
    ]
)
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
# MegaDetector v5a is a YOLOv5 model. We use the yolov5 library to load it.
download_model_if_needed()
try:
    # PyTorch 2.6+ defaults weights_only=True which ensures security but fails with older models (like MegaDetector).
    # Since we trust this model from the official source, we monkey-patch torch.load to allow partial loading.
    import torch
    _original_torch_load = torch.load
    def _patched_torch_load(*args, **kwargs):
        if 'weights_only' not in kwargs:
            kwargs['weights_only'] = False
        return _original_torch_load(*args, **kwargs)
    torch.load = _patched_torch_load

    # load() automatically handles YOLOv5 models
    model = yolov5.load(MODEL_PATH)
    logger.info(f"Model loaded. Classes: {model.names}")
    
    # Restore original load just in case
    torch.load = _original_torch_load
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

from collections import defaultdict
import re

# ... (Previous imports omitted for brevity in replacement, but kept in file) ...

# Cycle Manager for Aggregation using same logic as Pi (roughly)
class CycleManager:
    def __init__(self):
        # { cycle_id: { 'files': [], 'last_update': datetime } }
        self.cycles = defaultdict(lambda: {'files': [], 'last_update': datetime.now()})
        self.lock = asyncio.Lock()

    async def add_result(self, cycle_id, result_data):
        """
        result_data: {
          'filename': str,
          'animal_count': int,
          'max_conf': float,
          'annotated_path': str,
          'summary_text': str
        }
        """
        async with self.lock:
            self.cycles[cycle_id]['files'].append(result_data)
            self.cycles[cycle_id]['last_update'] = datetime.now()
            
            # Check if cycle is complete (assuming 3 images per cycle)
            if len(self.cycles[cycle_id]['files']) >= 3:
                await self.process_cycle(cycle_id)
                del self.cycles[cycle_id]

    async def process_cycle(self, cycle_id):
        files = self.cycles[cycle_id]['files']
        logger.info(f"Cycle {cycle_id} complete. Processing aggregated email.")
        
        # 1. Identify best image (High animal count > High confidence)
        best_data = sorted(files, key=lambda x: (x['animal_count'], x['max_conf']), reverse=True)[0]
        
        # 2. Compose Email Body
        # "1サイクルの画像3枚組のうち、何枚で検出か"
        detected_images_count = sum(1 for f in files if f['animal_count'] > 0)
        
        body_lines = [
            f"Cycle ID: {cycle_id}",
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Detections: Found animals in {detected_images_count} out of {len(files)} images.",
            "",
            "Details per image:"
        ]
        
        for f in files:
            # Sort by original upload order if possible? 
            # Filename usually has timestamp or index. Let's just list them.
            body_lines.append(f"- {f['filename']}: {f['summary_text']}")
            
        body = "\n".join(body_lines)
        subject = f"Wild Animal Cycle Detected: {best_data['summary_text']}"
        
        # 3. Send Email (One email per cycle)
        # Using the annotated path of the best image
        send_email(subject, body, best_data['annotated_path'])
        logger.info(f"Aggregated email sent for Cycle {cycle_id}")

    async def check_timeouts(self, timeout_seconds=300):
        """
        Periodically check for incomplete cycles that have timed out.
        """
        while True:
            await asyncio.sleep(60) # Run check every minute
            logger.info("Running cycle timeout check...")
            now = datetime.now()
            
            # Need to iterate over a copy of keys because we might modify the dict
            cycle_ids = list(self.cycles.keys())
            
            for cycle_id in cycle_ids:
                data = self.cycles[cycle_id]
                last_update = data['last_update']
                time_diff = (now - last_update).total_seconds()
                
                if time_diff > timeout_seconds:
                    logger.warning(f"Cycle {cycle_id} timed out (last update {time_diff}s ago). Force processing.")
                    async with self.lock:
                        # Double check existence in lock
                        if cycle_id in self.cycles:
                             await self.process_cycle(cycle_id)
                             del self.cycles[cycle_id]

cycle_manager = CycleManager()

@app.on_event("startup")
async def startup_event():
    # Start the timeout checker background task
    asyncio.create_task(cycle_manager.check_timeouts())

def extract_cycle_id(filename: str) -> str:
    """
    Extract Cycle ID from filename.
    Format expected: ServerTimestamp_PiTimestamp_CycleID-IndexSuffix.jpg
    or just CycleID-IndexSuffix.jpg
    
    The logic parses the {CycleID}-{Index}{Suffix}.jpg pattern first,
    then strips any underscore-separated prefixes (timestamps) to get the bare CycleID.
    """
    try:
        # 1. Regex to find the suffix patterns like "-1d.jpg" or "-2.jpg"
        # We capture everything before that suffix as the "stem".
        # Regex: greedy match (.*) until a hyphen and digit(s) and extension at end
        match = re.search(r"^(.*)-(\d+)[nd]?\.jpg$", filename, re.IGNORECASE)
        
        if match:
            full_stem = match.group(1) # e.g. "2026..._2026..._WIN-SIM-CAM01-0001"
            
            # 2. Strip timestamps.
            # Timestamps are usually separated by underscores. 
            # Cycle ID itself might contain underscores? 
            # Project convention: CycleID is MacAddr-Seq (hyphens) or similar.
            # Timestamps are YYYYMMDD_HHMMSS_ffffff
            # Only the LAST part is the CycleID if we assume standard naming.
            
            if '_' in full_stem:
                return full_stem.split('_')[-1]
            return full_stem
            
        # Fallback if regex fails (unexpected naming)
        return filename.rsplit('-', 1)[0]
    except Exception as e:
        logger.error(f"Failed to extract cycle ID: {e}")
        return "unknown"

async def process_and_notify(image_path: str, filename: str):
    """
    Perform inference and Add to Cycle Buffer.
    """
    logger.info(f"Processing {filename}...")
    
    # Run inference
    model.conf = 0.25 
    results = model(image_path)
    
    detected_animals = {}
    animal_found = False
    max_conf = 0.0
    
    df = results.pandas().xyxy[0]
    
    for index, row in df.iterrows():
        cls = int(row['class'])
        if cls in ANIMAL_CLASSES:
            animal_found = True
            label = row['name']
            conf = float(row['confidence'])
            detected_animals[label] = detected_animals.get(label, 0) + 1
            if conf > max_conf:
                max_conf = conf
    
    # Generate summary string
    if detected_animals:
        counts_str = ", ".join([f"{label}: {count}" for label, count in detected_animals.items()])
    else:
        counts_str = "No animals"
        
    annotated_path = image_path # Default to original if no annotation needed
    
    # Save annotated image if animal found
    if animal_found:
        processed_filename = f"processed_{filename}"
        annotated_path = os.path.join(PROCESSED_DIR, processed_filename)
        
        try:
            img = cv2.imread(image_path)
            for index, row in df.iterrows():
                x1, y1, x2, y2 = int(row['xmin']), int(row['ymin']), int(row['xmax']), int(row['ymax'])
                label_text = f"{row['name']} {row['confidence']:.2f}"
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                t_size = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
                c2 = x1 + t_size[0], y1 - t_size[1] - 3
                cv2.rectangle(img, (x1, y1), c2, (0, 255, 0), -1, cv2.LINE_AA)
                cv2.putText(img, label_text, (x1, y1 - 2), 0, 0.5, [255, 255, 255], thickness=1, lineType=cv2.LINE_AA)

            cv2.imwrite(annotated_path, img)
            logger.info(f"Animal detected! Saved annotated image to {annotated_path}")
        except Exception as e:
            logger.error(f"Failed to annotate: {e}")
            annotated_path = image_path # Fallback
    else:
        logger.info(f"No animals detected in {filename}")

    # Add to Cycle Buffer
    cycle_id = extract_cycle_id(filename)
    logger.info(f"Extracted Cycle ID: {cycle_id} for {filename}")
    
    # Calculate total animal count
    total_animals = sum(detected_animals.values())
    
    result_data = {
        'filename': filename,
        'animal_count': total_animals,
        'max_conf': max_conf,
        'annotated_path': annotated_path,
        'summary_text': counts_str
    }
    
    await cycle_manager.add_result(cycle_id, result_data)

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
