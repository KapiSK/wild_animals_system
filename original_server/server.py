import os
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Depends, HTTPException, status, Header
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import yolov5
import cv2
import asyncio
import time
from collections import defaultdict
import re
import json
import secrets

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

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "secret")

API_TOKEN = os.getenv("API_TOKEN", "wild-animals-token-2026")

security = HTTPBasic()

async def verify_api_token(x_api_key: str = Header(None)):
    if x_api_key != API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Token"
        )

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    current_username_bytes = credentials.username.encode("utf8")
    correct_username_bytes = ADMIN_USERNAME.encode("utf8")
    is_correct_username = secrets.compare_digest(current_username_bytes, correct_username_bytes)
    
    current_password_bytes = credentials.password.encode("utf8")
    correct_password_bytes = ADMIN_PASSWORD.encode("utf8")
    is_correct_password = secrets.compare_digest(current_password_bytes, correct_password_bytes)
    
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

MAC_MAPPING_FILE = os.getenv("MAC_MAPPING_FILE", "mac_mapping.json")

def get_camera_id(mac_address: str) -> str:
    try:
        if os.path.exists(MAC_MAPPING_FILE):
            with open(MAC_MAPPING_FILE, 'r') as f:
                mapping = json.load(f)
                return mapping.get(mac_address, mac_address)
    except Exception as e:
        logger.error(f"Failed to read mac mapping: {e}")
    return mac_address

def replace_mac_in_filename(original: str) -> str:
    # 12桁の16進数（MACアドレス）を検索
    match = re.search(r"([A-Fa-f0-9]{12})", original)
    if match:
        mac = match.group(1)
        cam_id = get_camera_id(mac)
        if cam_id != mac:
            return original.replace(mac, cam_id)
    return original

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
        
        # 抽出: IDと日時をファイル名から取得
        best_filename = best_data['filename']
        cam_id = "Unknown"
        cycle_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        
        # 新フォーマット: CAM_01_20260409150849_00000005_1n.jpg
        # または旧フォーマット: 20260409150849_CAM_01-00000005-1n.jpg
        match_new = re.search(r"^(.*?)_(\d{14})_", best_filename)
        match_old = re.search(r"^\d{14}_(.*?(?:-|$))", best_filename)
        
        if match_new:
            cam_id = match_new.group(1)
            time_raw = match_new.group(2)
            cycle_time = f"{time_raw[:4]}/{time_raw[4:6]}/{time_raw[6:8]} {time_raw[8:10]}:{time_raw[10:12]}:{time_raw[12:14]}"
        elif match_old:
            cam_id = re.sub(r"-$", "", match_old.group(1)) # Remove trailing dash if present
            time_raw = best_filename[:14]
            cycle_time = f"{time_raw[:4]}/{time_raw[4:6]}/{time_raw[6:8]} {time_raw[8:10]}:{time_raw[10:12]}:{time_raw[12:14]}"

        # ID部分をパースし、「CAM-{ID}」の形式にするための整理
        raw_id = cam_id
        if raw_id.upper().startswith("CAM-"):
            raw_id = raw_id[4:]
        elif raw_id.upper().startswith("CAM_"):
            raw_id = raw_id[4:]
        elif raw_id.upper().startswith("CAM"):
            raw_id = raw_id[3:]

        # 個体数を省いたラベルのみを取得 ("person: 1, animal: 2" -> "person, animal")
        labels_part = best_data['summary_text']
        if ":" in labels_part:
            labels_part = ", ".join([item.split(':')[0].strip() for item in labels_part.split(',')])
            
        # 時間表記を見やすく秒抜きにする (例: "2026/04/09 15:08")
        short_time = cycle_time.rsplit(':', 1)[0]

        # 2. Compose Email Body
        detected_images_count = sum(1 for f in files if f['target_count'] > 0)
        
        edge_receive_info = ""
        if "_Rcv" in raw_id:
            parts = raw_id.split("_Rcv")
            head = parts[0]
            if len(parts) > 1:
                tail_parts = parts[1].split("_")
                t = tail_parts[0]
                if len(t) == 6:
                    edge_time_str = f"{t[:2]}:{t[2:4]}:{t[4:6]}"
                    display_type = "統合サーバ" if "satos" in head else "エッジサーバ"
                    edge_receive_info = f"・{display_type}受取時刻：{edge_time_str}"
                
                # Extract pure camera name without prefix and timestamp
                raw_id = "_".join(tail_parts[1:])
        
        body_lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f" 🚨 CAM-{raw_id} 検知レポート",
            "━━━━━━━━━━━━━━━━━━━━",
            "■ 検知サマリー",
            f"・カメラ　：CAM-{raw_id}",
            f"・クラウド側検知日時：{cycle_time}"
        ]
        
        if edge_receive_info:
            body_lines.append(edge_receive_info)

        body_lines.extend([
            f"・対象物　：{labels_part} ({len(files)}枚中 {detected_images_count}枚で検知)",
            "",
            "■ 解析ログ (画像ごと)"
        ])
        
        for i, f in enumerate(files, 1):
            f_summary = f['summary_text']
            if f_summary == "No targets":
                f_summary = "検知なし (No targets)"
            body_lines.append(f" [画像{i}] {f_summary}")
            
        body_lines.extend([
            "",
            "■ システム情報",
            f"・Cycle ID: {cycle_id}",
            "",
            "※判定スコアが最も高かった1枚を添付画像として送信しています。"
        ])
            
        body = "\n".join(body_lines)
        
        # ユーザー指定の件名フォーマット（案3 個体数なしver）
        subject = f"【検知】CAM-{raw_id} ｜ {short_time} ｜ {labels_part}"
        
        # 3. Send Email (Skip if no detections)
        email_duration = 0.0
        if detected_images_count > 0:
            email_start = time.perf_counter()
            send_email(subject, body, best_data['annotated_path'])
            email_duration = (time.perf_counter() - email_start) * 1000
            logger.info(f"Aggregated email sent for Cycle {cycle_id}")
        else:
            logger.info(f"Cycle {cycle_id} complete. No targets detected. Skipping email notification.")

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
        # 新フォーマット: {cam_id}_{time_str}_{seq}_{idx}.jpg
        # 例: CAM_01_20260409150849_00000005_1n.jpg
        match_new = re.search(r"^(.*?)_\d{14}_(\d+)_([1-3][nd]?)\.jpg$", filename, re.IGNORECASE)
        if match_new:
            cam_str = match_new.group(1)
            # Remove receiving timestamp prefix to ensure identical Cycle ID despite arrival time differences
            cam_str = re.sub(r"^(pi|satos)_Rcv\d{6}_", "", cam_str)
            # サイクルIDは、カメラIDとシーケンス番号の組み合わせとする
            return f"{cam_str}_{match_new.group(2)}"

        # 旧フォーマットのフォールバック
        match = re.search(r"^(.*)-(\d+)[nd]?\.jpg$", filename, re.IGNORECASE)
        if match:
            full_stem = match.group(1) 
            if '_' in full_stem:
                return full_stem.split('_', 1)[-1]
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
    
    # Extract pure cam id for processed directory
    pure_cam_id = "unknown"
    match_new = re.search(r"^(.*?)_\d{14}_(\d+)_([1-3][nd]?)\.jpg$", filename, re.IGNORECASE)
    if match_new:
        pure_cam_id = re.sub(r"^(pi|satos)_Rcv\d{6}_", "", match_new.group(1))

    # Save annotated image if target found
    if target_found:
        processed_filename = f"processed_{filename}"
        proc_cam_dir = os.path.join(PROCESSED_DIR, pure_cam_id)
        os.makedirs(proc_cam_dir, exist_ok=True)
        annotated_path = os.path.join(proc_cam_dir, processed_filename)
        
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
async def upload_image(background_tasks: BackgroundTasks, file: UploadFile = File(...), api_key: str = Depends(verify_api_token)):
    """
    Receive image, save it, and trigger processing.
    """
    # エッジ側(Pi)が付与した冗長なタイムスタンプ(YYYYMMDD_HHMMSS_microseconds_)を削除
    clean_original = re.sub(r"^\d{8}_\d{6}_\d+_", "", file.filename)
    
    mapped_filename = replace_mac_in_filename(clean_original)
    
    time_str = datetime.now().strftime("%Y%m%d%H%M%S")
    # ESP32のオリジナル形式(ID-SEQ-IDXn.jpg)から、ご要望の(id_日時_シーケンス_インデックス.jpg)へ変換
    match = re.search(r"^(.*?)-(\d+)-([1-3][nd]?)\.jpg$", mapped_filename, re.IGNORECASE)
    if match:
        cam_id = match.group(1)
        seq = match.group(2)
        idx = match.group(3)
        filename = f"{cam_id}_{time_str}_{seq}_{idx}.jpg"
        pure_cam_id = re.sub(r"^(pi|satos)_Rcv\d{6}_", "", cam_id)
    else:
        # フォーマット外のファイルの場合のフォールバック
        filename = f"{time_str}_{mapped_filename}"
        pure_cam_id = "unknown"
        
    cam_dir = os.path.join(UPLOAD_DIR, pure_cam_id)
    os.makedirs(cam_dir, exist_ok=True)
    file_path = os.path.join(cam_dir, filename)
    
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
async def get_images(username: str = Depends(verify_credentials)):
    """
    Return a list of raw and processed images.
    """
    def get_all_images(base_dir):
        files = []
        for root, dirs, filenames in os.walk(base_dir):
            for f in filenames:
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    rel_path = os.path.relpath(os.path.join(root, f), base_dir)
                    rel_path = rel_path.replace(os.sep, '/')
                    files.append(rel_path)
        files.sort(key=lambda x: os.path.getmtime(os.path.join(base_dir, x)), reverse=True)
        return files

    try:
        raw_files = get_all_images(UPLOAD_DIR)
        proc_files = get_all_images(PROCESSED_DIR)
        
        return {"status": "ok", "raw": raw_files, "processed": proc_files}
    except Exception as e:
        logger.error(f"Failed to get image list: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/config/mapping")
async def get_mapping(username: str = Depends(verify_credentials)):
    if os.path.exists(MAC_MAPPING_FILE):
        with open(MAC_MAPPING_FILE, 'r') as f:
            return json.load(f)
    return {}

@app.post("/api/config/mapping")
async def update_mapping(mapping: dict, username: str = Depends(verify_credentials)):
    try:
        with open(MAC_MAPPING_FILE, 'w') as f:
            json.dump(mapping, f, indent=4)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/config/env")
async def get_env(username: str = Depends(verify_credentials)):
    return {
        "SENDER_EMAIL": SENDER_EMAIL,
        "RECIPIENT_EMAIL": RECIPIENT_EMAIL
    }

class EnvConfig(BaseModel):
    RECIPIENT_EMAIL: str
    SENDER_EMAIL: str

@app.post("/api/config/env")
async def update_env(config: EnvConfig, username: str = Depends(verify_credentials)):
    global RECIPIENT_EMAIL, SENDER_EMAIL
    env_path = ".env"
    try:
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        else:
            lines = []
            
        updated_recipient = False
        updated_sender = False
        
        for i, line in enumerate(lines):
            if line.startswith("RECIPIENT_EMAIL="):
                lines[i] = f"RECIPIENT_EMAIL='{config.RECIPIENT_EMAIL}'\n"
                updated_recipient = True
            elif line.startswith("SENDER_EMAIL="):
                lines[i] = f"SENDER_EMAIL='{config.SENDER_EMAIL}'\n"
                updated_sender = True
                
        if not updated_recipient:
            lines.append(f"RECIPIENT_EMAIL='{config.RECIPIENT_EMAIL}'\n")
        if not updated_sender:
            lines.append(f"SENDER_EMAIL='{config.SENDER_EMAIL}'\n")
            
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
            
        os.environ["RECIPIENT_EMAIL"] = config.RECIPIENT_EMAIL
        os.environ["SENDER_EMAIL"] = config.SENDER_EMAIL
        RECIPIENT_EMAIL = config.RECIPIENT_EMAIL
        SENDER_EMAIL = config.SENDER_EMAIL
        
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(username: str = Depends(verify_credentials)):
    html_content = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>System Admin & Settings</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&family=Inter:wght@400;500;600&display=swap');
            
            :root {
                --glass-bg: rgba(255, 255, 255, 0.75);
                --glass-border: rgba(255, 255, 255, 0.5);
                --primary: #4f46e5;
                --primary-hover: #4338ca;
                --text-main: #1e293b;
                --text-sub: #64748b;
            }

            body {
                font-family: 'Inter', sans-serif;
                margin: 0;
                padding: 40px 20px;
                color: var(--text-main);
                min-height: 100vh;
                background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%);
                background-attachment: fixed;
            }

            .blob {
                position: fixed;
                width: 600px;
                height: 600px;
                background: linear-gradient(135deg, rgba(168,237,234,0.6), rgba(254,214,227,0.6));
                border-radius: 50%;
                filter: blur(80px);
                z-index: -1;
                animation: float 15s infinite ease-in-out alternate;
            }
            
            @keyframes float {
                0% { transform: translate(-100px, -100px) scale(0.9); }
                100% { transform: translate(50vw, 50vh) scale(1.1); }
            }

            .container { max-width: 900px; margin: 0 auto; }

            h1 {
                font-family: 'Outfit', sans-serif;
                font-size: 2.5rem;
                font-weight: 600;
                margin-bottom: 30px;
                text-align: center;
                color: #1e293b;
                text-shadow: 0 2px 10px rgba(255,255,255,0.5);
            }

            .glass-card {
                background: var(--glass-bg);
                backdrop-filter: blur(25px);
                -webkit-backdrop-filter: blur(25px);
                border: 1px solid var(--glass-border);
                border-radius: 20px;
                padding: 30px;
                margin-bottom: 30px;
                box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.05);
                transition: transform 0.3s ease, box-shadow 0.3s ease;
            }
            
            .glass-card:hover { box-shadow: 0 12px 40px 0 rgba(31, 38, 135, 0.08); }

            .card-header {
                margin-bottom: 25px;
                border-bottom: 1px solid rgba(0,0,0,0.05);
                padding-bottom: 15px;
            }

            h2 {
                font-family: 'Outfit', sans-serif;
                margin: 0;
                font-size: 1.5rem;
                color: var(--text-main);
            }

            .btn {
                background: var(--primary);
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 12px;
                font-family: 'Inter', sans-serif;
                font-weight: 500;
                cursor: pointer;
                transition: all 0.2s ease;
                box-shadow: 0 4px 15px rgba(79, 70, 229, 0.3);
            }
            .btn:hover { background: var(--primary-hover); transform: translateY(-2px); box-shadow: 0 6px 20px rgba(79, 70, 229, 0.4); }

            .btn-danger { background: #ef4444; box-shadow: 0 4px 15px rgba(239, 68, 68, 0.3); }
            .btn-danger:hover { background: #dc2626; box-shadow: 0 6px 20px rgba(239, 68, 68, 0.4); }

            table { width: 100%; border-collapse: separate; border-spacing: 0 8px; }
            th, td { text-align: left; padding: 15px; }
            th { color: var(--text-sub); font-weight: 500; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em; }

            tr.row-item { background: rgba(255, 255, 255, 0.5); transition: all 0.2s; }
            tr.row-item:hover { background: rgba(255, 255, 255, 0.8); transform: scale(1.01); }

            tr.row-item td:first-child { border-top-left-radius: 12px; border-bottom-left-radius: 12px; font-family: 'JetBrains Mono', monospace; font-size: 1.05rem;}
            tr.row-item td:last-child { border-top-right-radius: 12px; border-bottom-right-radius: 12px; text-align: right;}

            .form-group { margin-bottom: 20px; }
            label { display: block; margin-bottom: 8px; color: var(--text-sub); font-weight: 500; font-size: 0.9rem; }

            input[type="text"], input[type="email"] {
                width: 100%; padding: 12px 15px; border: 1px solid rgba(0,0,0,0.1); border-radius: 12px;
                background: rgba(255,255,255,0.8); font-family: 'Inter', sans-serif; font-size: 1rem;
                transition: all 0.2s; box-sizing: border-box;
            }

            input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.2); background: #fff; }

            #toast {
                position: fixed; bottom: 30px; right: 30px; background: #10b981; color: white;
                padding: 15px 25px; border-radius: 12px; box-shadow: 0 10px 30px rgba(16, 185, 129, 0.3);
                font-weight: 500; transform: translateY(100px); opacity: 0; transition: all 0.4s cubic-bezier(0.68, -0.55, 0.265, 1.55); z-index: 1000;
            }
            #toast.show { transform: translateY(0); opacity: 1; }
            
            .add-row { display: grid; grid-template-columns: 2fr 2fr 1fr; gap: 15px; margin-bottom: 20px; align-items: end; }
            
            .nav-link { text-align: center; margin-top: 20px; display: block; color: var(--primary); text-decoration: none; font-weight: 500; }
            .nav-link:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <div class="blob"></div>
        <div class="container">
            <h1>Admin Dashboard</h1>
            
            <div class="glass-card">
                <div class="card-header">
                    <h2>Camera Edge Mapping</h2>
                </div>
                
                <div class="add-row">
                    <div class="form-group" style="margin-bottom:0">
                        <label>MAC Address (12 chars)</label>
                        <input type="text" id="new-mac" placeholder="ex: AABBCCDDEEFF">
                    </div>
                    <div class="form-group" style="margin-bottom:0">
                        <label>Assigned ID</label>
                        <input type="text" id="new-id" placeholder="ex: CAM_01">
                    </div>
                    <button class="btn" onclick="addMapping()">+ Add</button>
                </div>

                <table>
                    <thead>
                        <tr>
                            <th>Hardware MAC</th>
                            <th>Display ID</th>
                            <th style="text-align: right">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="mapping-body">
                        <!-- Loaded via JS -->
                    </tbody>
                </table>
            </div>

            <div class="glass-card">
                <div class="card-header">
                    <h2>System Email Configuration</h2>
                </div>
                
                <div class="form-group">
                    <label>Alert Recipients (Comma separated)</label>
                    <input type="text" id="env-recipient" placeholder="alert@example.com">
                </div>
                <div class="form-group">
                    <label>System Sender Email</label>
                    <input type="email" id="env-sender" placeholder="system@gmail.com">
                </div>
                
                <div style="text-align: right">
                    <button class="btn" onclick="saveEnv()">Save Changes</button>
                </div>
            </div>
            
            <a href="/gallery" class="nav-link">← Go back to Image Gallery</a>
        </div>

        <div id="toast">✅ Settings saved successfully!</div>

        <script>
            let currentMapping = {};

            async function fetchConfig() {
                try {
                    const mapRes = await fetch('/api/config/mapping');
                    currentMapping = await mapRes.json();
                    renderMapping();

                    const envRes = await fetch('/api/config/env');
                    const envData = await envRes.json();
                    document.getElementById('env-recipient').value = envData.RECIPIENT_EMAIL || '';
                    document.getElementById('env-sender').value = envData.SENDER_EMAIL || '';
                } catch (e) {
                    console.error("Failed to load config", e);
                }
            }

            function renderMapping() {
                const tbody = document.getElementById('mapping-body');
                tbody.innerHTML = '';
                for (const [mac, id] of Object.entries(currentMapping)) {
                    const tr = document.createElement('tr');
                    tr.className = 'row-item';
                    tr.innerHTML = `
                        <td>${mac}</td>
                        <td><span style="background: rgba(79, 70, 229, 0.1); color: #4338ca; padding: 4px 12px; border-radius: 20px; font-weight: 500;">${id}</span></td>
                        <td style="text-align: right">
                            <button class="btn btn-danger" style="padding: 6px 12px; font-size: 0.85rem;" onclick="deleteMapping('${mac}')">Delete</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                }
            }

            async function saveMappingToServer() {
                try {
                    await fetch('/api/config/mapping', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(currentMapping)
                    });
                    showToast("Camera Mapping Updated! 📸");
                } catch(e) {
                    alert("Error saving mapping");
                }
            }

            function addMapping() {
                const mac = document.getElementById('new-mac').value.trim();
                const id = document.getElementById('new-id').value.trim();
                if (!mac || !id) return;
                
                currentMapping[mac] = id;
                document.getElementById('new-mac').value = '';
                document.getElementById('new-id').value = '';
                renderMapping();
                saveMappingToServer();
            }

            function deleteMapping(mac) {
                delete currentMapping[mac];
                renderMapping();
                saveMappingToServer();
            }

            async function saveEnv() {
                const recipient = document.getElementById('env-recipient').value.trim();
                const sender = document.getElementById('env-sender').value.trim();
                
                try {
                    await fetch('/api/config/env', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({RECIPIENT_EMAIL: recipient, SENDER_EMAIL: sender})
                    });
                    showToast("Email Settings Saved! 📧");
                } catch(e) {
                    alert("Error saving env settings");
                }
            }

            function showToast(msg) {
                const toast = document.getElementById('toast');
                toast.innerText = msg;
                toast.classList.add('show');
                setTimeout(() => { toast.classList.remove('show'); }, 3000);
            }

            fetchConfig();
        </script>
    </body>
    </html>
    """
    return html_content

@app.get("/gallery", response_class=HTMLResponse)
async def gallery(username: str = Depends(verify_credentials)):
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
            .camera-section { margin-bottom: 60px; background: #ffffff; border-radius: 16px; padding: 30px 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
            .camera-title { font-size: 1.5rem; color: #1c4532; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; margin-bottom: 30px; display: flex; align-items: center; justify-content: space-between; font-weight: 600; }
            .camera-title .badge { background: #38a169; color: white; font-size: 0.9rem; padding: 4px 12px; border-radius: 20px; font-weight: 600; }
            .latest-container h3 { color: #276749; margin-bottom: 15px; font-weight: 500; }
            .controls-container { display: flex; justify-content: center; align-items: center; margin-bottom: 40px; position: relative; max-width: 1200px; margin-left: auto; margin-right: auto; padding: 0 20px; }
            .tabs { display: flex; gap: 12px; margin-bottom: 0; }
            .view-mode-selector { position: absolute; right: 20px; display: flex; align-items: center; gap: 10px; background: #ffffff; padding: 8px 16px; border-radius: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
            @media (max-width: 768px) {
                .controls-container { flex-direction: column; gap: 20px; }
                .view-mode-selector { position: static; }
            }
            .view-mode-selector label { font-size: 14px; font-weight: 500; color: #4a5568; }
            .view-mode-selector select { border: 1px solid #e2e8f0; border-radius: 8px; padding: 4px 8px; font-family: inherit; color: #2d3748; background: #f8fafc; outline: none; cursor: pointer; }
        </style>
    </head>
    <body>
        <h1>Cloud Server Gallery</h1>
        <div class="header-accent"></div>
        
        <div class="controls-container">
            <div class="tabs">
                <button class="tab active" onclick="showTab('processed')">処理済み画像 (Processed)</button>
                <button class="tab" onclick="showTab('raw')">元画像 (Raw)</button>
            </div>
            <div class="view-mode-selector">
                <label for="viewMode">表示形式:</label>
                <select id="viewMode" onchange="changeViewMode(this.value)">
                    <option value="grouped">カメラ別 (By Camera)</option>
                    <option value="flat">全体表示 (All Photos)</option>
                </select>
            </div>
        </div>
        
        <div class="gallery-container active" id="gallery-processed"></div>
        <div class="gallery-container" id="gallery-raw"></div>
        
        <script>
            let currentProcessed = null;
            let currentRaw = null;
            let currentViewMode = 'grouped';

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
                if (event && event.target && event.target.classList) {
                    event.target.classList.add('active');
                }
                document.getElementById('gallery-' + type).classList.add('active');
            }

            function changeViewMode(mode) {
                currentViewMode = mode;
                renderGallery('gallery-processed', currentProcessed, '/images/processed');
                renderGallery('gallery-raw', currentRaw, '/images/raw');
            }

            function groupImagesByFolder(images) {
                const groups = {};
                images.forEach(img => {
                    const parts = img.split('/');
                    const folder = parts.length > 1 ? parts[0] : 'Root';
                    if (!groups[folder]) groups[folder] = [];
                    groups[folder].push(img);
                });
                return groups;
            }

            function renderGallery(containerId, images, basePath) {
                const container = document.getElementById(containerId);
                if (!images || images.length === 0) {
                    container.innerHTML = '<div class="empty-msg">画像が見つかりません。カメラで撮影された画像がここに表示されます。</div>';
                    return;
                }

                let html = '';

                if (currentViewMode === 'grouped') {
                    const groups = groupImagesByFolder(images);
                    for (const folder of Object.keys(groups).sort()) {
                        const folderImages = groups[folder];
                        const latestImg = folderImages[0];
                        const displayFilename = latestImg.split('/').pop();
                        
                        html += `
                            <div class="camera-section">
                                <h2 class="camera-title">📷 CAM: ${folder} <span class="badge">${folderImages.length}</span></h2>
                                <div class="latest-container">
                                    <h3>Latest Capture</h3>
                                    <div class="latest-item">
                                        <img src="${basePath}/${latestImg}" title="クリックしてフルサイズの画像を表示" onclick="window.open(this.src, '_blank')">
                                        <span>${displayFilename}</span>
                                    </div>
                                </div>
                        `;

                        if (folderImages.length > 1) {
                            html += '<div class="gallery-grid">';
                            for (let i = 1; i < folderImages.length; i++) {
                                const filename = folderImages[i].split('/').pop();
                                html += `
                                    <div class="item">
                                        <div class="img-wrapper" onclick="window.open('${basePath}/${folderImages[i]}', '_blank')">
                                            <img src="${basePath}/${folderImages[i]}" title="クリックしてフルサイズの画像を表示">
                                        </div>
                                        <span>${filename}</span>
                                    </div>
                                `;
                            }
                            html += '</div>';
                        }
                        html += '</div>';
                    }
                } else {
                    // Flat / All Folders View
                    const latestImg = images[0];
                    html += `
                        <div class="latest-container" style="margin-top: 20px;">
                            <h2 style="color: #276749;">Latest Capture (All Cameras)</h2>
                            <div class="latest-item">
                                <img src="${basePath}/${latestImg}" title="クリックしてフルサイズの画像を表示" onclick="window.open(this.src, '_blank')">
                                <span>${latestImg}</span>
                            </div>
                        </div>
                    `;

                    if (images.length > 1) {
                        html += '<div class="gallery-grid" style="margin-top: 30px;">';
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
                }
                
                container.innerHTML = html;
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
