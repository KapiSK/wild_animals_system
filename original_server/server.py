import os
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import yolov5
import cv2
import asyncio
import time
from collections import defaultdict
import re

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

# Mount the static directories to serve images
app.mount("/images/raw", StaticFiles(directory=UPLOAD_DIR), name="raw_images")
app.mount("/images/processed", StaticFiles(directory=PROCESSED_DIR), name="processed_images")

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
download_model_if_needed()
try:
    # PyTorch 2.6+ prevention
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
    
    # Restore original load
    torch.load = _original_torch_load
except Exception as e:
    logger.error(f"Failed to load model: {e}")
    raise

# MegaDetector v5 classes: 0: animal, 1: person, 2: vehicle
TARGET_CLASSES = []
for k, v in model.names.items():
    if 'animal' in v.lower() or 'person' in v.lower():
        TARGET_CLASSES.append(k)
        
if not TARGET_CLASSES:
    logger.warning("'animal' or 'person' class not found in model names. Defaulting to class 0.")
    TARGET_CLASSES = [0]
    
logger.info(f"Target classes set to: {TARGET_CLASSES}")

def send_email(subject: str, body: str, attachment_path: str = None):
    """
    Send an email notification with an optional image attachment.
    """
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    recipients = [email.strip() for email in RECIPIENT_EMAIL.split(',')]
    msg['To'] = ", ".join(recipients)
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
        logger.info(f"Email sent to {recipients}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

# Cycle Manager for Aggregation
class CycleManager:
    def __init__(self):
        # { cycle_id: { 'files': [], 'last_update': datetime.now(), 'start_time': None, 'timings': [] } }
        self.cycles = defaultdict(lambda: {
            'files': [], 
            'last_update': datetime.now(),
            'start_time': None,
            'timings': []
        })
        self.lock = asyncio.Lock()

    async def add_result(self, cycle_id, result_data, timing_info):
        """
        result_data include 'target_count'
        """
        async with self.lock:
            cycle = self.cycles[cycle_id]
            
            # Set cycle start time if it's the first image
            if cycle['start_time'] is None:
                cycle['start_time'] = timing_info['receive_start']
            elif timing_info['receive_start'] < cycle['start_time']:
                cycle['start_time'] = timing_info['receive_start']

            cycle['files'].append(result_data)
            cycle['timings'].append(timing_info)
            cycle['last_update'] = datetime.now()
            
            # Check if cycle is complete (assuming 3 images per cycle)
            if len(self.cycles[cycle_id]['files']) >= 3:
                await self.process_cycle(cycle_id)
                del self.cycles[cycle_id]

    async def process_cycle(self, cycle_id):
        cycle_data = self.cycles[cycle_id]
        files = cycle_data['files']
        logger.info(f"Cycle {cycle_id} complete. Processing aggregated email.")
        
        cycle_end_time = time.perf_counter()
        if cycle_data['start_time']:
            total_cycle_time = (cycle_end_time - cycle_data['start_time']) * 1000
        else:
            total_cycle_time = 0
            
        # Calculate specific totals
        timings = cycle_data['timings']
        total_save = sum(t.get('save_duration', 0) for t in timings) * 1000
        total_inference = sum(t.get('inference_duration', 0) for t in timings) * 1000

        # 1. Identify best image (High target count > High confidence)
        best_data = sorted(files, key=lambda x: (x['target_count'], x['max_conf']), reverse=True)[0]
        
        # 2. Compose Email Body
        detected_images_count = sum(1 for f in files if f['target_count'] > 0)
        
        body_lines = [
            f"Cycle ID: {cycle_id}",
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Detections: Found targets in {detected_images_count} out of {len(files)} images.",
            "",
            "Details per image:"
        ]
        
        for f in files:
            body_lines.append(f"- {f['filename']}: {f['summary_text']}")
            
        body = "\n".join(body_lines)
        subject = f"Target Cycle Detected: {best_data['summary_text']}"
        
        # 3. Send Email
        email_start = time.perf_counter()
        send_email(subject, body, best_data['annotated_path'])
        email_duration = (time.perf_counter() - email_start) * 1000
        logger.info(f"Aggregated email sent for Cycle {cycle_id}")

        # Log Performance Metrics
        logger.info(f"[PERF] Cycle {cycle_id} Finished. Total Time: {total_cycle_time:.2f}ms")
        logger.info(f"[PERF] Breakdown: Save={total_save:.2f}ms, Inference={total_inference:.2f}ms, Email={email_duration:.2f}ms")

        # --- CSV Logging ---
        try:
            csv_file = "cloud_metrics.csv"
            file_exists = os.path.isfile(csv_file)
            with open(csv_file, "a") as f:
                if not file_exists:
                    f.write("timestamp,cycle_id,total_time_ms,inference_time_ms,email_time_ms,detected_count,best_conf\n")
                
                f.write(f"{datetime.now().isoformat()},{cycle_id},{total_cycle_time:.2f},{total_inference:.2f},{email_duration:.2f},{detected_images_count},{best_data['max_conf']:.4f}\n")
        except Exception as e:
            logger.error(f"Failed to write metrics: {e}")

    async def check_timeouts(self, timeout_seconds=300):
        while True:
            await asyncio.sleep(60)
            logger.info("Running cycle timeout check...")
            now = datetime.now()
            cycle_ids = list(self.cycles.keys())
            
            for cycle_id in cycle_ids:
                data = self.cycles[cycle_id]
                last_update = data['last_update']
                time_diff = (now - last_update).total_seconds()
                
                if time_diff > timeout_seconds:
                    logger.warning(f"Cycle {cycle_id} timed out (last update {time_diff}s ago). Force processing.")
                    async with self.lock:
                        if cycle_id in self.cycles:
                             await self.process_cycle(cycle_id)
                             del self.cycles[cycle_id]

cycle_manager = CycleManager()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cycle_manager.check_timeouts())

def extract_cycle_id(filename: str) -> str:
    """
    Extract Cycle ID from filename.
    """
    try:
        match = re.search(r"^(.*)-(\d+)[nd]?\.jpg$", filename, re.IGNORECASE)
        if match:
            full_stem = match.group(1) 
            if '_' in full_stem:
                return full_stem.split('_')[-1]
            return full_stem
        return filename.rsplit('-', 1)[0]
    except Exception as e:
        logger.error(f"Failed to extract cycle ID: {e}")
        return "unknown"

async def process_and_notify(image_path: str, filename: str, receive_start: float, save_duration: float):
    """
    Perform inference and Add to Cycle Buffer.
    """
    logger.info(f"Processing {filename}...")
    
    inference_start = time.perf_counter()
    # Run inference
    model.conf = 0.25 
    results = model(image_path)
    inference_duration = time.perf_counter() - inference_start
    
    detected_targets = {}
    target_found = False
    max_conf = 0.0
    
    df = results.pandas().xyxy[0]
    
    for index, row in df.iterrows():
        cls = int(row['class'])
        if cls in TARGET_CLASSES:
            target_found = True
            label = row['name']
            conf = float(row['confidence'])
            detected_targets[label] = detected_targets.get(label, 0) + 1
            if conf > max_conf:
                max_conf = conf
    
    # Generate summary string
    if detected_targets:
        counts_str = ", ".join([f"{label}: {count}" for label, count in detected_targets.items()])
    else:
        counts_str = "No targets"
        
    annotated_path = image_path # Default to original if no annotation needed
    
    # Save annotated image if target found
    if target_found:
        processed_filename = f"processed_{filename}"
        annotated_path = os.path.join(PROCESSED_DIR, processed_filename)
        
        try:
            img = cv2.imread(image_path)
            for index, row in df.iterrows():
                cls = int(row['class'])
                # Only draw BB for targets
                if cls in TARGET_CLASSES:
                    x1, y1, x2, y2 = int(row['xmin']), int(row['ymin']), int(row['xmax']), int(row['ymax'])
                    label_text = f"{row['name']} {row['confidence']:.2f}"
                    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    t_size = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
                    c2 = x1 + t_size[0], y1 - t_size[1] - 3
                    cv2.rectangle(img, (x1, y1), c2, (0, 255, 0), -1, cv2.LINE_AA)
                    cv2.putText(img, label_text, (x1, y1 - 2), 0, 0.5, [255, 255, 255], thickness=1, lineType=cv2.LINE_AA)

            cv2.imwrite(annotated_path, img)
            logger.info(f"Target detected! Saved annotated image to {annotated_path}")
        except Exception as e:
            logger.error(f"Failed to annotate: {e}")
            annotated_path = image_path # Fallback
    else:
        logger.info(f"No targets detected in {filename}")

    # Add to Cycle Buffer
    cycle_id = extract_cycle_id(filename)
    logger.info(f"Extracted Cycle ID: {cycle_id} for {filename}")
    
    # Calculate total target count
    total_targets = sum(detected_targets.values())
    
    result_data = {
        'filename': filename,
        'target_count': total_targets,
        'max_conf': max_conf,
        'annotated_path': annotated_path,
        'summary_text': counts_str
    }
    
    timing_info = {
        'receive_start': receive_start,
        'save_duration': save_duration,
        'inference_duration': inference_duration
    }
    
    await cycle_manager.add_result(cycle_id, result_data, timing_info)

@app.post("/upload")
async def upload_image(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    Receive image, save it, and trigger processing.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    logger.info(f"Receiving image: {filename}")
    
    receive_start = time.perf_counter()
    try:
        with open(file_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                buffer.write(content)
        
        save_end = time.perf_counter()
        save_duration = save_end - receive_start

        # Trigger background processing
        background_tasks.add_task(process_and_notify, file_path, filename, receive_start, save_duration)
        
        return {"status": "ok", "message": "Image received and processing started"}
    except Exception as e:
        logger.error(f"Failed to save image: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/images")
async def get_images():
    """
    Return a list of raw and processed images.
    """
    try:
        raw_files = [f for f in os.listdir(UPLOAD_DIR) if os.path.isfile(os.path.join(UPLOAD_DIR, f)) and f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
        raw_files.sort(key=lambda x: os.path.getmtime(os.path.join(UPLOAD_DIR, x)), reverse=True)
        
        proc_files = [f for f in os.listdir(PROCESSED_DIR) if os.path.isfile(os.path.join(PROCESSED_DIR, f)) and f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
        proc_files.sort(key=lambda x: os.path.getmtime(os.path.join(PROCESSED_DIR, x)), reverse=True)
        
        return {"status": "ok", "raw": raw_files, "processed": proc_files}
    except Exception as e:
        logger.error(f"Failed to get image list: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/gallery", response_class=HTMLResponse)
async def gallery():
    """
    Serve a simple HTML page to view raw and processed images.
    """
    html_content = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Cloud Server Gallery</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
            body { font-family: 'Inter', 'Segoe UI', Tahoma, sans-serif; margin: 0; padding: 20px; background-color: #f2f7f4; color: #2d3748; }
            h1 { text-align: center; color: #1c4532; margin-bottom: 10px; font-weight: 600; letter-spacing: -0.5px; font-size: 2.2rem; }
            h2 { color: #276749; font-weight: 500; font-size: 1.2rem; margin-bottom: 20px; text-align: center; }
            .header-accent { display: block; width: 60px; height: 4px; background: #38a169; margin: 0 auto 30px auto; border-radius: 2px; }
            .tabs { display: flex; justify-content: center; margin-bottom: 40px; gap: 12px; }
            .tab { padding: 12px 24px; background: #e2e8f0; color: #4a5568; border: none; cursor: pointer; font-size: 15px; font-weight: 500; border-radius: 30px; transition: all 0.2s ease; }
            .tab:hover { background: #cbd5e0; }
            .tab.active { background: #2f855a; color: white; box-shadow: 0 4px 6px rgba(47, 133, 90, 0.2); }
            .gallery-container { display: none; margin: 0 auto; max-width: 1200px; padding-bottom: 60px; }
            .gallery-container.active { display: block; }
            .latest-container { margin: 0 auto 50px auto; max-width: 900px; text-align: center; }
            .latest-item { background: #ffffff; border-radius: 16px; box-shadow: 0 20px 40px rgba(39, 103, 73, 0.08); overflow: hidden; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 0; border: 1px solid #e2e8f0; transition: transform 0.3s ease, box-shadow 0.3s ease; }
            .latest-item:hover { transform: translateY(-5px); box-shadow: 0 25px 50px rgba(39, 103, 73, 0.12); }
            .latest-item img { width: 100%; max-height: 550px; object-fit: contain; cursor: pointer; background: #f8fafc; border-bottom: 1px solid #edf2f7; }
            .latest-item span { padding: 18px; font-size: 15px; color: #4a5568; font-weight: 500; word-break: break-all; width: 100%; box-sizing: border-box; }
            .gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 24px; padding: 0 20px; }
            .item { background: #ffffff; border-radius: 14px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -2px rgba(0, 0, 0, 0.025); overflow: hidden; display: flex; flex-direction: column; align-items: center; transition: all 0.3s ease; border: 1px solid #edf2f7; }
            .item:hover { transform: translateY(-8px); box-shadow: 0 20px 25px -5px rgba(39, 103, 73, 0.1), 0 10px 10px -5px rgba(39, 103, 73, 0.04); border-color: #c6f6d5; }
            .item .img-wrapper { width: 100%; height: 220px; overflow: hidden; background: #edf2f7; cursor: pointer; }
            .item img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.4s ease; }
            .item img:hover { transform: scale(1.05); }
            .item span { padding: 16px 12px; font-size: 13px; color: #718096; font-weight: 500; word-break: break-all; width: 100%; box-sizing: border-box; text-align: center; }
            .empty-msg { text-align: center; color: #718096; font-size: 16px; margin-top: 50px; font-weight: 500; }
        </style>
    </head>
    <body>
        <h1>Cloud Server Gallery</h1>
        <div class="header-accent"></div>
        <div class="tabs">
            <button class="tab active" onclick="showTab('processed')">処理済み画像 (Processed)</button>
            <button class="tab" onclick="showTab('raw')">元画像 (Raw)</button>
        </div>
        
        <div class="gallery-container active" id="gallery-processed"></div>
        <div class="gallery-container" id="gallery-raw"></div>
        
        <script>
            let currentProcessed = null;
            let currentRaw = null;

            function arraysEqual(a, b) {
                if (a === b) return true;
                if (a == null || b == null) return false;
                if (a.length !== b.length) return false;
                for (let i = 0; i < a.length; ++i) {
                    if (a[i] !== b[i]) return false;
                }
                return true;
            }

            function showTab(type) {
                document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
                document.querySelectorAll('.gallery-container').forEach(el => el.classList.remove('active'));
                if (event && event.target) {
                    event.target.classList.add('active');
                }
                document.getElementById('gallery-' + type).classList.add('active');
            }

            function renderGallery(containerId, images, basePath) {
                const container = document.getElementById(containerId);
                if (images && images.length > 0) {
                    const latestImg = images[0];
                    let html = `
                        <div class="latest-container">
                            <h2>Latest Capture</h2>
                            <div class="latest-item">
                                <img src="${basePath}/${latestImg}" title="クリックしてフルサイズの画像を表示" onclick="window.open(this.src, '_blank')">
                                <span>${latestImg}</span>
                            </div>
                        </div>
                    `;

                    if (images.length > 1) {
                        html += '<div class="gallery-grid">';
                        for (let i = 1; i < images.length; i++) {
                            html += `
                                <div class="item">
                                    <div class="img-wrapper" onclick="window.open('${basePath}/${images[i]}', '_blank')">
                                        <img src="${basePath}/${images[i]}" title="クリックしてフルサイズの画像を表示">
                                    </div>
                                    <span>${images[i]}</span>
                                </div>
                            `;
                        }
                        html += '</div>';
                    }
                    container.innerHTML = html;
                } else {
                    container.innerHTML = '<div class="empty-msg">画像が見つかりません。カメラで撮影された画像がここに表示されます。</div>';
                }
            }

            function fetchImages() {
                fetch('/api/images')
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'ok') {
                            const processedChanged = !arraysEqual(currentProcessed, data.processed);
                            const rawChanged = !arraysEqual(currentRaw, data.raw);
                            
                            if (processedChanged || rawChanged) {
                                currentProcessed = data.processed;
                                currentRaw = data.raw;
                                renderGallery('gallery-processed', data.processed, '/images/processed');
                                renderGallery('gallery-raw', data.raw, '/images/raw');
                            }
                        } else {
                            console.error('API Error:', data.message);
                        }
                    })
                    .catch(err => {
                        console.error('Fetch Error:', err.message);
                    });
            }

            // Initial load
            fetchImages();
            
            // Poll every 5 seconds to auto-update
            setInterval(fetchImages, 5000);
        </script>
    </body>
    </html>
    """
    return html_content

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
