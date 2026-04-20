import os
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Depends, HTTPException, status, Header
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from dotenv import load_dotenv
import yolov5
import cv2
import asyncio
import time
from collections import defaultdict
import re
import json
import secrets
import shutil

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
USER_ACCESS_FILE = os.getenv("USER_ACCESS_FILE", "user_access_config.json")

security = HTTPBasic()


def load_user_access_config() -> dict:
    default_config = {"users": {}}
    if not os.path.exists(USER_ACCESS_FILE):
        return default_config

    try:
        with open(USER_ACCESS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read user access config: {e}")
        return default_config

    if not isinstance(raw, dict):
        return default_config

    raw_users = raw.get("users", raw)
    if not isinstance(raw_users, dict):
        return default_config

    normalized_users = {}
    for username, info in raw_users.items():
        if not isinstance(info, dict):
            continue

        clean_username = str(username).strip()
        if not clean_username:
            continue

        password = str(info.get("password", "")).strip()
        allowed_raw = info.get("allowed_cameras", [])
        if not isinstance(allowed_raw, list):
            allowed_raw = []

        allowed_cameras = sorted({
            str(camera).strip() for camera in allowed_raw
            if str(camera).strip()
        })

        normalized_users[clean_username] = {
            "password": password,
            "allowed_cameras": allowed_cameras
        }

    return {"users": normalized_users}


def save_user_access_config(config: dict) -> None:
    normalized = load_user_access_config()
    if isinstance(config, dict):
        raw_users = config.get("users", config)
        if isinstance(raw_users, dict):
            normalized["users"] = {}
            for username, info in raw_users.items():
                if not isinstance(info, dict):
                    continue
                clean_username = str(username).strip()
                if not clean_username:
                    continue
                password = str(info.get("password", "")).strip()
                allowed_raw = info.get("allowed_cameras", [])
                if not isinstance(allowed_raw, list):
                    allowed_raw = []
                normalized["users"][clean_username] = {
                    "password": password,
                    "allowed_cameras": sorted({
                        str(camera).strip() for camera in allowed_raw
                        if str(camera).strip()
                    })
                }

    with open(USER_ACCESS_FILE, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=4, ensure_ascii=False)

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
    
    if is_correct_username and is_correct_password:
        return {
            "username": credentials.username,
            "role": "admin",
            "allowed_cameras": None
        }

    user_access = load_user_access_config()
    user_info = user_access.get("users", {}).get(credentials.username)
    if user_info:
        current_password_bytes = credentials.password.encode("utf8")
        expected_password_bytes = user_info.get("password", "").encode("utf8")
        if secrets.compare_digest(current_password_bytes, expected_password_bytes):
            return {
                "username": credentials.username,
                "role": "user",
                "allowed_cameras": user_info.get("allowed_cameras", [])
            }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Basic"},
    )


def verify_admin(principal: dict = Depends(verify_credentials)):
    if principal.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return principal


def filter_images_for_principal(files: list, principal: dict) -> list:
    if principal.get("role") == "admin":
        return files

    allowed_cameras = set(principal.get("allowed_cameras") or [])
    filtered = []
    for rel_path in files:
        camera_name = rel_path.split("/", 1)[0]
        if camera_name in allowed_cameras:
            filtered.append(rel_path)
    return filtered


def resolve_image_path(base_dir: str, relative_path: str) -> str:
    normalized_rel_path = os.path.normpath(relative_path).lstrip("\\/")
    full_path = os.path.abspath(os.path.join(base_dir, normalized_rel_path))
    base_abs = os.path.abspath(base_dir)
    if os.path.commonpath([base_abs, full_path]) != base_abs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image path")
    return full_path


def verify_camera_access(principal: dict, relative_path: str) -> None:
    if principal.get("role") == "admin":
        return

    normalized_path = relative_path.replace("\\", "/").lstrip("/")
    camera_name = normalized_path.split("/", 1)[0]
    allowed_cameras = set(principal.get("allowed_cameras") or [])
    if camera_name not in allowed_cameras:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Camera access denied")

MAC_MAPPING_FILE = os.getenv("MAC_MAPPING_FILE", "mac_mapping.json")
MAILING_LISTS_FILE = os.getenv("MAILING_LISTS_FILE", "mailing_lists.json")
CAMERA_ALERT_FILE = os.getenv("CAMERA_ALERT_FILE", "camera_alert_config.json")

def load_mailing_lists() -> dict:
    if os.path.exists(MAILING_LISTS_FILE):
        try:
            with open(MAILING_LISTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read mailing lists: {e}")
    return {}

def load_camera_alert_config() -> dict:
    if os.path.exists(CAMERA_ALERT_FILE):
        try:
            with open(CAMERA_ALERT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read camera alert config: {e}")
    return {}

def get_recipients_for_camera(cam_id: str) -> list:
    """Return the recipient list for a given camera ID. Falls back to RECIPIENT_EMAIL."""
    alert_cfg = load_camera_alert_config()
    list_name = alert_cfg.get(cam_id)
    if list_name:
        ml = load_mailing_lists()
        recipients = ml.get(list_name, [])
        if recipients:
            return recipients
    # Fallback to default
    return [e.strip() for e in RECIPIENT_EMAIL.split(',') if e.strip()]


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

def send_email(subject: str, body: str, attachment_path: str = None, recipients: list = None):
    """
    Send an email notification with an optional image attachment.
    If recipients is None, falls back to RECIPIENT_EMAIL env var.
    """
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    if not recipients:
        recipients = [e.strip() for e in RECIPIENT_EMAIL.split(',') if e.strip()]
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
            # カメラIDに応じたメーリングリスト宛先を取得
            alert_recipients = get_recipients_for_camera(raw_id)
            send_email(subject, body, best_data['annotated_path'], recipients=alert_recipients)
            email_duration = (time.perf_counter() - email_start) * 1000
            logger.info(f"Email sent to {alert_recipients} for Cycle {cycle_id}")
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
        if "_" in pure_cam_id:
            parts = pure_cam_id.rsplit("_", 1)
            if parts[1].isdigit():  # KD1_000121 → KD1 のみ分割、Lab_Entrance はそのまま
                pure_cam_id = parts[0]
        pure_cam_id = get_camera_id(pure_cam_id)

    # Save annotated image if target found
    if target_found:
        # フォルダが異なるため processed_ プレフィックス不要
        proc_cam_dir = os.path.join(PROCESSED_DIR, pure_cam_id)
        os.makedirs(proc_cam_dir, exist_ok=True)
        annotated_path = os.path.join(proc_cam_dir, filename)
        
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
        # ← pure_cam_id を先に確定してからファイル名に使用する
        pure_cam_id = re.sub(r"^(pi|satos)_Rcv\d{6}_", "", cam_id)
        if "_" in pure_cam_id:
            parts = pure_cam_id.rsplit("_", 1)
            if parts[1].isdigit():
                pure_cam_id = parts[0]
        pure_cam_id = get_camera_id(pure_cam_id)
        # フォーマット: {カメラID}_{日時}_{シーケンス}_{インデックス}.jpg
        filename = f"{pure_cam_id}_{time_str}_{seq}_{idx}.jpg"
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

@app.get("/images/{image_type}/{image_path:path}")
async def get_image_file(image_type: str, image_path: str, principal: dict = Depends(verify_credentials)):
    if image_type == "raw":
        base_dir = UPLOAD_DIR
    elif image_type == "processed":
        base_dir = PROCESSED_DIR
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown image type")

    verify_camera_access(principal, image_path)
    full_path = resolve_image_path(base_dir, image_path)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    return FileResponse(full_path)


@app.get("/api/images")
async def get_images(principal: dict = Depends(verify_credentials)):
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
        raw_files = filter_images_for_principal(get_all_images(UPLOAD_DIR), principal)
        proc_files = filter_images_for_principal(get_all_images(PROCESSED_DIR), principal)
        
        return {
            "status": "ok",
            "raw": raw_files,
            "processed": proc_files,
            "viewer": {
                "username": principal.get("username"),
                "role": principal.get("role"),
                "allowed_cameras": principal.get("allowed_cameras") or []
            }
        }
    except Exception as e:
        logger.error(f"Failed to get image list: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/config/unmapped_cameras")
async def get_unmapped_cameras(admin: dict = Depends(verify_admin)):
    mapped_keys = []
    mapped_values = []
    if os.path.exists(MAC_MAPPING_FILE):
        with open(MAC_MAPPING_FILE, 'r') as f:
            mapping = json.load(f)
            mapped_keys = list(mapping.keys())
            mapped_values = list(mapping.values())
    
    unmapped = []
    for d in [UPLOAD_DIR, PROCESSED_DIR]:
        if os.path.exists(d):
            for folder in os.listdir(d):
                if os.path.isdir(os.path.join(d, folder)):
                    if folder not in mapped_keys and folder not in mapped_values and folder != "unknown":
                        if folder not in unmapped:
                            unmapped.append(folder)
    return {"status": "ok", "unmapped": unmapped}

@app.delete("/api/config/camera_folder/{folder_name}")
async def delete_camera_folder(folder_name: str, admin: dict = Depends(verify_admin)):
    """Delete an unmapped camera folder and all its images from both upload and processed dirs."""
    try:
        deleted = []
        for base_dir in [UPLOAD_DIR, PROCESSED_DIR]:
            target = os.path.join(base_dir, folder_name)
            if os.path.exists(target) and os.path.isdir(target):
                shutil.rmtree(target)
                deleted.append(target)
        if deleted:
            logger.info(f"Deleted camera folders: {deleted}")
            return {"status": "ok", "deleted": deleted}
        else:
            return {"status": "not_found", "message": f"No folder named '{folder_name}' found."}
    except Exception as e:
        logger.error(f"Failed to delete camera folder '{folder_name}': {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/config/mapping")
async def get_mapping(admin: dict = Depends(verify_admin)):
    if os.path.exists(MAC_MAPPING_FILE):
        with open(MAC_MAPPING_FILE, 'r') as f:
            return json.load(f)
    return {}

@app.post("/api/config/mapping")
async def update_mapping(mapping: dict, admin: dict = Depends(verify_admin)):
    try:
        old_mapping = {}
        if os.path.exists(MAC_MAPPING_FILE):
            with open(MAC_MAPPING_FILE, 'r') as f:
                old_mapping = json.load(f)

        for mac, new_name in mapping.items():
            old_name = old_mapping.get(mac, mac)
            if old_name != new_name:
                for base_dir in [UPLOAD_DIR, PROCESSED_DIR]:
                    old_path = os.path.join(base_dir, old_name)
                    new_path = os.path.join(base_dir, new_name)
                    if os.path.exists(old_path) and os.path.isdir(old_path):
                        if os.path.exists(new_path) and os.path.isdir(new_path):
                            for item in os.listdir(old_path):
                                src_item = os.path.join(old_path, item)
                                dst_item = os.path.join(new_path, item)
                                if not os.path.exists(dst_item):
                                    shutil.move(src_item, new_path)
                            try:
                                os.rmdir(old_path)
                            except OSError:
                                pass
                        else:
                            os.rename(old_path, new_path)

        with open(MAC_MAPPING_FILE, 'w') as f:
            json.dump(mapping, f, indent=4)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Failed to update mapping: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/config/env")
async def get_env(admin: dict = Depends(verify_admin)):
    return {
        "SENDER_EMAIL": SENDER_EMAIL,
        "RECIPIENT_EMAIL": RECIPIENT_EMAIL
    }

# --- Mailing List API ---
@app.get("/api/config/mailing_lists")
async def get_mailing_lists(admin: dict = Depends(verify_admin)):
    return load_mailing_lists()

@app.post("/api/config/mailing_lists")
async def save_mailing_lists(data: dict, admin: dict = Depends(verify_admin)):
    try:
        with open(MAILING_LISTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- Camera Alert Config API ---
@app.get("/api/config/camera_alert")
async def get_camera_alert(admin: dict = Depends(verify_admin)):
    return load_camera_alert_config()

@app.post("/api/config/camera_alert")
async def save_camera_alert(data: dict, admin: dict = Depends(verify_admin)):
    try:
        with open(CAMERA_ALERT_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/config/user_access")
async def get_user_access(admin: dict = Depends(verify_admin)):
    return load_user_access_config()


@app.post("/api/config/user_access")
async def update_user_access(data: dict, admin: dict = Depends(verify_admin)):
    try:
        save_user_access_config(data)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Failed to update user access config: {e}")
        return {"status": "error", "message": str(e)}


class EnvConfig(BaseModel):
    RECIPIENT_EMAIL: str
    SENDER_EMAIL: str

@app.post("/api/config/env")
async def update_env(config: EnvConfig, admin: dict = Depends(verify_admin)):
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
async def admin_dashboard(admin: dict = Depends(verify_admin)):
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

            .inline-edit-input { width: 100%; max-width: 200px; padding: 6px 12px; border: 1px solid #cbd5e0; border-radius: 8px; font-family: 'Inter', sans-serif; font-size: 0.95rem; font-weight: 500; color: #4338ca; background: rgba(255,255,255,0.9); transition: all 0.2s; }
            .inline-edit-input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.2); }

            #toast {
                position: fixed; bottom: 30px; right: 30px; background: #10b981; color: white;
                padding: 15px 25px; border-radius: 12px; box-shadow: 0 10px 30px rgba(16, 185, 129, 0.3);
                font-weight: 500; transform: translateY(100px); opacity: 0; transition: all 0.4s cubic-bezier(0.68, -0.55, 0.265, 1.55); z-index: 1000;
            }
            #toast.show { transform: translateY(0); opacity: 1; }
            
            .add-row { display: grid; grid-template-columns: 2fr 2fr 1fr; gap: 15px; margin-bottom: 20px; align-items: end; }
            .unmapped-highlight { background: rgba(254, 215, 215, 0.2); padding: 15px; border-radius: 12px; border: 1px dashed #fc8181; margin-bottom: 20px; position: relative; }
            
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
                <div id="unmapped-add-rows-container">
                    <!-- Loaded via JS for new cameras -->
                </div>

                <div class="add-row">
                    <div class="form-group" style="margin-bottom:0">
                        <label>Camera ID (Current Folder / MAC)</label>
                        <input type="text" id="new-mac" placeholder="Manual entry...">
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
                            <th>Notification List</th>
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
                    <h2>📧 Mailing Lists</h2>
                </div>
                <div class="add-row" style="grid-template-columns: 1fr 2fr 1fr;">
                    <div class="form-group" style="margin-bottom:0">
                        <label>List Name</label>
                        <input type="text" id="ml-name" placeholder="e.g. 研究室A">
                    </div>
                    <div class="form-group" style="margin-bottom:0">
                        <label>Addresses (comma separated)</label>
                        <input type="text" id="ml-addresses" placeholder="a@example.com, b@example.com">
                    </div>
                    <button class="btn" onclick="addMailingList()">+ Add List</button>
                </div>
                <table style="margin-top:20px;">
                    <thead><tr>
                        <th>List Name</th>
                        <th>Recipients</th>
                        <th style="text-align:right">Actions</th>
                    </tr></thead>
                    <tbody id="ml-body"></tbody>
                </table>
            </div>

            <div class="glass-card">
                <div class="card-header">
                    <h2>System Email Configuration</h2>
                </div>
                
                <div class="form-group">
                    <label>Default Alert Recipients (Comma separated)</label>
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
            
            <div class="glass-card">
                <div class="card-header">
                    <h2>User Gallery Access</h2>
                </div>
                <p style="color: var(--text-sub); margin-top:0; line-height:1.7;">
                    一般ユーザ用のログイン情報と、閲覧を許可するカメラIDを設定します。
                    許可カメラIDはカンマ区切りで入力してください。
                </p>
                <div class="add-row" style="grid-template-columns: 1.2fr 1fr 2fr 1fr;">
                    <div class="form-group" style="margin-bottom:0">
                        <label>User Name</label>
                        <input type="text" id="new-user-name" placeholder="viewer01">
                    </div>
                    <div class="form-group" style="margin-bottom:0">
                        <label>Password</label>
                        <input type="text" id="new-user-password" placeholder="password">
                    </div>
                    <div class="form-group" style="margin-bottom:0">
                        <label>Allowed Camera IDs</label>
                        <input type="text" id="new-user-cameras" placeholder="CAM_01, CAM_02">
                    </div>
                    <button class="btn" onclick="addUserAccess()">+ Add User</button>
                </div>
                <table style="margin-top:20px;">
                    <thead>
                        <tr>
                            <th>User Name</th>
                            <th>Password</th>
                            <th>Allowed Camera IDs</th>
                            <th style="text-align:right">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="user-access-body"></tbody>
                </table>
            </div>

            <a href="/gallery" class="nav-link">← Go back to Image Gallery</a>
        </div>

        <div id="toast">✅ Settings saved successfully!</div>

        <script>
            let currentMapping = {};
            let currentMailingLists = {};
            let currentCameraAlert = {};
            let currentUserAccess = {};

            async function fetchConfig() {
                try {
                    const mapRes = await fetch('/api/config/mapping');
                    currentMapping = await mapRes.json();
                    renderMapping();

                    const envRes = await fetch('/api/config/env');
                    const envData = await envRes.json();
                    document.getElementById('env-recipient').value = envData.RECIPIENT_EMAIL || '';
                    document.getElementById('env-sender').value = envData.SENDER_EMAIL || '';
                    
                    await fetchUnmapped();

                    const mlRes = await fetch('/api/config/mailing_lists');
                    currentMailingLists = await mlRes.json();
                    renderMailingLists();

                    const caRes = await fetch('/api/config/camera_alert');
                    currentCameraAlert = await caRes.json();
                    renderMapping(); // re-render to show dropdowns

                    const uaRes = await fetch('/api/config/user_access');
                    currentUserAccess = await uaRes.json();
                    renderUserAccess();
                } catch (e) {
                    console.error("Failed to load config", e);
                }
            }

            async function fetchUnmapped() {
                try {
                    const res = await fetch('/api/config/unmapped_cameras');
                    const data = await res.json();
                    if (data.status === 'ok' && data.unmapped) {
                        renderUnmappedRows(data.unmapped);
                    }
                } catch(e) {
                    console.error("Error fetching unmapped cameras", e);
                }
            }

            function renderUnmappedRows(unmappedList) {
                const container = document.getElementById('unmapped-add-rows-container');
                if (!container) return;
                container.innerHTML = '';
                
                unmappedList.forEach(mac => {
                    const row = document.createElement('div');
                    row.className = 'add-row unmapped-highlight';
                    row.id = `unmapped-row-${mac}`;
                    row.innerHTML = `
                        <div class="form-group" style="margin-bottom:0">
                            <label>Unmapped Camera Detected 👇</label>
                            <input type="text" value="${mac}" readonly style="background: rgba(254, 215, 215, 0.5); border-color: #fc8181; color: #c53030; font-weight: 600; cursor: not-allowed;">
                        </div>
                        <div class="form-group" style="margin-bottom:0">
                            <label>Enter Assigned ID</label>
                            <input type="text" id="new-id-${mac}" placeholder="Type name here & press Register">
                        </div>
                        <div style="display:flex; gap:8px;">
                            <button class="btn" style="background: #e53e3e; flex:1;" onclick="addUnmappedMapping('${mac}')">+ Register</button>
                            <button class="btn btn-danger" style="padding: 8px 10px;" title="フォルダごと削除" onclick="deleteUnmappedFolder('${mac}')">🗑</button>
                        </div>
                    `;
                    container.appendChild(row);
                });
            }

            function addUnmappedMapping(mac) {
                const idInput = document.getElementById(`new-id-${mac}`);
                if (!idInput) return;
                const newId = idInput.value.trim();
                if (!newId) return;
                
                currentMapping[mac] = newId;
                saveMappingToServer().then(() => {
                    renderMapping();
                    fetchUnmapped();
                });
            }

            async function deleteUnmappedFolder(mac) {
                if (!confirm(`「${mac}」のカメラフォルダとすべての画像を削除しますか？\n\nこの操作は取り消せません。`)) return;
                try {
                    const res = await fetch(`/api/config/camera_folder/${encodeURIComponent(mac)}`, {
                        method: 'DELETE'
                    });
                    const data = await res.json();
                    if (data.status === 'ok') {
                        showToast(`「${mac}」フォルダを削除しました 🗑`);
                        fetchUnmapped();
                    } else {
                        alert('削除に失敗しました: ' + (data.message || data.status));
                    }
                } catch(e) {
                    alert('通信エラーが発生しました');
                }
            }

            function renderMapping() {
                const tbody = document.getElementById('mapping-body');
                tbody.innerHTML = '';
                const listNames = Object.keys(currentMailingLists);
                for (const [mac, id] of Object.entries(currentMapping)) {
                    const selectedList = currentCameraAlert[id] || '';
                    const optionsHtml = `<option value="">デフォルト (Default)</option>` +
                        listNames.map(n => `<option value="${n}" ${n === selectedList ? 'selected' : ''}>${n}</option>`).join('');
                    const tr = document.createElement('tr');
                    tr.className = 'row-item';
                    tr.innerHTML = `
                        <td>${mac}</td>
                        <td>
                            <input type="text" value="${id}" class="inline-edit-input" onchange="updateInlineMapping('${mac}', this.value)" title="タイプしてEnterで保存">
                        </td>
                        <td>
                            <select class="inline-edit-input" style="color:#1e293b;" onchange="updateCameraAlert('${id}', this.value)">
                                ${optionsHtml}
                            </select>
                        </td>
                        <td style="text-align: right">
                            <button class="btn btn-danger" style="padding: 6px 12px; font-size: 0.85rem;" onclick="deleteMapping('${mac}')">Delete</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                }
            }

            function updateCameraAlert(camId, listName) {
                if (listName) {
                    currentCameraAlert[camId] = listName;
                } else {
                    delete currentCameraAlert[camId];
                }
                fetch('/api/config/camera_alert', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(currentCameraAlert)
                }).then(() => showToast('通知先を更新しました 📧'));
            }

            function renderMailingLists() {
                const tbody = document.getElementById('ml-body');
                if (!tbody) return;
                tbody.innerHTML = '';
                for (const [name, addrs] of Object.entries(currentMailingLists)) {
                    const tr = document.createElement('tr');
                    tr.className = 'row-item';
                    tr.innerHTML = `
                        <td style="font-weight:600;">${name}</td>
                        <td>
                            <input type="text" value="${addrs.join(', ')}" class="inline-edit-input" style="max-width:100%;" onchange="updateMailingList('${name}', this.value)">
                        </td>
                        <td style="text-align:right">
                            <button class="btn btn-danger" style="padding:6px 12px;font-size:0.85rem;" onclick="deleteMailingList('${name}')">Delete</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                }
            }

            async function saveMailingListsToServer() {
                await fetch('/api/config/mailing_lists', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(currentMailingLists)
                });
            }

            function addMailingList() {
                const name = document.getElementById('ml-name').value.trim();
                const addrs = document.getElementById('ml-addresses').value.trim();
                if (!name || !addrs) return;
                currentMailingLists[name] = addrs.split(',').map(a => a.trim()).filter(Boolean);
                document.getElementById('ml-name').value = '';
                document.getElementById('ml-addresses').value = '';
                saveMailingListsToServer().then(() => {
                    renderMailingLists();
                    renderMapping(); // update dropdowns
                    showToast('メーリングリストを保存しました 📧');
                });
            }

            function updateMailingList(name, addrStr) {
                currentMailingLists[name] = addrStr.split(',').map(a => a.trim()).filter(Boolean);
                saveMailingListsToServer().then(() => showToast('リストを更新しました'));
            }

            function normalizeCameraList(cameraText) {
                return cameraText.split(',').map(item => item.trim()).filter(Boolean);
            }

            async function persistUserAccess() {
                await fetch('/api/config/user_access', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(currentUserAccess)
                });
            }

            function renderUserAccess() {
                const tbody = document.getElementById('user-access-body');
                if (!tbody) return;
                tbody.innerHTML = '';

                const users = currentUserAccess.users || {};
                for (const [username, info] of Object.entries(users)) {
                    const tr = document.createElement('tr');
                    tr.className = 'row-item';
                    tr.innerHTML = `
                        <td style="font-weight:600;">${username}</td>
                        <td>
                            <input type="text" value="${info.password || ''}" class="inline-edit-input" style="max-width:100%;" onchange="updateUserPassword('${username}', this.value)">
                        </td>
                        <td>
                            <input type="text" value="${(info.allowed_cameras || []).join(', ')}" class="inline-edit-input" style="max-width:100%; color:#1e293b;" onchange="updateUserCameras('${username}', this.value)" placeholder="CAM_01, CAM_02">
                        </td>
                        <td style="text-align:right">
                            <button class="btn btn-danger" style="padding:6px 12px;font-size:0.85rem;" onclick="deleteUserAccess('${username}')">Delete</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                }
            }

            function addUserAccess() {
                const username = document.getElementById('new-user-name').value.trim();
                const password = document.getElementById('new-user-password').value.trim();
                const cameras = normalizeCameraList(document.getElementById('new-user-cameras').value.trim());

                if (!username || !password) {
                    alert('ユーザ名とパスワードを入力してください');
                    return;
                }

                if (!currentUserAccess.users) {
                    currentUserAccess.users = {};
                }

                currentUserAccess.users[username] = {
                    password: password,
                    allowed_cameras: cameras
                };

                persistUserAccess().then(() => {
                    renderUserAccess();
                    document.getElementById('new-user-name').value = '';
                    document.getElementById('new-user-password').value = '';
                    document.getElementById('new-user-cameras').value = '';
                    showToast('ユーザを追加しました');
                });
            }

            function updateUserPassword(username, password) {
                if (!currentUserAccess.users || !currentUserAccess.users[username]) return;
                currentUserAccess.users[username].password = password.trim();
                persistUserAccess().then(() => showToast('パスワードを更新しました'));
            }

            function updateUserCameras(username, cameraText) {
                if (!currentUserAccess.users || !currentUserAccess.users[username]) return;
                currentUserAccess.users[username].allowed_cameras = normalizeCameraList(cameraText);
                persistUserAccess().then(() => showToast('許可カメラを更新しました'));
            }

            function deleteUserAccess(username) {
                if (!currentUserAccess.users || !currentUserAccess.users[username]) return;
                if (!confirm(`ユーザ「${username}」を削除しますか？`)) return;
                delete currentUserAccess.users[username];
                persistUserAccess().then(() => {
                    renderUserAccess();
                    showToast('ユーザを削除しました');
                });
            }

            function deleteMailingList(name) {
                if (!confirm(`「${name}」リストを削除しますか？`)) return;
                delete currentMailingLists[name];
                // Remove assignments using this list
                for (const cam of Object.keys(currentCameraAlert)) {
                    if (currentCameraAlert[cam] === name) delete currentCameraAlert[cam];
                }
                saveMailingListsToServer();
                fetch('/api/config/camera_alert', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(currentCameraAlert)
                });
                renderMailingLists();
                renderMapping();
                showToast('リストを削除しました');
            }

            function updateInlineMapping(mac, newId) {
                newId = newId.trim();
                if (!newId) return;
                currentMapping[mac] = newId;
                saveMappingToServer();
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
                saveMappingToServer().then(() => {
                    renderMapping();
                    fetchUnmapped();
                });
            }

            function deleteMapping(mac) {
                const displayId = currentMapping[mac] || mac;
                if (!confirm(`「${mac}」→「${displayId}」のマッピングを削除しますか？\n\n※ 画像フォルダ自体は削除されません。`)) return;
                delete currentMapping[mac];
                saveMappingToServer().then(() => {
                    renderMapping();
                    fetchUnmapped();
                });
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
async def gallery(principal: dict = Depends(verify_credentials)):
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
        <p style="text-align:center; color:#4a5568; margin:0 0 24px 0;">Logged in as: <strong>__USERNAME__</strong> (__ROLE__)</p>
        
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

            function toggleSection(sectionId) {
                const el = document.getElementById(sectionId);
                const arrow = document.getElementById(sectionId + '-arrow');
                if (!el) return;
                if (el.style.display === 'none' || el.style.display === '') {
                    el.style.display = 'block';
                    if (arrow) arrow.style.transform = 'rotate(90deg)';
                } else {
                    el.style.display = 'none';
                    if (arrow) arrow.style.transform = 'rotate(0deg)';
                }
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
                        const sectionId = `cam-section-${containerId}-${folder.replace(/[^a-z0-9]/gi, '_')}`;
                        
                        html += `
                            <div class="camera-section">
                                <div class="camera-title" onclick="toggleSection('${sectionId}')" style="cursor:pointer; user-select:none; display:flex; align-items:center; justify-content:space-between;">
                                    <span>📷 CAM: ${folder} <span class="badge">${folderImages.length}</span></span>
                                    <span id="${sectionId}-arrow" style="font-size:1.2rem; transition: transform 0.3s;">▶</span>
                                </div>
                                <div id="${sectionId}" style="display:none; overflow:hidden; transition: all 0.3s ease;">
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
                        html += '</div></div>';  // close inner content + camera-section
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
    html_content = html_content.replace("__USERNAME__", principal.get("username", "unknown"))
    html_content = html_content.replace("__ROLE__", principal.get("role", "user"))
    return html_content

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
