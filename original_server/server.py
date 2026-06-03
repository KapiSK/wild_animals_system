import os
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Depends, HTTPException, status, Header, Request, Form, Query
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from typing import Optional
import tempfile
import zipfile
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
import csv

# Load environment variables
load_dotenv()

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_config_path(path_value: str) -> str:
    expanded = os.path.expanduser(path_value)
    if os.path.isabs(expanded):
        return expanded
    return os.path.abspath(os.path.join(APP_DIR, expanded))


# Configuration
UPLOAD_DIR = resolve_config_path(os.getenv("UPLOAD_DIR", "received_images"))
PROCESSED_DIR = resolve_config_path(os.getenv("PROCESSED_DIR", "processed_images"))
VIDEO_DIR = resolve_config_path(os.getenv("VIDEO_DIR", "received_videos"))
EVENT_METADATA_DIR = resolve_config_path(os.getenv("EVENT_METADATA_DIR", "event_metadata"))
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "your_email@example.com")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "your_password")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "recipient@example.com")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "secret")

API_TOKEN = os.getenv("API_TOKEN", "wild-animals-token-2026")
USER_ACCESS_FILE = resolve_config_path(os.getenv("USER_ACCESS_FILE", "user_access_config.json"))
TELEMETRY_FILE = resolve_config_path(os.getenv("TELEMETRY_FILE", "telemetry.json"))
SERVER_SEQUENCE_FILE = resolve_config_path(os.getenv("SERVER_SEQUENCE_FILE", "server_sequence.json"))

APP_VERSION = os.getenv("APP_VERSION", "1.0.1")

PORT_STR = os.getenv("PORT", "8000")
if PORT_STR == "8000":
    ENV_BADGE = f'<span style="display:inline-block; background: #28a745; color: white; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 0.95rem;">Version (v{APP_VERSION})</span>'
else:
    ENV_BADGE = f'<span style="display:inline-block; background: #dc3545; color: white; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 0.95rem;">Test Environment (v{APP_VERSION} - Port {PORT_STR})</span>'

def get_env_badge(page_name: str = "") -> str:
    if not page_name:
        return ENV_BADGE
    color = "#2b6cb0" if page_name == "Admin Settings" else "#2f855a" if page_name == "Gallery" else "#4a5568"
    return f'{ENV_BADGE}<br><span style="display:inline-block; background: {color}; color: white; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 0.82rem; margin-top: 4px;">{page_name}</span>'

security = HTTPBasic(auto_error=False)
SESSION_COOKIE_NAME = "wild_animals_session"
SESSION_STORE = {}

THEME_TOGGLE_SCRIPT = """
<script>
(function() {
    var storedTheme = localStorage.getItem('theme');
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (storedTheme === 'dark' || (!storedTheme && prefersDark)) {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
})();
</script>
"""

THEME_TOGGLE_UI = """
<button id="theme-toggle" style="position: fixed; bottom: 24px; right: 24px; width: 48px; height: 48px; border-radius: 50%; background: #ffffff; border: 1px solid #e2e8f0; box-shadow: 0 4px 12px rgba(0,0,0,0.1); cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 1.2rem; z-index: 10000; transition: all 0.2s ease; padding: 0;">
    <span id="theme-icon">☀️</span>
</button>
<script>
(function() {
    var btn = document.getElementById('theme-toggle');
    var icon = document.getElementById('theme-icon');
    
    function updateIcon() {
        var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        icon.textContent = isDark ? '🌙' : '☀️';
        btn.style.background = isDark ? '#1e293b' : '#ffffff';
        btn.style.borderColor = isDark ? '#334155' : '#e2e8f0';
    }
    
    updateIcon();
    
    btn.addEventListener('click', function() {
        var currentTheme = document.documentElement.getAttribute('data-theme');
        var newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
        updateIcon();
    });
})();
</script>
"""

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


def load_telemetry() -> dict:
    if not os.path.exists(TELEMETRY_FILE):
        return {}
    try:
        with open(TELEMETRY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read telemetry config: {e}")
        return {}


def save_telemetry(data: dict) -> None:
    try:
        with open(TELEMETRY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save telemetry config: {e}")

import threading
_seq_lock_sync = threading.Lock()

def load_server_sequence() -> dict:
    if not os.path.exists(SERVER_SEQUENCE_FILE):
        return {}
    try:
        with open(SERVER_SEQUENCE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read server sequence: {e}")
        return {}

def save_server_sequence(data: dict) -> None:
    try:
        with open(SERVER_SEQUENCE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save server sequence: {e}")

def get_or_increment_server_sequence(camera_id: str, edge_event_id: str, timeout_sec: int = 300) -> str:
    with _seq_lock_sync:
        data = load_server_sequence()
        cam_data = data.get(camera_id, {
            "current_server_seq": 0,
            "last_edge_event_id": "",
            "last_update_time": 0.0
        })
        
        now = time.time()
        # 同一エッジイベントで、かつタイムアウト以内なら、同じシーケンス番号を返す
        if cam_data["last_edge_event_id"] == edge_event_id and (now - cam_data["last_update_time"]) <= timeout_sec:
            cam_data["last_update_time"] = now
            data[camera_id] = cam_data
            save_server_sequence(data)
            return f"{cam_data['current_server_seq']:04d}"
            
        # そうでなければカウントアップ
        cam_data["current_server_seq"] += 1
        cam_data["last_edge_event_id"] = edge_event_id
        cam_data["last_update_time"] = now
        data[camera_id] = cam_data
        save_server_sequence(data)
        
        return f"{cam_data['current_server_seq']:04d}"

def init_server_sequence() -> None:
    data = load_server_sequence()
    updated = False
    
    # 既存の event_metadata から最大の sequence を探す
    for root, _, files in os.walk(EVENT_METADATA_DIR):
        for f in files:
            if f.endswith(".json"):
                try:
                    with open(os.path.join(root, f), "r", encoding="utf-8") as jf:
                        meta = json.load(jf)
                    event_id = meta.get("event_id", "")
                    camera_id = meta.get("camera_id", "")
                    if not event_id or not camera_id:
                        continue
                    
                    # event_id = {camera_id}_{seq}
                    parts = event_id.rsplit("_", 1)
                    if len(parts) == 2 and parts[1].isdigit():
                        seq_num = int(parts[1])
                        cam_data = data.get(camera_id, {
                            "current_server_seq": 0,
                            "last_edge_event_id": "",
                            "last_update_time": 0.0
                        })
                        if seq_num > cam_data["current_server_seq"]:
                            cam_data["current_server_seq"] = seq_num
                            data[camera_id] = cam_data
                            updated = True
                except Exception:
                    pass
                    
    if updated:
        save_server_sequence(data)
        logger.info("Initialized server sequences from existing metadata.")


async def verify_api_token(x_api_key: str = Header(None)):
    if x_api_key != API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Token"
        )

def authenticate_user(username: str, password: str):
    current_username_bytes = username.encode("utf8")
    correct_username_bytes = ADMIN_USERNAME.encode("utf8")
    is_correct_username = secrets.compare_digest(current_username_bytes, correct_username_bytes)

    current_password_bytes = password.encode("utf8")
    correct_password_bytes = ADMIN_PASSWORD.encode("utf8")
    is_correct_password = secrets.compare_digest(current_password_bytes, correct_password_bytes)

    if is_correct_username and is_correct_password:
        return {
            "username": username,
            "role": "admin",
            "allowed_cameras": None
        }

    user_access = load_user_access_config()
    user_info = user_access.get("users", {}).get(username)
    if user_info:
        expected_password_bytes = user_info.get("password", "").encode("utf8")
        if secrets.compare_digest(current_password_bytes, expected_password_bytes):
            return {
                "username": username,
                "role": "user",
                "allowed_cameras": user_info.get("allowed_cameras", [])
            }

    return None


def create_session(principal: dict) -> str:
    session_token = secrets.token_urlsafe(32)
    SESSION_STORE[session_token] = {
        "username": principal.get("username"),
        "role": principal.get("role"),
        "allowed_cameras": principal.get("allowed_cameras")
    }
    return session_token


def get_principal_from_session(request: Request):
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return None
    return SESSION_STORE.get(session_token)


def clear_session(request: Request):
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        SESSION_STORE.pop(session_token, None)


def get_optional_principal(request: Request, credentials: HTTPBasicCredentials = None):
    session_principal = get_principal_from_session(request)
    if session_principal:
        return session_principal

    if credentials is not None:
        return authenticate_user(credentials.username, credentials.password)

    return None


def verify_credentials(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security)
):
    principal = get_optional_principal(request, credentials)
    if principal:
        return principal

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


def extract_event_id_from_video_filename(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename))[0]
    match = re.match(r"^(.*?)_(\d{14})_(\d+)$", stem)
    if match:
        return f"{match.group(1)}_{match.group(3)}"
    return stem


def build_video_filename(camera_id: str, seq: str, suffix: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{camera_id}_{timestamp}_{seq}{suffix.lower()}"


def get_video_relpaths_for_event(camera_id: str, event_id: str) -> list:
    camera_dir = os.path.join(VIDEO_DIR, camera_id)
    if not os.path.isdir(camera_dir):
        return []

    relpaths = []
    for name in os.listdir(camera_dir):
        file_path = os.path.join(camera_dir, name)
        if not os.path.isfile(file_path):
            continue
        if extract_event_id_from_video_filename(name) != event_id:
            continue
        relpaths.append(f"{camera_id}/{name}".replace(os.sep, "/"))

    relpaths.sort(key=lambda x: os.path.getmtime(os.path.join(VIDEO_DIR, x.replace("/", os.sep))), reverse=True)
    return relpaths


def get_related_event_images(base_dir: str, camera_id: str, event_id: str) -> list:
    camera_dir = os.path.join(base_dir, camera_id)
    if not os.path.isdir(camera_dir):
        return []

    relpaths = []
    for name in os.listdir(camera_dir):
        file_path = os.path.join(camera_dir, name)
        if not os.path.isfile(file_path):
            continue
        if extract_cycle_id(name) != event_id:
            continue
        relpaths.append(f"{camera_id}/{name}".replace(os.sep, "/"))

    relpaths.sort(key=lambda x: os.path.getmtime(os.path.join(base_dir, x.replace("/", os.sep))), reverse=True)
    return relpaths


def get_related_processed_images(camera_id: str, event_id: str) -> list:
    return get_related_event_images(PROCESSED_DIR, camera_id, event_id)


def get_related_raw_images(camera_id: str, event_id: str) -> list:
    return get_related_event_images(UPLOAD_DIR, camera_id, event_id)


def get_event_metadata_path(camera_id: str, event_id: str) -> str:
    safe_camera_id = re.sub(r"[^0-9A-Za-z_-]", "_", camera_id) or "unknown"
    safe_event_id = re.sub(r"[^0-9A-Za-z_-]", "_", event_id) or "unknown"
    camera_dir = os.path.join(EVENT_METADATA_DIR, safe_camera_id)
    os.makedirs(camera_dir, exist_ok=True)
    return os.path.join(camera_dir, f"{safe_event_id}.json")


def save_event_metadata(camera_id: str, event_id: str, metadata: dict) -> None:
    path = get_event_metadata_path(camera_id, event_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def load_event_metadata(camera_id: str, event_id: str) -> dict | None:
    path = get_event_metadata_path(camera_id, event_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read event metadata {path}: {e}")
        return None


def build_event_metadata_map(base_dir: str, files: list) -> dict:
    metadata_map = {}
    for rel_path in files:
        camera_id = rel_path.split("/", 1)[0]
        event_id = extract_cycle_id(os.path.basename(rel_path))
        key = f"{camera_id}/{event_id}"
        if key not in metadata_map:
            meta = load_event_metadata(camera_id, event_id)
            if meta:
                meta["video_paths"] = get_video_relpaths_for_event(camera_id, event_id)
                metadata_map[key] = meta
    return metadata_map


def collect_event_images(base_dir: str) -> dict:
    events: dict[tuple[str, str], list[str]] = defaultdict(list)
    if not os.path.isdir(base_dir):
        return events

    for root, _, filenames in os.walk(base_dir):
        for filename in filenames:
            if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif")):
                continue
            rel_path = os.path.relpath(os.path.join(root, filename), base_dir).replace(os.sep, "/")
            camera_id = rel_path.split("/", 1)[0]
            event_id = extract_cycle_id(filename)
            events[(camera_id, event_id)].append(rel_path)

    for rel_paths in events.values():
        rel_paths.sort()
    return events


def build_event_metadata_payload(camera_id: str, event_id: str) -> dict | None:
    processed_images = get_related_processed_images(camera_id, event_id)
    raw_images = get_related_raw_images(camera_id, event_id)
    if not processed_images and not raw_images:
        return None

    existing_metadata = load_event_metadata(camera_id, event_id) or {}
    source = existing_metadata.get("source", "unknown")

    selected_images = processed_images or raw_images
    image_summaries = dict(existing_metadata.get("image_summaries", {}))
    normalized_summaries = {}
    labels = set()
    target_count = 0
    max_conf = 0.0
    detected_images_count = 0

    for rel_path in selected_images:
        filename = os.path.basename(rel_path)
        summary = image_summaries.get(filename, "")
        if summary:
            normalized_summaries[filename] = summary
        if summary and summary != "No targets":
            detected_images_count += 1
            for part in summary.split(","):
                label_part = part.strip()
                if not label_part:
                    continue
                if ":" in label_part:
                    label_name, count_text = label_part.split(":", 1)
                    label_name = label_name.strip()
                    labels.add(label_name)
                    try:
                        count_value = int(count_text.strip())
                    except ValueError:
                        count_value = 1
                else:
                    label_name = label_part
                    labels.add(label_name)
                    count_value = 1
                target_count += count_value
                max_conf = max(max_conf, 1.0)
        elif summary == "No targets":
            normalized_summaries[filename] = summary

    best_image = existing_metadata.get("best_image", "")
    if not best_image or os.path.basename(best_image) not in {os.path.basename(path) for path in selected_images}:
        best_image = selected_images[0]

    cycle_time = existing_metadata.get("cycle_time", "")
    if not cycle_time and selected_images:
        sample_name = os.path.basename(selected_images[0])
        match_new = re.search(r"^(.*?)_(\d{14})_(\d+)_([1-3][nd]?)\.jpg$", sample_name, re.IGNORECASE)
        if match_new:
            time_raw = match_new.group(2)
            cycle_time = f"{time_raw[:4]}/{time_raw[4:6]}/{time_raw[6:8]} {time_raw[8:10]}:{time_raw[10:12]}:{time_raw[12:14]}"

    video_paths = get_video_relpaths_for_event(camera_id, event_id)

    return {
        "event_id": event_id,
        "camera_id": camera_id,
        "source": source,
        "labels": sorted(labels) or existing_metadata.get("labels", []),
        "target_count": target_count or existing_metadata.get("target_count", 0),
        "detected_images_count": detected_images_count or existing_metadata.get("detected_images_count", 0),
        "max_conf": max_conf or existing_metadata.get("max_conf", 0.0),
        "summary_text": existing_metadata.get("summary_text", ""),
        "best_image": best_image if "/" in best_image else f"{camera_id}/{os.path.basename(best_image)}",
        "images": [path if "/" in path else f"{camera_id}/{path}" for path in selected_images],
        "image_summaries": normalized_summaries or existing_metadata.get("image_summaries", {}),
        "has_video": bool(video_paths),
        "cycle_time": cycle_time,
        "updated_at": datetime.now().isoformat(),
    }


def backfill_event_metadata() -> None:
    processed_events = collect_event_images(PROCESSED_DIR)
    raw_events = collect_event_images(UPLOAD_DIR)
    event_keys = set(processed_events.keys()) | set(raw_events.keys())
    if not event_keys:
        logger.info("No existing events found for metadata backfill.")
        return

    updated = 0
    skipped = 0
    for camera_id, event_id in sorted(event_keys):
        try:
            payload = build_event_metadata_payload(camera_id, event_id)
            if not payload:
                skipped += 1
                continue

            existing_metadata = load_event_metadata(camera_id, event_id)
            if existing_metadata == payload:
                skipped += 1
                continue

            save_event_metadata(camera_id, event_id, payload)
            updated += 1
        except Exception as e:
            logger.error(f"Failed to backfill event metadata for {camera_id}/{event_id}: {e}")

    logger.info(f"Event metadata backfill completed. updated={updated}, skipped={skipped}")


def cycle_needs_reinference(camera_id: str, event_id: str) -> bool:
    processed_images = get_related_processed_images(camera_id, event_id)
    raw_images = get_related_raw_images(camera_id, event_id)
    selected_images = processed_images or raw_images
    if not selected_images:
        return False

    metadata = load_event_metadata(camera_id, event_id) or {}
    image_summaries = metadata.get("image_summaries")
    if not isinstance(image_summaries, dict):
        return True

    for rel_path in selected_images:
        filename = os.path.basename(rel_path)
        summary = image_summaries.get(filename)
        if not isinstance(summary, str) or not summary.strip():
            return True
    return False


def reprocess_event_cycle(camera_id: str, event_id: str) -> bool:
    raw_images = get_related_raw_images(camera_id, event_id)
    if not raw_images:
        logger.warning(f"Reinference skipped for {camera_id}/{event_id}: raw images not found.")
        return False

    analyzed_results = []
    for rel_path in raw_images:
        raw_abs = resolve_image_path(UPLOAD_DIR, rel_path)
        if not os.path.isfile(raw_abs):
            logger.warning(f"Missing raw image during reinference: {raw_abs}")
            continue
        analyzed_results.append(analyze_image_for_cycle(raw_abs, os.path.basename(rel_path), "backfill"))

    if not analyzed_results:
        return False

    analyzed_results.sort(key=lambda item: item['filename'])
    labels = sorted({label for item in analyzed_results for label in item.get('labels', [])})
    detected_images_count = sum(1 for item in analyzed_results if item.get('target_count', 0) > 0)
    best_data = sorted(analyzed_results, key=lambda item: (item.get('target_count', 0), item.get('max_conf', 0.0)), reverse=True)[0]

    cycle_time = ""
    match_new = re.search(r"^(.*?)_(\d{14})_(\d+)_([1-3][nd]?)\.jpg$", best_data['filename'], re.IGNORECASE)
    if match_new:
        time_raw = match_new.group(2)
        cycle_time = f"{time_raw[:4]}/{time_raw[4:6]}/{time_raw[6:8]} {time_raw[8:10]}:{time_raw[10:12]}:{time_raw[12:14]}"

    source = (load_event_metadata(camera_id, event_id) or {}).get("source", "backfill")
    payload = {
        "event_id": event_id,
        "camera_id": camera_id,
        "source": source,
        "labels": labels,
        "target_count": max((item.get("target_count", 0) for item in analyzed_results), default=0),
        "detected_images_count": detected_images_count,
        "max_conf": max((item.get("max_conf", 0.0) for item in analyzed_results), default=0.0),
        "summary_text": best_data.get("summary_text", ""),
        "best_image": f"{camera_id}/{best_data['filename']}",
        "images": [f"{camera_id}/{item['filename']}" for item in analyzed_results],
        "image_summaries": {item['filename']: item.get("summary_text", "") for item in analyzed_results},
        "has_video": len(get_video_relpaths_for_event(camera_id, event_id)) > 0,
        "cycle_time": cycle_time,
        "updated_at": datetime.now().isoformat(),
    }
    save_event_metadata(camera_id, event_id, payload)
    return True


def reinfer_missing_cycles() -> None:
    processed_events = collect_event_images(PROCESSED_DIR)
    raw_events = collect_event_images(UPLOAD_DIR)
    event_keys = sorted(set(processed_events.keys()) | set(raw_events.keys()))
    if not event_keys:
        logger.info("No existing events found for reinference scan.")
        return

    updated = 0
    skipped = 0
    for camera_id, event_id in event_keys:
        try:
            if not cycle_needs_reinference(camera_id, event_id):
                skipped += 1
                continue
            if reprocess_event_cycle(camera_id, event_id):
                updated += 1
            else:
                skipped += 1
        except Exception as e:
            logger.error(f"Failed to reinfer cycle {camera_id}/{event_id}: {e}")

    logger.info(f"Missing cycle reinference completed. updated={updated}, skipped={skipped}")


async def run_startup_maintenance() -> None:
    try:
        await asyncio.to_thread(backfill_event_metadata)
        await asyncio.to_thread(reinfer_missing_cycles)
    except Exception as e:
        logger.error(f"Startup maintenance failed: {e}")


def file_matches_filters(rel_path: str, metadata_map: dict, filters: dict) -> bool:
    if not filters:
        return True

    camera_id = rel_path.split("/", 1)[0]
    event_id = extract_cycle_id(os.path.basename(rel_path))
    metadata = metadata_map.get(f"{camera_id}/{event_id}")

    detection_filter = filters.get("detection", "all")
    label_filter = filters.get("label", "all")
    video_filter = filters.get("video", "all")
    source_filter = filters.get("source", "all")
    min_conf = filters.get("min_conf")

    if not metadata:
        return detection_filter == "all" and label_filter == "all" and video_filter == "all" and source_filter == "all" and not min_conf

    target_count = int(metadata.get("target_count", 0))
    labels = set(metadata.get("labels", []))
    has_video = bool(metadata.get("has_video", False))
    source = metadata.get("source", "unknown")
    max_conf = float(metadata.get("max_conf", 0.0))

    if detection_filter == "detected" and target_count <= 0:
        return False
    if detection_filter == "not_detected" and target_count > 0:
        return False
    if label_filter != "all" and label_filter not in labels:
        return False
    if video_filter == "with_video" and not has_video:
        return False
    if video_filter == "without_video" and has_video:
        return False
    if source_filter != "all" and source != source_filter:
        return False
    if min_conf is not None and max_conf < min_conf:
        return False
    return True


def get_available_camera_ids() -> list:
    camera_ids = set()

    try:
        mapping = {}
        if os.path.exists(MAC_MAPPING_FILE):
            with open(MAC_MAPPING_FILE, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        if isinstance(mapping, dict):
            camera_ids.update(str(v).strip() for v in mapping.values() if str(v).strip())
    except Exception as e:
        logger.error(f"Failed to load camera mapping for available cameras: {e}")

    for base_dir in [UPLOAD_DIR, PROCESSED_DIR]:
        if os.path.exists(base_dir):
            for folder in os.listdir(base_dir):
                folder_path = os.path.join(base_dir, folder)
                if os.path.isdir(folder_path) and folder != "unknown":
                    camera_ids.add(folder)

    camera_ids.update(load_camera_alert_config().keys())

    user_access = load_user_access_config()
    for info in user_access.get("users", {}).values():
        if not isinstance(info, dict):
            continue
        for camera_id in info.get("allowed_cameras", []):
            camera_text = str(camera_id).strip()
            if camera_text:
                camera_ids.add(camera_text)

    return sorted(camera_ids)

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
os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(EVENT_METADATA_DIR, exist_ok=True)

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

def migrate_statistics_csv():
    stat_csv = os.path.join(EVENT_METADATA_DIR, "statistics.csv")
    if not os.path.exists(stat_csv):
        return
        
    try:
        with open(stat_csv, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        if not lines:
            return
            
        header = lines[0].strip().split(",")
        if "cycle_id" in header:
            return # Already migrated
            
        logger.info("Migrating statistics.csv to include cycle_id...")
        
        # Build a mapping of cycle_time to cycle_id from metadata
        time_to_cycle_id = {}
        for root, _, files in os.walk(EVENT_METADATA_DIR):
            for file in files:
                if file.endswith(".json"):
                    try:
                        with open(os.path.join(root, file), "r", encoding="utf-8") as jf:
                            meta = json.load(jf)
                            c_time = meta.get("cycle_time")
                            c_id = meta.get("event_id")
                            if c_time and c_id:
                                time_to_cycle_id[c_time] = c_id
                    except Exception:
                        pass

        # Rewrite CSV with cycle_id
        new_header = "timestamp,cycle_id,camera_id,temperature,labels,target_count\n"
        with open(stat_csv, "w", encoding="utf-8") as f:
            f.write(new_header)
            for line in lines[1:]:
                parts = line.strip().split(",")
                if len(parts) >= 5:
                    timestamp = parts[0]
                    camera_id = parts[1]
                    temperature = parts[2]
                    labels = parts[3]
                    target_count = parts[4]
                    cycle_id = time_to_cycle_id.get(timestamp, "")
                    f.write(f"{timestamp},{cycle_id},{camera_id},{temperature},{labels},{target_count}\n")
                else:
                    f.write(line)
        logger.info("Successfully migrated statistics.csv")
    except Exception as e:
        logger.error(f"Failed to migrate statistics.csv: {e}")

migrate_statistics_csv()

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
        camera_id = best_data.get('camera_id', 'unknown')
        labels = sorted({label for f in files for label in f.get('labels', [])})
        source = best_data.get('source', 'unknown')
        
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

        current_telemetry = load_telemetry().get(camera_id, {})
        temperature = current_telemetry.get("temperature", "")

        try:
            event_metadata = {
                "event_id": cycle_id,
                "camera_id": camera_id,
                "source": source,
                "labels": labels,
                "target_count": max((f.get("target_count", 0) for f in files), default=0),
                "detected_images_count": detected_images_count,
                "max_conf": max((f.get("max_conf", 0.0) for f in files), default=0.0),
                "summary_text": best_data.get("summary_text", ""),
                "best_image": f"{camera_id}/{best_data['filename']}",
                "images": [f"{camera_id}/{f['filename']}" for f in files],
                "image_summaries": {f['filename']: f.get("summary_text", "") for f in files},
                "detections": {f['filename']: f.get("detections", []) for f in files},
                "has_video": len(get_video_relpaths_for_event(camera_id, cycle_id)) > 0,
                "cycle_time": cycle_time,
                "temperature": temperature,
                "updated_at": datetime.now().isoformat(),
            }
            save_event_metadata(camera_id, cycle_id, event_metadata)
        except Exception as e:
            logger.error(f"Failed to save event metadata for {cycle_id}: {e}")

        # --- Statistics Logging ---
        try:
            stat_csv = "statistics.csv"
            stat_exists = os.path.isfile(stat_csv)
            with open(stat_csv, "a", encoding="utf-8") as f:
                if not stat_exists:
                    f.write("timestamp,cycle_id,camera_id,temperature,labels,target_count\n")
                
                labels_str = "|".join(labels) if labels else "None"
                # timestamp として画像の撮影日時(cycle_time)を使用
                f.write(f"{cycle_time},{cycle_id},{camera_id},{temperature},{labels_str},{event_metadata['target_count']}\n")
        except Exception as e:
            logger.error(f"Failed to write statistics: {e}")

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
    init_server_sequence()
    asyncio.create_task(run_startup_maintenance())
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
            if "X" in cam_str:
                cam_str = cam_str.split("X", 1)[0]
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


def analyze_image_for_cycle(image_path: str, filename: str, source: str) -> dict:
    model.conf = 0.25
    results = model(image_path)

    detected_targets = {}
    target_found = False
    max_conf = 0.0

    df = results.pandas().xyxy[0]
    df_n = results.pandas().xyxyn[0]
    detections = []

    for index, row in df.iterrows():
        cls = int(row['class'])
        if cls in TARGET_CLASSES:
            target_found = True
            label = row['name']
            conf = float(row['confidence'])
            detected_targets[label] = detected_targets.get(label, 0) + 1
            if conf > max_conf:
                max_conf = conf

            row_n = df_n.iloc[index]
            w_norm = row_n['xmax'] - row_n['xmin']
            h_norm = row_n['ymax'] - row_n['ymin']
            bbox = [
                round(row_n['xmin'], 4),
                round(row_n['ymin'], 4),
                round(w_norm, 4),
                round(h_norm, 4)
            ]
            detections.append({
                "category": str(cls),
                "conf": round(conf, 4),
                "bbox": bbox
            })

    if detected_targets:
        counts_str = ", ".join([f"{label}: {count}" for label, count in detected_targets.items()])
    else:
        counts_str = "No targets"

    annotated_path = image_path

    pure_cam_id = "unknown"
    match_new = re.search(r"^(.*?)_\d{14}_(\d+)_([1-3][nd]?)\.jpg$", filename, re.IGNORECASE)
    if match_new:
        pure_cam_id = re.sub(r"^(pi|satos)_Rcv\d{6}_", "", match_new.group(1))
        if "_" in pure_cam_id:
            parts = pure_cam_id.rsplit("_", 1)
            if parts[1].isdigit():
                pure_cam_id = parts[0]
        pure_cam_id = get_camera_id(pure_cam_id)
        if "X" in pure_cam_id:
            pure_cam_id = pure_cam_id.split("X", 1)[0]

    proc_cam_dir = os.path.join(PROCESSED_DIR, pure_cam_id)
    os.makedirs(proc_cam_dir, exist_ok=True)
    annotated_path = os.path.join(proc_cam_dir, filename)

    if target_found:
        try:
            img = cv2.imread(image_path)
            for index, row in df.iterrows():
                cls = int(row['class'])
                if cls in TARGET_CLASSES:
                    x1, y1, x2, y2 = int(row['xmin']), int(row['ymin']), int(row['xmax']), int(row['ymax'])
                    name_str = str(row['name']).lower()
                    box_color = (0, 255, 0) if name_str == 'person' else (0, 0, 255)
                    label_bg_color = box_color
                    label_text_color = (255, 0, 0)

                    label_text = f"{row['name']} {row['confidence']:.2f}"
                    cv2.rectangle(img, (x1, y1), (x2, y2), box_color, 2)
                    t_size = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
                    c2 = x1 + t_size[0], y1 - t_size[1] - 3
                    cv2.rectangle(img, (x1, y1), c2, label_bg_color, -1, cv2.LINE_AA)
                    cv2.putText(img, label_text, (x1, y1 - 2), 0, 0.5, label_text_color, thickness=1, lineType=cv2.LINE_AA)

            cv2.imwrite(annotated_path, img)
            logger.info(f"Target detected! Saved annotated image to {annotated_path}")
        except Exception as e:
            logger.error(f"Failed to annotate: {e}")
            import shutil
            shutil.copy2(image_path, annotated_path)
    else:
        logger.info(f"No targets detected in {filename}. Copying original to processed dir.")
        import shutil
        shutil.copy2(image_path, annotated_path)

    cycle_id = extract_cycle_id(filename)
    total_targets = sum(detected_targets.values())

    return {
        'filename': filename,
        'target_count': total_targets,
        'max_conf': max_conf,
        'annotated_path': annotated_path,
        'summary_text': counts_str,
        'labels': sorted(detected_targets.keys()),
        'source': source,
        'camera_id': pure_cam_id,
        'event_id': cycle_id,
        'detections': detections
    }


async def process_and_notify(image_path: str, filename: str, receive_start: float, save_duration: float, source: str):
    """
    Perform inference and Add to Cycle Buffer.
    """
    logger.info(f"Processing {filename}...")

    inference_start = time.perf_counter()
    result_data = analyze_image_for_cycle(image_path, filename, source)
    inference_duration = time.perf_counter() - inference_start
    cycle_id = result_data['event_id']
    logger.info(f"Extracted Cycle ID: {cycle_id} for {filename}")

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
        if "X" in pure_cam_id:
            pure_cam_id = pure_cam_id.split("X", 1)[0]
            
        server_seq = get_or_increment_server_sequence(pure_cam_id, seq)
        # フォーマット: {カメラID}_{日時}_{シーケンス}_{インデックス}.jpg
        filename = f"{pure_cam_id}_{time_str}_{server_seq}_{idx}.jpg"
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

        source = "satos" if clean_original.startswith("satos_") else "pi" if clean_original.startswith("pi_") else "unknown"

        # Trigger background processing
        background_tasks.add_task(process_and_notify, file_path, filename, receive_start, save_duration, source)
        
        return {"status": "ok", "message": "Image received and processing started"}
    except Exception as e:
        logger.error(f"Failed to save image: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/upload_video")
async def upload_video(
    file: UploadFile = File(...),
    x_event_id: str = Header(None),
    x_camera_id: str = Header(None),
    x_sequence: str = Header(None),
    api_key: str = Depends(verify_api_token)
):
    if not x_camera_id or not x_sequence:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing camera metadata")

    pure_cam_id = get_camera_id(x_camera_id.strip())
    if "X" in pure_cam_id:
        pure_cam_id = pure_cam_id.split("X", 1)[0]
        
    safe_seq = re.sub(r"[^0-9A-Za-z_-]", "", x_sequence.strip()) or "001"
    server_seq = get_or_increment_server_sequence(pure_cam_id, safe_seq)
    
    suffix = os.path.splitext(file.filename or "")[1] or ".mov"
    filename = build_video_filename(pure_cam_id, server_seq, suffix)

    cam_dir = os.path.join(VIDEO_DIR, pure_cam_id)
    os.makedirs(cam_dir, exist_ok=True)
    file_path = os.path.join(cam_dir, filename)

    try:
        with open(file_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                buffer.write(content)

        event_id = x_event_id.strip() if x_event_id else extract_event_id_from_video_filename(filename)
        existing_metadata = load_event_metadata(pure_cam_id, event_id) or {
            "event_id": event_id,
            "camera_id": pure_cam_id,
            "source": "satos",
            "labels": [],
            "target_count": 0,
            "detected_images_count": 0,
            "max_conf": 0.0,
            "summary_text": "",
            "images": [],
            "cycle_time": "",
        }
        existing_metadata["has_video"] = True
        existing_metadata["updated_at"] = datetime.now().isoformat()
        save_event_metadata(pure_cam_id, event_id, existing_metadata)
        logger.info(f"Received video for event {event_id}: {file_path}")
        return {
            "status": "ok",
            "event_id": event_id,
            "filename": filename,
            "camera_id": pure_cam_id
        }
    except Exception as e:
        logger.error(f"Failed to save video upload: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/telemetry")
async def update_telemetry(payload: dict, api_key: str = Depends(verify_api_token)):
    cam_id = payload.get("camera_id")
    if not cam_id:
        raise HTTPException(status_code=400, detail="Missing camera_id")
    
    current_data = load_telemetry()
    pure_cam_id = get_camera_id(cam_id)
    if "X" in pure_cam_id:
        pure_cam_id = pure_cam_id.split("X", 1)[0]
    if pure_cam_id not in current_data:
        current_data[pure_cam_id] = {}
        
    for k, v in payload.items():
        if k not in ("camera_id", "acquired_at"):
            current_data[pure_cam_id][k] = v
            
    # Use acquired_at if provided by integration server, otherwise current server time
    acquired_at = payload.get("acquired_at")
    if acquired_at:
        current_data[pure_cam_id]["updated_at"] = acquired_at
    else:
        current_data[pure_cam_id]["updated_at"] = datetime.now().isoformat()
    
    save_telemetry(current_data)
    return {"status": "ok"}

@app.get("/api/telemetry")
async def get_telemetry(principal: dict = Depends(verify_credentials)):
    return {"status": "ok", "telemetry": load_telemetry()}

# --- Dataset Export APIs ---
def export_filter_data(
    start_date: str = None,
    end_date: str = None,
    camera: str = None,
    labels: str = None,
    include_empty: bool = True,
    min_conf: float = 0.0,
    max_conf: float = 1.0,
    principal: dict = None
):
    target_labels = [l.strip().lower() for l in labels.split(",")] if labels else []
    matched_images_data = []
    
    for root, dirs, files in os.walk(EVENT_METADATA_DIR):
        for f in files:
            if f.endswith(".json"):
                meta_path = os.path.join(root, f)
                try:
                    with open(meta_path, 'r', encoding='utf-8') as jf:
                        meta = json.load(jf)
                except Exception:
                    continue
                
                cam_id = meta.get("camera_id")
                if principal and principal["role"] == "user":
                    if cam_id not in principal.get("allowed_cameras", []):
                        continue
                
                if camera and camera != "all" and cam_id != camera:
                    continue
                
                cycle_time_str = meta.get("cycle_time", "")
                if cycle_time_str:
                    try:
                        dt = datetime.strptime(cycle_time_str, "%Y/%m/%d %H:%M:%S")
                        date_str = dt.strftime("%Y-%m-%d")
                        if start_date and date_str < start_date:
                            continue
                        if end_date and date_str > end_date:
                            continue
                    except:
                        pass
                
                image_detections = meta.get("detections", {})
                event_labels = meta.get("labels", [])
                
                for img_rel_path in meta.get("images", []):
                    img_filename = os.path.basename(img_rel_path)
                    dets = image_detections.get(img_filename, [])
                    
                    if not dets:
                        # 過去データ(BBなし)のフォールバック処理
                        has_target = False
                        if event_labels and event_labels != ['None'] and event_labels != "None":
                            for lbl in event_labels:
                                cat_str = str(lbl).lower()
                                cat_name = "animal"
                                if "person" in cat_str or cat_str == "1":
                                    cat_name = "person"
                                elif "vehicle" in cat_str or cat_str == "2":
                                    cat_name = "vehicle"
                                    
                                if not target_labels or "all" in target_labels or cat_name in target_labels:
                                    has_target = True
                                    break
                                    
                        if has_target:
                            matched_images_data.append((meta, img_filename, []))
                        elif include_empty:
                            matched_images_data.append((meta, img_filename, []))
                        continue
                        
                    filtered_dets = []
                    for d in dets:
                        cat_str = str(d.get("category", "")).lower()
                        cat_name = "animal"
                        if "person" in cat_str or cat_str == "1":
                            cat_name = "person"
                        elif "vehicle" in cat_str or cat_str == "2":
                            cat_name = "vehicle"
                            
                        if target_labels and "all" not in target_labels and cat_name not in target_labels:
                            continue
                            
                        conf = float(d.get("conf", 0.0))
                        if not (min_conf <= conf <= max_conf):
                            continue
                            
                        filtered_dets.append(d)
                        
                    if filtered_dets:
                        matched_images_data.append((meta, img_filename, filtered_dets))
                    elif include_empty:
                        matched_images_data.append((meta, img_filename, []))
                        
    matched_images_data.sort(key=lambda x: x[0].get("cycle_time", ""), reverse=True)
    return matched_images_data

@app.get("/api/export/preview")
async def export_preview(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    camera: Optional[str] = Query(None),
    labels: Optional[str] = Query(None),
    include_empty: str = Query("true"),
    min_conf: float = Query(0.0),
    max_conf: float = Query(1.0),
    principal: dict = Depends(verify_credentials)
):
    try:
        inc_empty = include_empty.lower() == "true"
        matched = export_filter_data(start, end, camera, labels, inc_empty, min_conf, max_conf, principal)
        return {"status": "ok", "total_images": len(matched)}
    except Exception as e:
        logger.error(f"Preview API Error: {e}")
        return {"status": "error", "message": str(e)}

def cleanup_temp_dir(path: str):
    try:
        import shutil
        shutil.rmtree(path)
    except Exception as e:
        logger.error(f"Failed to cleanup {path}: {e}")

@app.get("/api/export/download")
async def export_download(
    background_tasks: BackgroundTasks,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    camera: Optional[str] = Query(None),
    labels: Optional[str] = Query(None),
    include_empty: str = Query("true"),
    min_conf: float = Query(0.0),
    max_conf: float = Query(1.0),
    page: int = Query(1),
    principal: dict = Depends(verify_credentials)
):
    try:
        inc_empty = include_empty.lower() == "true"
        matched = export_filter_data(start, end, camera, labels, inc_empty, min_conf, max_conf, principal)
        
        limit = 1000
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        target_images = matched[start_idx:end_idx]
        
        if not target_images:
            raise HTTPException(status_code=404, detail="No data found for this page.")
            
        md_json = {
            "info": {
                "version": "1.0",
                "description": "Exported from WILD ANIMALS Server",
                "date_created": datetime.now().isoformat()
            },
            "detection_categories": {
                "0": "animal",
                "1": "person",
                "2": "vehicle"
            },
            "images": []
        }
        
        temp_dir = tempfile.mkdtemp()
        zip_filename = f"dataset_export_part{page}.zip"
        zip_path = os.path.join(temp_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for meta, img_filename, dets in target_images:
                cam_id = meta.get("camera_id")
                img_path = os.path.join(UPLOAD_DIR, cam_id, img_filename)
                if not os.path.exists(img_path):
                    img_path = os.path.join(PROCESSED_DIR, cam_id, img_filename)
                
                md_detections = []
                for d in dets:
                    cat = str(d.get("category", "0"))
                    md_detections.append({
                        "category": cat,
                        "conf": d.get("conf"),
                        "bbox": d.get("bbox")
                    })
                    
                md_json["images"].append({
                    "file": f"images/{img_filename}",
                    "location": cam_id,
                    "datetime": meta.get("cycle_time"),
                    "detections": md_detections
                })
                
                if os.path.exists(img_path):
                    zipf.write(img_path, arcname=f"images/{img_filename}")
            
            json_str = json.dumps(md_json, indent=2)
            zipf.writestr("md_results.json", json_str)
            
        background_tasks.add_task(cleanup_temp_dir, temp_dir)
        return FileResponse(zip_path, media_type="application/zip", filename=zip_filename)
        
    except Exception as e:
        logger.error(f"Download API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/statistics")
async def get_statistics(principal: dict = Depends(verify_credentials)):
    data = []
    try:
        if os.path.exists("statistics.csv"):
            with open("statistics.csv", "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    data.append(row)
    except Exception as e:
        logger.error(f"Error reading statistics.csv: {e}")
    return {"status": "ok", "data": data}

@app.get("/statistics", response_class=HTMLResponse)
async def statistics_page(request: Request, credentials: HTTPBasicCredentials = Depends(security)):
    principal = get_optional_principal(request, credentials)
    if not principal:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if principal.get("role") != "admin":
        return RedirectResponse(url="/gallery", status_code=status.HTTP_303_SEE_OTHER)
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Statistics Dashboard</title>
        {THEME_TOGGLE_SCRIPT}
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
            :root {{
                --bg-main: #f8fafc;
                --text-main: #1e293b;
                --text-sub: #64748b;
                --card-bg: #ffffff;
                --card-border: #e2e8f0;
                --accent: #3b82f6;
            }}
            [data-theme="dark"] {{
                --bg-main: #0f172a;
                --text-main: #f8fafc;
                --text-sub: #94a3b8;
                --card-bg: #1e293b;
                --card-border: #334155;
                --accent: #60a5fa;
            }}
            body {{
                font-family: 'Inter', sans-serif;
                margin: 0;
                padding: 20px;
                background-color: var(--bg-main);
                color: var(--text-main);
                transition: all 0.3s ease;
            }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }}
            h1 {{ margin: 0; font-size: 2rem; font-weight: 700; }}
            .btn-back {{
                display: inline-flex; align-items: center; gap: 8px;
                padding: 8px 16px; background: var(--card-bg); color: var(--text-main);
                border: 1px solid var(--card-border); border-radius: 8px; text-decoration: none;
                font-weight: 500; transition: all 0.2s;
            }}
            .btn-back:hover {{ background: var(--card-border); }}
            
            .overview-grid {{
                display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 30px;
            }}
            .kpi-card {{
                background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 16px;
                padding: 24px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            }}
            .kpi-title {{ font-size: 0.9rem; color: var(--text-sub); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }}
            .kpi-value {{ font-size: 2.5rem; font-weight: 700; color: var(--accent); margin: 0; }}
            
            .charts-grid {{
                display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 30px;
            }}
            .chart-card {{
                background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 16px;
                padding: 24px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            }}
            .chart-card.full-width {{ grid-column: 1 / -1; }}
            .chart-title {{ margin-top: 0; margin-bottom: 20px; font-size: 1.2rem; font-weight: 600; }}
            
            @media (max-width: 768px) {{
                .charts-grid {{ grid-template-columns: 1fr; }}
            }}
            .btn-export {{ background: #38a169; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: 0.2s; }}
            .btn-export:hover {{ background: #2f855a; }}
            .modal-overlay {{ display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 1000; align-items: center; justify-content: center; }}
            .modal-content {{ background: var(--card-bg); padding: 30px; border-radius: 12px; width: 90%; max-width: 500px; color: var(--text-main); }}
            .modal-content h2 {{ margin-top: 0; color: var(--text-main); font-size: 1.5rem; }}
            .form-group {{ margin-bottom: 15px; }}
            .form-group label {{ display: block; margin-bottom: 5px; font-weight: 500; font-size: 0.9rem; }}
            .form-group input, .form-group select {{ width: 100%; padding: 8px; border: 1px solid var(--card-border); border-radius: 6px; box-sizing: border-box; background: var(--bg-main); color: var(--text-main); }}
            .form-row {{ display: flex; gap: 10px; }}
            .checkbox-group {{ display: flex; flex-wrap: wrap; gap: 10px; }}
            .checkbox-item {{ display: flex; align-items: center; gap: 5px; font-size: 0.9rem; cursor: pointer; }}
            #export-preview-msg {{ margin: 15px 0; padding: 10px; border-radius: 6px; background: #ebf8ff; color: #2b6cb0; border: 1px solid #bee3f8; display: none; font-size: 0.95rem; }}
            #export-actions {{ display: flex; flex-direction: column; gap: 10px; margin-top: 20px; }}
            .btn-check {{ background: #3182ce; color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer; font-weight: 500; }}
            .btn-check:hover {{ background: #2b6cb0; }}
            .btn-dl {{ background: #38a169; color: white; border: none; padding: 10px; border-radius: 6px; cursor: pointer; font-weight: bold; text-align: center; text-decoration: none; }}
            .btn-cancel {{ background: #a0aec0; color: white; border: none; padding: 10px; border-radius: 6px; cursor: pointer; font-weight: 500; }}
            [data-theme="dark"] .modal-overlay {{ background: rgba(0,0,0,0.7); }}
            [data-theme="dark"] #export-preview-msg {{ background: #2a4365; color: #90cdf4; border-color: #2c5282; }}
        </style>
    </head>
    <body>
        {THEME_TOGGLE_UI}
        <div class="container">
            <div class="header">
                <h1>Statistics Dashboard</h1>
                <div style="display: flex; gap: 10px;">
                    <button onclick="openExportModal()" class="btn-export">📦 Export Dataset</button>
                    <a href="/gallery" class="btn-back"><span>←</span> Back to Gallery</a>
                </div>
            </div>
            
            <div class="overview-grid">
                <div class="kpi-card">
                    <div class="kpi-title">Total Detections</div>
                    <div class="kpi-value" id="kpi-total">0</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-title">Active Cameras</div>
                    <div class="kpi-value" id="kpi-cameras">0</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-title">Most Detected Animal</div>
                    <div class="kpi-value" id="kpi-top-animal" style="font-size: 1.8rem;">-</div>
                </div>
            </div>
            
            <div class="charts-grid">
                <div class="chart-card full-width">
                    <h2 class="chart-title">Daily Trends & Temperature</h2>
                    <canvas id="trendChart" height="80"></canvas>
                </div>
                
                <div class="chart-card">
                    <h2 class="chart-title">Activity by Hour</h2>
                    <canvas id="hourChart"></canvas>
                </div>
                
                <div class="chart-card">
                    <h2 class="chart-title">Distribution by Animal</h2>
                    <canvas id="animalChart"></canvas>
                </div>
            </div>
        </div>
        
        <!-- Export Modal -->
        <div id="exportModal" class="modal-overlay">
            <div class="modal-content">
                <h2>Export Dataset (MD Format)</h2>
                <div class="form-group">
                    <label>Camera</label>
                    <select id="exp-camera">
                        <option value="all">All Cameras</option>
                    </select>
                </div>
                <div class="form-row">
                    <div class="form-group" style="flex:1;">
                        <label>Start Date</label>
                        <input type="date" id="exp-start">
                    </div>
                    <div class="form-group" style="flex:1;">
                        <label>End Date</label>
                        <input type="date" id="exp-end">
                    </div>
                </div>
                <div class="form-group">
                    <label>Labels</label>
                    <div class="checkbox-group">
                        <label class="checkbox-item"><input type="checkbox" class="exp-label" value="animal" checked> Animal</label>
                        <label class="checkbox-item"><input type="checkbox" class="exp-label" value="person" checked> Person</label>
                        <label class="checkbox-item"><input type="checkbox" class="exp-label" value="vehicle" checked> Vehicle</label>
                        <label class="checkbox-item"><input type="checkbox" id="exp-empty" checked> Empty / No Detection</label>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group" style="flex:1;">
                        <label>Min Confidence</label>
                        <input type="number" id="exp-min-conf" min="0" max="1" step="0.1" value="0.0">
                    </div>
                    <div class="form-group" style="flex:1;">
                        <label>Max Confidence</label>
                        <input type="number" id="exp-max-conf" min="0" max="1" step="0.1" value="1.0">
                    </div>
                </div>
                
                <div id="export-preview-msg"></div>
                
                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px;">
                    <button class="btn-check" onclick="checkExportSize()">Check Data Size</button>
                    <button class="btn-cancel" onclick="closeExportModal()">Cancel</button>
                </div>
                
                <div id="export-actions"></div>
            </div>
        </div>

        <script>
            const getChartColors = () => {{
                const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
                return {{
                    text: isDark ? '#f8fafc' : '#1e293b',
                    grid: isDark ? '#334155' : '#e2e8f0',
                    primary: '#3b82f6',
                    secondary: '#10b981',
                    colors: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4']
                }};
            }};

            Chart.defaults.color = getChartColors().text;
            Chart.defaults.font.family = "'Inter', sans-serif";

            let charts = [];

            const observer = new MutationObserver((mutations) => {{
                mutations.forEach((mutation) => {{
                    if (mutation.attributeName === 'data-theme') {{
                        const colors = getChartColors();
                        Chart.defaults.color = colors.text;
                        charts.forEach(c => {{
                            if(c.options.scales && c.options.scales.x) {{
                                c.options.scales.x.grid.color = colors.grid;
                                c.options.scales.x.ticks.color = colors.text;
                            }}
                            if(c.options.scales && c.options.scales.y) {{
                                c.options.scales.y.grid.color = colors.grid;
                                c.options.scales.y.ticks.color = colors.text;
                            }}
                            c.update();
                        }});
                    }}
                }});
            }});
            observer.observe(document.documentElement, {{ attributes: true }});

            async function initDashboard() {{
                try {{
                    const res = await fetch('/api/statistics');
                    const json = await res.json();
                    if(json.status !== 'ok') return;
                    
                    const data = json.data;
                    if(data.length === 0) return;
                    
                    let totalDetections = 0;
                    const cameras = new Set();
                    const animalCounts = {{}};
                    const dailyData = {{}};
                    const hourlyData = new Array(24).fill(0);
                    
                    data.forEach(row => {{
                        cameras.add(row.camera_id);
                        const count = parseInt(row.target_count, 10) || 0;
                        totalDetections += count;
                        
                        if(row.labels && row.labels !== 'None') {{
                            row.labels.split('|').forEach(l => {{
                                animalCounts[l] = (animalCounts[l] || 0) + 1;
                            }});
                        }}
                        
                        const timeParts = row.timestamp.split(' ');
                        if(timeParts.length === 2) {{
                            const date = timeParts[0];
                            const hour = parseInt(timeParts[1].split(':')[0], 10);
                            
                            if(!isNaN(hour)) hourlyData[hour] += count;
                            
                            if(!dailyData[date]) dailyData[date] = {{ count: 0, tempSum: 0, tempCount: 0 }};
                            dailyData[date].count += count;
                            
                            const temp = parseFloat(row.temperature);
                            if(!isNaN(temp)) {{
                                dailyData[date].tempSum += temp;
                                dailyData[date].tempCount++;
                            }}
                        }}
                    }});
                    
                    document.getElementById('kpi-total').textContent = totalDetections;
                    document.getElementById('kpi-cameras').textContent = cameras.size;
                    
                    let topAnimal = '-';
                    let topCount = 0;
                    for(const [animal, count] of Object.entries(animalCounts)) {{
                        if(count > topCount) {{ topCount = count; topAnimal = animal; }}
                    }}
                    document.getElementById('kpi-top-animal').textContent = topAnimal;
                    
                    const colors = getChartColors();
                    
                    const sortedDates = Object.keys(dailyData).sort();
                    const dailyCounts = sortedDates.map(d => dailyData[d].count);
                    const dailyTemps = sortedDates.map(d => dailyData[d].tempCount > 0 ? (dailyData[d].tempSum / dailyData[d].tempCount).toFixed(1) : null);
                    
                    const ctxTrend = document.getElementById('trendChart').getContext('2d');
                    charts.push(new Chart(ctxTrend, {{
                        type: 'bar',
                        data: {{
                            labels: sortedDates,
                            datasets: [
                                {{
                                    label: 'Detections',
                                    data: dailyCounts,
                                    backgroundColor: colors.primary,
                                    borderRadius: 4,
                                    order: 2
                                }},
                                {{
                                    label: 'Avg Temperature (°C)',
                                    data: dailyTemps,
                                    type: 'line',
                                    borderColor: colors.secondary,
                                    backgroundColor: colors.secondary,
                                    borderWidth: 2,
                                    tension: 0.3,
                                    yAxisID: 'y1',
                                    order: 1
                                }}
                            ]
                        }},
                        options: {{
                            responsive: true,
                            scales: {{
                                x: {{ grid: {{ color: colors.grid }} }},
                                y: {{ type: 'linear', display: true, position: 'left', title: {{ display: true, text: 'Count' }}, grid: {{ color: colors.grid }}, beginAtZero: true }},
                                y1: {{ type: 'linear', display: true, position: 'right', title: {{ display: true, text: 'Temp (°C)' }}, grid: {{ drawOnChartArea: false }} }}
                            }}
                        }}
                    }}));
                    
                    const ctxHour = document.getElementById('hourChart').getContext('2d');
                    charts.push(new Chart(ctxHour, {{
                        type: 'bar',
                        data: {{
                            labels: Array.from({{length: 24}}, (_, i) => `${{i}}:00`),
                            datasets: [{{
                                label: 'Activity by Hour',
                                data: hourlyData,
                                backgroundColor: colors.secondary,
                                borderRadius: 4
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            scales: {{
                                x: {{ grid: {{ color: colors.grid }} }},
                                y: {{ beginAtZero: true, grid: {{ color: colors.grid }} }}
                            }}
                        }}
                    }}));
                    
                    const animalLabels = Object.keys(animalCounts);
                    const animalData = Object.values(animalCounts);
                    
                    const ctxAnimal = document.getElementById('animalChart').getContext('2d');
                    charts.push(new Chart(ctxAnimal, {{
                        type: 'doughnut',
                        data: {{
                            labels: animalLabels,
                            datasets: [{{
                                data: animalData,
                                backgroundColor: colors.colors.slice(0, animalLabels.length),
                                borderWidth: 0
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            cutout: '60%',
                            plugins: {{
                                legend: {{ position: 'right' }}
                            }}
                        }}
                    }}));
                    
                }} catch (e) {{
                    console.error("Failed to load statistics data", e);
                }}
            }}
            
            initDashboard();

            // --- Export Modal Logic ---
            function openExportModal() {{
                const camSelect = document.getElementById('exp-camera');
                if (camSelect.options.length === 1) {{
                    fetch('/api/config/available_cameras')
                        .then(r => r.json())
                        .then(d => {{
                            if(d.status==='ok') {{
                                d.cameras.forEach(c => {{
                                    const opt = document.createElement('option');
                                    opt.value = c; opt.innerText = c;
                                    camSelect.appendChild(opt);
                                }});
                            }}
                        }});
                }}
                document.getElementById('exportModal').style.display = 'flex';
                document.getElementById('export-preview-msg').style.display = 'none';
                document.getElementById('export-actions').innerHTML = '';
            }}
            
            function closeExportModal() {{
                document.getElementById('exportModal').style.display = 'none';
            }}
            
            function buildExportQuery() {{
                const cam = document.getElementById('exp-camera').value;
                const start = document.getElementById('exp-start').value;
                const end = document.getElementById('exp-end').value;
                const empty = document.getElementById('exp-empty').checked;
                const minC = document.getElementById('exp-min-conf').value;
                const maxC = document.getElementById('exp-max-conf').value;
                
                const labelBoxes = document.querySelectorAll('.exp-label:checked');
                const labels = Array.from(labelBoxes).map(b => b.value).join(',');
                
                let q = `include_empty=${{empty}}&min_conf=${{minC}}&max_conf=${{maxC}}`;
                if(cam !== 'all') q += `&camera=${{cam}}`;
                if(start) q += `&start=${{start}}`;
                if(end) q += `&end=${{end}}`;
                if(labels) q += `&labels=${{labels}}`;
                return q;
            }}

            async function checkExportSize() {{
                const btn = document.querySelector('.btn-check');
                btn.innerText = 'Checking...';
                
                const q = buildExportQuery();
                try {{
                    const res = await fetch(`/api/export/preview?${{q}}`);
                    const json = await res.json();
                    
                    const msgDiv = document.getElementById('export-preview-msg');
                    const actionsDiv = document.getElementById('export-actions');
                    msgDiv.style.display = 'block';
                    actionsDiv.innerHTML = '';
                    
                    if (json.status !== 'ok') {{
                        msgDiv.innerHTML = `⚠️ Error: ${{json.message}}`;
                        return;
                    }}
                    
                    const total = json.total_images;
                    const limit = 1000;
                    
                    if (total === 0) {{
                        msgDiv.innerHTML = `No data found matching these conditions.`;
                    }} else if (total <= limit) {{
                        msgDiv.innerHTML = `✅ <b>${{total}}</b> images found. Ready to download.`;
                        actionsDiv.innerHTML = `<a href="/api/export/download?${{q}}&page=1" class="btn-dl">Download ZIP</a>`;
                    }} else {{
                        msgDiv.innerHTML = `⚠️ <b>${{total}} images found.</b><br>This exceeds the single download limit (${{limit}}).<br>Please refine your conditions or download in parts below.`;
                        const parts = Math.ceil(total / limit);
                        let html = '';
                        for(let i=1; i<=parts; i++) {{
                            const pStart = (i-1)*limit + 1;
                            const pEnd = Math.min(i*limit, total);
                            html += `<a href="/api/export/download?${{q}}&page=${{i}}" class="btn-dl" style="background:#3182ce;">Download Part ${{i}} (${{pStart}} - ${{pEnd}})</a>`;
                        }}
                        actionsDiv.innerHTML = html;
                    }}
                }} catch(e) {{
                    alert('Error checking size');
                }} finally {{
                    btn.innerText = 'Check Data Size';
                }}
            }}
        </script>
    </body>
    </html>
    """
    return html_content

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


@app.get("/videos/{video_path:path}")
async def get_video_file(video_path: str, principal: dict = Depends(verify_credentials)):
    verify_camera_access(principal, video_path)
    full_path = resolve_image_path(VIDEO_DIR, video_path)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    return FileResponse(full_path, media_type="video/quicktime")

@app.delete("/api/cycle/{camera_id}/{cycle_id}")
async def delete_cycle(camera_id: str, cycle_id: str, principal: dict = Depends(verify_credentials)):
    if principal.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
        
    try:
        # 1. Physical files deletion
        up_dir = os.path.join(UPLOAD_DIR, camera_id)
        if os.path.exists(up_dir):
            for f in os.listdir(up_dir):
                if f"_{cycle_id}_" in f:
                    os.remove(os.path.join(up_dir, f))
                    
        proc_dir = os.path.join(PROCESSED_DIR, camera_id)
        if os.path.exists(proc_dir):
            for f in os.listdir(proc_dir):
                if f"_{cycle_id}_" in f:
                    os.remove(os.path.join(proc_dir, f))
                    
        vid_dir = os.path.join(VIDEO_DIR, camera_id)
        if os.path.exists(vid_dir):
            for f in os.listdir(vid_dir):
                if f.endswith(f"_{cycle_id}.mp4"):
                    os.remove(os.path.join(vid_dir, f))
                    
        meta_path = get_event_metadata_path(camera_id, cycle_id)
        if os.path.exists(meta_path):
            os.remove(meta_path)
            
        # 2. Remove from statistics.csv
        stat_csv = os.path.join(EVENT_METADATA_DIR, "statistics.csv")
        if os.path.exists(stat_csv):
            with open(stat_csv, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if lines:
                new_lines = [lines[0]]
                header = lines[0].strip().split(",")
                cycle_id_idx = header.index("cycle_id") if "cycle_id" in header else -1
                cam_idx = header.index("camera_id") if "camera_id" in header else 1
                
                for line in lines[1:]:
                    parts = line.strip().split(",")
                    if len(parts) > max(cam_idx, cycle_id_idx):
                        if cycle_id_idx >= 0 and parts[cycle_id_idx] == cycle_id and parts[cam_idx] == camera_id:
                            continue
                    new_lines.append(line)
                    
                with open(stat_csv, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                    
        # 3. Revert server_sequence.json if it's the latest cycle
        with _seq_lock_sync:
            seq_data = load_server_sequence()
            if camera_id in seq_data:
                cam_data = seq_data[camera_id]
                try:
                    if int(cycle_id) == cam_data.get("current_server_seq", -1):
                        cam_data["current_server_seq"] -= 1
                        cam_data["last_edge_event_id"] = ""
                        cam_data["last_update_time"] = 0.0
                        seq_data[camera_id] = cam_data
                        save_server_sequence(seq_data)
                        logger.info(f"Reverted server sequence for {camera_id} due to cycle deletion.")
                except ValueError:
                    pass
                    
        return {"status": "ok", "message": "Cycle deleted successfully"}
        
    except Exception as e:
        logger.error(f"Error deleting cycle {camera_id}/{cycle_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/images")
async def get_images(
    detection: str = "all",
    label: str = "all",
    video: str = "all",
    source: str = "all",
    min_conf: float | None = None,
    principal: dict = Depends(verify_credentials)
):
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
        filters = {
            "detection": detection,
            "label": label,
            "video": video,
            "source": source,
            "min_conf": min_conf,
        }
        metadata_map = build_event_metadata_map(PROCESSED_DIR, proc_files)
        proc_files = [path for path in proc_files if file_matches_filters(path, metadata_map, filters)]
        raw_files = [path for path in raw_files if file_matches_filters(path, metadata_map, filters)]
        
        return {
            "status": "ok",
            "raw": raw_files,
            "processed": proc_files,
            "metadata": metadata_map,
            "filters": filters,
            "viewer": {
                "username": principal.get("username"),
                "role": principal.get("role"),
                "allowed_cameras": principal.get("allowed_cameras") or []
            }
        }
    except Exception as e:
        logger.error(f"Failed to get image list: {e}")
        return {"status": "error", "message": str(e)}
@app.get("/event/{camera_id}/{event_id}", response_class=HTMLResponse)
async def event_detail_by_cycle(
    camera_id: str,
    event_id: str,
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security)
):
    principal = get_optional_principal(request, credentials)
    if not principal:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    verify_camera_access(principal, f"{camera_id}/dummy.jpg")

    event_metadata = load_event_metadata(camera_id, event_id) or {}
    related_processed = get_related_processed_images(camera_id, event_id)
    related_raw = get_related_raw_images(camera_id, event_id)
    related_videos = get_video_relpaths_for_event(camera_id, event_id)
    primary_video = related_videos[0] if related_videos else ""

    cycle_time = event_metadata.get("cycle_time", "")
    if not cycle_time and len(event_id) == 14 and event_id.isdigit():
        cycle_time = f"{event_id[:4]}/{event_id[4:6]}/{event_id[6:8]} {event_id[8:10]}:{event_id[10:12]}:{event_id[12:14]}"

    image_summaries = event_metadata.get("image_summaries", {})
    
    def build_thumbs_html(image_list, source):
        if not image_list:
            return '<div class="empty-video" style="min-height:140px;">No images available.</div>'
        html = ""
        for rel in image_list:
            file_label = os.path.basename(rel)
            summary = image_summaries.get(file_label, "")
            summary_text = f"Detections: {summary}" if summary and summary != "No targets" else "Detections: none"
            summary_color = "#c53030" if summary and summary != "No targets" else "#4a5568"
            
            html += f"""
                <div class="thumb" onclick="openOverlay('/images/{source}/{rel}')" style="cursor:zoom-in;">
                    <img src="/images/{source}/{rel}" loading="lazy" alt="{file_label}">
                    <span>{file_label}</span>
                    <span style="font-size:0.8rem; color:{summary_color}; margin-top:4px;">{summary_text}</span>
                </div>
            """
        return html

    processed_thumbs_html = build_thumbs_html(related_processed, "processed")
    raw_thumbs_html = build_thumbs_html(related_raw, "raw")

    video_block = """
        <div class="empty-video">No related video yet.</div>
    """
    if primary_video:
        video_block = f"""
            <video controls preload="metadata" class="video-player">
                <source src="/videos/{primary_video}">
                Your browser cannot play this video.
            </video>
            <div style="text-align:center; margin-top:10px;">
                <a class="download-link" href="/videos/{primary_video}" target="_blank">Download video</a>
            </div>
        """

    labels = event_metadata.get("labels", [])
    labels_text = ", ".join(labels) if labels else "none"
    detected_count = event_metadata.get("detected_images_count", 0)

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Event Details: {event_id}</title>
        {THEME_TOGGLE_SCRIPT}
        <style>
            body {{ font-family: 'Inter', 'Segoe UI', sans-serif; margin: 0; padding: 24px; background: #f3f8f4; color: #22332b; }}
            .shell {{ max-width: 1280px; margin: 0 auto; }}
            .topbar {{ display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:20px; }}
            .back-link, .download-link {{ display:inline-flex; align-items:center; justify-content:center; padding:10px 16px; border-radius:999px; text-decoration:none; background:#ffffff; color:#2d4a3a; box-shadow:0 2px 8px rgba(0,0,0,0.06); font-weight:600; transition:all 0.2s; }}
            .back-link:hover, .download-link:hover {{ background:#e2e8f0; }}
            .panel {{ background:#ffffff; border-radius:20px; padding:20px; box-shadow:0 12px 30px rgba(34,51,43,0.06); margin-bottom:24px; }}
            .panel h2 {{ margin:0 0 14px 0; font-size:1.3rem; color:#21543b; border-bottom:2px solid #e2efe5; padding-bottom:8px; }}
            .meta {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-bottom:20px; }}
            .meta-card {{ background:#ffffff; border-radius:16px; padding:14px 16px; box-shadow:0 4px 15px rgba(34,51,43,0.04); border:1px solid #edf2f7; }}
            .meta-label {{ display:block; font-size:0.82rem; color:#6b7f74; margin-bottom:6px; }}
            .meta-value {{ font-weight:600; word-break:break-word; font-size:1.05rem; }}
            .grid-container {{ display:grid; grid-template-columns: 1fr 1fr; gap:24px; }}
            @media(max-width:900px) {{ .grid-container {{ grid-template-columns: 1fr; }} }}
            .thumbs {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:14px; margin-top:16px; }}
            .thumb {{ text-decoration:none; color:inherit; background:#ffffff; border-radius:14px; padding:10px; box-shadow:0 4px 15px rgba(34,51,43,0.04); border:1px solid #edf2f7; transition:all 0.2s; display:flex; flex-direction:column; align-items:center; }}
            .thumb:hover {{ transform:translateY(-3px); box-shadow:0 8px 25px rgba(47,133,90,0.12); border-color:#2f855a; }}
            .thumb img {{ width:100%; height:160px; object-fit:contain; border-radius:10px; display:block; background:#f8fbf8; margin-bottom:8px; }}
            .thumb span {{ display:block; font-size:0.85rem; color:#52645a; word-break:break-all; text-align:center; font-weight:600; }}
            .video-player {{ width:100%; border-radius:16px; background:#000; min-height:320px; }}
            .empty-video {{ min-height:200px; border-radius:16px; display:flex; align-items:center; justify-content:center; background:#f6faf7; color:#6b7f74; border:1px dashed #cfe0d5; }}
            
            /* Overlay */
            .overlay {{ display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); z-index:9999; justify-content:center; align-items:center; cursor:zoom-out; }}
            .overlay.active {{ display:flex; }}
            .overlay img {{ max-width:95%; max-height:95%; border-radius:12px; box-shadow:0 12px 40px rgba(0,0,0,0.3); }}
            
            [data-theme="dark"] body {{ background: #121915; color: #e2e8f0; }}
            [data-theme="dark"] .back-link, [data-theme="dark"] .download-link {{ background: #1e2923; color: #a5d2b7; box-shadow: 0 2px 8px rgba(0,0,0,0.4); border: 1px solid #2d3a33; }}
            [data-theme="dark"] .back-link:hover, [data-theme="dark"] .download-link:hover {{ background: #2d3a33; }}
            [data-theme="dark"] .panel {{ background: #1e2923; box-shadow: 0 12px 30px rgba(0,0,0,0.2); }}
            [data-theme="dark"] .panel h2 {{ color: #86c4a0; border-bottom-color: #2d3a33; }}
            [data-theme="dark"] .meta-card {{ background: #1e2923; box-shadow: 0 4px 15px rgba(0,0,0,0.1); border-color: #2d3a33; }}
            [data-theme="dark"] .meta-label {{ color: #8a9c92; }}
            [data-theme="dark"] .meta-value {{ color: #e2e8f0; }}
            [data-theme="dark"] .thumb {{ background: #1e2923; border-color: #2d3a33; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
            [data-theme="dark"] .thumb:hover {{ border-color: #48bb78; box-shadow: 0 8px 25px rgba(72,187,120,0.15); }}
            [data-theme="dark"] .thumb img {{ background: #121915; border: none; }}
            [data-theme="dark"] .thumb span {{ color: #cbd5e0; }}
            [data-theme="dark"] .empty-video {{ background: #121915; color: #8a9c92; border-color: #2d3a33; }}
        </style>
    </head>
    <body>
        {THEME_TOGGLE_UI}
        <div class="shell">
            <div class="topbar">
                <a class="back-link" href="/gallery">← Back to Gallery</a>
            </div>
            
            <div class="meta">
                <div class="meta-card"><span class="meta-label">Camera ID</span><span class="meta-value">{camera_id}</span></div>
                <div class="meta-card"><span class="meta-label">Event ID</span><span class="meta-value">{event_id}</span></div>
                <div class="meta-card"><span class="meta-label">Detected At</span><span class="meta-value">{cycle_time or '-'}</span></div>
                <div class="meta-card"><span class="meta-label">Detected Labels</span><span class="meta-value">{labels_text}</span></div>
                <div class="meta-card"><span class="meta-label">Detected Images</span><span class="meta-value">{detected_count}</span></div>
            </div>
            
            <section class="panel">
                <h2>Event Video</h2>
                {video_block}
            </section>
            
            <div class="grid-container">
                <section class="panel">
                    <h2>Processed Images (With Box)</h2>
                    <div class="thumbs">{processed_thumbs_html}</div>
                </section>
                <section class="panel">
                    <h2>Raw Images (No Box)</h2>
                    <div class="thumbs">{raw_thumbs_html}</div>
                </section>
            </div>
        </div>
        
        <div id="imageOverlay" class="overlay" onclick="closeOverlay()">
            <img id="overlayImage" src="" alt="Expanded Image">
        </div>
        <script>
            function openOverlay(src) {{
                document.getElementById('overlayImage').src = src;
                document.getElementById('imageOverlay').classList.add('active');
            }}
            function closeOverlay() {{
                document.getElementById('imageOverlay').classList.remove('active');
            }}
        </script>
    </body>
    </html>
    """
    return html_content


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


@app.get("/api/config/available_cameras")
async def get_available_cameras(admin: dict = Depends(verify_admin)):
    return {"camera_ids": get_available_camera_ids()}


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


@app.get("/")
async def root():
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    session_principal = get_principal_from_session(request)
    if session_principal:
        return RedirectResponse(url="/gallery", status_code=status.HTTP_303_SEE_OTHER)

    return """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Login</title>
        """ + THEME_TOGGLE_SCRIPT + """
        <style>
            body { font-family: 'Inter', 'Segoe UI', sans-serif; margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #eef7f1 0%, #d8efe3 100%); color: #234034; }
            .card { width: min(420px, 92vw); background: rgba(255,255,255,0.92); border: 1px solid rgba(255,255,255,0.7); border-radius: 20px; padding: 32px; box-shadow: 0 20px 40px rgba(35, 64, 52, 0.08); }
            h1 { margin: 0 0 8px 0; font-size: 2rem; text-align: center; }
            p { margin: 0 0 24px 0; text-align: center; color: #4a6a5b; line-height: 1.6; }
            label { display: block; margin-bottom: 8px; font-weight: 600; color: #315745; }
            input { width: 100%; box-sizing: border-box; padding: 12px 14px; border-radius: 12px; border: 1px solid #cfe0d6; background: #fbfdfb; margin-bottom: 18px; font: inherit; }
            button { width: 100%; padding: 12px 16px; border: none; border-radius: 12px; background: #2f855a; color: #fff; font: inherit; font-weight: 600; cursor: pointer; }
            button:hover { background: #276749; }
            
            [data-theme="dark"] body { background: linear-gradient(135deg, #121915 0%, #1c2b22 100%); color: #e2e8f0; }
            [data-theme="dark"] .card { background: rgba(30,41,35,0.92); border-color: rgba(255,255,255,0.1); box-shadow: 0 20px 40px rgba(0,0,0,0.3); }
            [data-theme="dark"] p { color: #a0b2aa; }
            [data-theme="dark"] label { color: #cbd5e0; }
            [data-theme="dark"] input { background: #121915; border-color: #2d3a33; color: #fff; }
            [data-theme="dark"] button { background: #38a169; }
            [data-theme="dark"] button:hover { background: #2f855a; }
        </style>
    </head>
    <body>
        """ + THEME_TOGGLE_UI + """
        <form class="card" method="post" action="/login">
            <h1>Wild Animals Login</h1>
            <div style="text-align:center; margin: 0 0 12px 0;">""" + get_env_badge() + """</div>
            <p>管理者または閲覧ユーザとしてログインしてください。</p>
            <label for="username">User Name</label>
            <input id="username" name="username" type="text" autocomplete="username" required>
            <label for="password">Password</label>
            <input id="password" name="password" type="password" autocomplete="current-password" required>
            <button type="submit">Login</button>
        </form>
    </body>
    </html>
    """


@app.post("/login")
async def login_submit(username: str = Form(...), password: str = Form(...)):
    principal = authenticate_user(username.strip(), password)
    if not principal:
        return HTMLResponse(
            """
            <html><body style="font-family: sans-serif; padding: 24px;">
            <p>ログインに失敗しました。ユーザ名またはパスワードを確認してください。</p>
            <p><a href="/login">ログイン画面へ戻る</a></p>
            </body></html>
            """,
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    session_token = create_session(principal)
    response = RedirectResponse(url="/gallery", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        samesite="lax"
    )
    return response


@app.get("/logout")
async def logout(request: Request):
    clear_session(request)
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, credentials: HTTPBasicCredentials = Depends(security)):
    admin = get_optional_principal(request, credentials)
    if not admin:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if admin.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    html_content = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>System Admin & Settings</title>
        """ + THEME_TOGGLE_SCRIPT + """
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

            .inline-edit-input { width: 100%; min-width: 0; max-width: 100%; padding: 6px 12px; border: 1px solid #cbd5e0; border-radius: 8px; font-family: 'Inter', sans-serif; font-size: 0.95rem; font-weight: 500; color: #4338ca; background: rgba(255,255,255,0.9); transition: all 0.2s; box-sizing: border-box; }
            .inline-edit-input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.2); }
            .camera-checkbox-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; margin-top: 10px; width: 100%; }
            .camera-checkbox-item { display:flex; align-items:center; gap:8px; min-width: 0; padding:8px 10px; border-radius:10px; background: rgba(255,255,255,0.65); border: 1px solid rgba(0,0,0,0.06); font-size: 0.9rem; }
            .camera-checkbox-item span { min-width: 0; overflow-wrap: anywhere; }
            .camera-checkbox-item input { width:auto; margin:0; }
            .subtle-text { color: var(--text-sub); font-size: 0.85rem; margin-top: 8px; }
            .page-actions { display:flex; justify-content:center; gap:12px; margin: 0 0 24px 0; flex-wrap: wrap; }
            .btn-secondary { background: #ffffff; color: #334155; box-shadow: 0 4px 15px rgba(148, 163, 184, 0.25); }
            .btn-secondary:hover { background: #f8fafc; }
            .user-access-form { display: grid; grid-template-columns: minmax(180px, 1.1fr) minmax(160px, 0.9fr) minmax(200px, 1.2fr) auto; gap: 15px; align-items: end; margin-bottom: 16px; }
            .user-access-form .btn { white-space: nowrap; }
            .compact-camera-input { max-width: 280px; }
            .collapsible-block { margin-top: 12px; border: 1px solid rgba(0,0,0,0.06); border-radius: 14px; background: rgba(255,255,255,0.35); overflow: hidden; }
            .collapsible-block summary { cursor: pointer; list-style: none; padding: 12px 14px; font-weight: 600; color: #334155; display: flex; align-items: center; justify-content: space-between; }
            .collapsible-block summary::-webkit-details-marker { display: none; }
            .collapsible-block summary::after { content: '▾'; font-size: 0.95rem; color: #64748b; transition: transform 0.2s ease; }
            .collapsible-block[open] summary::after { transform: rotate(180deg); }
            .collapsible-content { padding: 0 14px 14px 14px; }
            .checkbox-panel { width: 100%; padding: 10px; border: 1px solid rgba(0,0,0,0.06); border-radius: 12px; background: rgba(255,255,255,0.45); box-sizing: border-box; }
            .user-access-list { display: flex; flex-direction: column; gap: 14px; margin-top: 20px; }
            .user-card { background: rgba(255,255,255,0.55); border: 1px solid rgba(255,255,255,0.7); border-radius: 16px; overflow: hidden; box-shadow: 0 6px 20px rgba(31, 38, 135, 0.04); }
            .user-card summary { cursor: pointer; list-style: none; padding: 16px 18px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
            .user-card summary::-webkit-details-marker { display: none; }
            .user-card summary::after { content: '▾'; color: #64748b; transition: transform 0.2s ease; flex-shrink: 0; }
            .user-card[open] summary::after { transform: rotate(180deg); }
            .user-card-header { display: flex; align-items: center; gap: 10px; min-width: 0; }
            .user-card-name { font-weight: 700; color: #1e293b; overflow-wrap: anywhere; }
            .user-card-meta { color: #64748b; font-size: 0.88rem; }
            .user-card-body { padding: 0 18px 18px 18px; display: flex; flex-direction: column; gap: 14px; }
            .user-card-row { display: flex; flex-direction: column; gap: 8px; }
            .user-card-actions { display: flex; justify-content: flex-end; }
            
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
            @media (max-width: 980px) {
                .user-access-form { grid-template-columns: 1fr 1fr; }
                .user-access-form .form-group:last-of-type { grid-column: 1 / -1; }
                .compact-camera-input { max-width: 100%; }
            }
            @media (max-width: 768px) {
                .user-access-form { grid-template-columns: 1fr; }
                .user-access-form .btn { width: 100%; }
                .user-card summary { align-items: flex-start; }
                .user-card-actions { justify-content: stretch; }
                .user-card-actions .btn { width: 100%; }
            }
            
            [data-theme="dark"] {
                --glass-bg: rgba(30, 41, 59, 0.75);
                --glass-border: rgba(255, 255, 255, 0.15);
                --primary: #6366f1;
                --primary-hover: #818cf8;
                --text-main: #f8fafc;
                --text-sub: #cbd5e1;
            }
            [data-theme="dark"] body { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); }
            [data-theme="dark"] .blob { background: linear-gradient(135deg, rgba(99,102,241,0.2), rgba(236,72,153,0.2)); }
            [data-theme="dark"] h1 { color: #f8fafc; text-shadow: 0 2px 10px rgba(0,0,0,0.5); }
            [data-theme="dark"] .btn-secondary { background: #334155; color: #f8fafc; box-shadow: 0 4px 15px rgba(0,0,0,0.25); border: 1px solid #475569; }
            [data-theme="dark"] .btn-secondary:hover { background: #475569; }
            [data-theme="dark"] tr.row-item { background: rgba(30, 41, 59, 0.5); }
            [data-theme="dark"] tr.row-item:hover { background: rgba(30, 41, 59, 0.8); }
            [data-theme="dark"] input[type="text"], [data-theme="dark"] input[type="email"] { background: rgba(15, 23, 42, 0.8); color: #f8fafc; border: 1px solid rgba(255,255,255,0.1); }
            [data-theme="dark"] input:focus { background: #0f172a; }
            [data-theme="dark"] .inline-edit-input { background: rgba(15, 23, 42, 0.9); color: #818cf8; border: 1px solid #475569; }
            [data-theme="dark"] .camera-checkbox-item { background: rgba(30, 41, 59, 0.65); border: 1px solid rgba(255,255,255,0.1); }
            [data-theme="dark"] .collapsible-block { background: rgba(30, 41, 59, 0.35); border: 1px solid rgba(255,255,255,0.1); }
            [data-theme="dark"] .collapsible-block summary { color: #cbd5e1; }
            [data-theme="dark"] .checkbox-panel { background: rgba(30, 41, 59, 0.45); border: 1px solid rgba(255,255,255,0.1); }
            [data-theme="dark"] .user-card { background: rgba(30, 41, 59, 0.55); border: 1px solid rgba(255,255,255,0.15); }
            [data-theme="dark"] .user-card-name { color: #f8fafc; }
            [data-theme="dark"] .unmapped-highlight { background: rgba(153, 27, 27, 0.2); border: 1px solid #991b1b; }
        </style>
    </head>
    <body>
        """ + THEME_TOGGLE_UI + """
        <div class="blob"></div>
        <div class="container">
            <h1>Admin Dashboard</h1>
            <div style="text-align:center; margin: 0 0 16px 0;">""" + get_env_badge("Admin Settings") + """</div>
            
            <div class="page-actions" style="margin-bottom: 30px;">
                <a class="btn btn-secondary" href="/gallery" style="text-decoration:none; display:inline-flex; align-items:center; gap:8px;">
                    <span style="font-size:1.2rem;">←</span> Back to Gallery
                </a>
                <a class="btn btn-danger" href="/logout" style="text-decoration:none;">Logout</a>
            </div>
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
                <div class="user-access-form">
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
                        <input type="text" id="new-user-cameras" class="compact-camera-input" placeholder="CAM_01, CAM_02" onchange="renderNewUserCameraOptions()">
                    </div>
                    <button class="btn" onclick="addUserAccess()">+ Add User</button>
                </div>
                <details class="collapsible-block">
                    <summary>許可カメラをチェックボックスから選ぶ</summary>
                    <div class="collapsible-content">
                        <div class="checkbox-panel">
                            <div id="new-user-camera-checkboxes" class="camera-checkbox-grid"></div>
                        </div>
                    </div>
                </details>
                <div id="user-access-body" class="user-access-list"></div>
            </div>

            <div class="page-actions">
                <a href="/gallery" class="btn btn-secondary" style="text-decoration:none; display:inline-flex; align-items:center;">Image Gallery</a>
                <a href="/logout" class="btn btn-danger" style="text-decoration:none; display:inline-flex; align-items:center;">Logout</a>
            </div>

            <a href="/gallery" class="nav-link">← Go back to Image Gallery</a>
        </div>

        <div id="toast">✅ Settings saved successfully!</div>

        <script>
            let currentMapping = {};
            let currentMailingLists = {};
            let currentCameraAlert = {};
            let currentUserAccess = {};
            let availableCameraIds = [];

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
                    const cameraRes = await fetch('/api/config/available_cameras');
                    const cameraData = await cameraRes.json();
                    availableCameraIds = cameraData.camera_ids || [];
                    refreshAvailableCameraIdsFromState();
                    renderNewUserCameraOptions();
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

            function refreshAvailableCameraIdsFromState() {
                const merged = new Set(availableCameraIds || []);
                const users = (currentUserAccess && currentUserAccess.users) || {};

                Object.values(users).forEach(info => {
                    if (!info || !Array.isArray(info.allowed_cameras)) return;
                    info.allowed_cameras.forEach(cameraId => {
                        const text = String(cameraId || '').trim();
                        if (text) merged.add(text);
                    });
                });

                const newUserInput = document.getElementById('new-user-cameras');
                if (newUserInput) {
                    normalizeCameraList(newUserInput.value).forEach(cameraId => merged.add(cameraId));
                }

                availableCameraIds = Array.from(merged).sort();
            }

            function mergeCameraSelections(textValue, selectedValues) {
                return Array.from(new Set([
                    ...selectedValues,
                    ...normalizeCameraList(textValue || '')
                ])).sort();
            }

            function renderCheckboxes(containerId, selectedValues, inputId, onChangeExpression) {
                const container = document.getElementById(containerId);
                if (!container) return;
                container.innerHTML = '';
                const selected = new Set(selectedValues || []);

                availableCameraIds.forEach(cameraId => {
                    const item = document.createElement('label');
                    item.className = 'camera-checkbox-item';
                    item.innerHTML = `
                        <input type="checkbox" value="${cameraId}" ${selected.has(cameraId) ? 'checked' : ''} onchange="${onChangeExpression}">
                        <span>${cameraId}</span>
                    `;
                    container.appendChild(item);
                });
            }

            function getCheckedCameraValues(containerId) {
                const container = document.getElementById(containerId);
                if (!container) return [];
                return Array.from(container.querySelectorAll('input[type="checkbox"]:checked')).map(el => el.value);
            }

            function renderNewUserCameraOptions() {
                refreshAvailableCameraIdsFromState();
                const selected = mergeCameraSelections(
                    document.getElementById('new-user-cameras')?.value || '',
                    getCheckedCameraValues('new-user-camera-checkboxes')
                );
                renderCheckboxes(
                    'new-user-camera-checkboxes',
                    selected,
                    'new-user-cameras',
                    "syncNewUserCameraInput()"
                );
                syncNewUserCameraInput();
            }

            function syncNewUserCameraInput() {
                const input = document.getElementById('new-user-cameras');
                if (!input) return;
                const merged = mergeCameraSelections(input.value, getCheckedCameraValues('new-user-camera-checkboxes'));
                input.value = merged.join(', ');
            }

            async function persistUserAccess() {
                await fetch('/api/config/user_access', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(currentUserAccess)
                });
                refreshAvailableCameraIdsFromState();
            }

            function renderUserAccess() {
                const container = document.getElementById('user-access-body');
                if (!container) return;
                container.innerHTML = '';

                const users = currentUserAccess.users || {};
                if (Object.keys(users).length === 0) {
                    container.innerHTML = '<div class="subtle-text">登録済みユーザはまだありません。</div>';
                    return;
                }

                for (const [username, info] of Object.entries(users)) {
                    const checkboxId = `user-camera-checkboxes-${username.replace(/[^a-zA-Z0-9_-]/g, '_')}`;
                    const userCard = document.createElement('details');
                    userCard.className = 'user-card';
                    const cameraCount = (info.allowed_cameras || []).length;
                    userCard.innerHTML = `
                        <summary>
                            <div class="user-card-header">
                                <span class="user-card-name">${username}</span>
                                <span class="user-card-meta">許可カメラ ${cameraCount}件</span>
                            </div>
                        </summary>
                        <div class="user-card-body">
                            <div class="user-card-row">
                                <label>Password</label>
                                <input type="text" value="${info.password || ''}" class="inline-edit-input" onchange="updateUserPassword('${username}', this.value)">
                            </div>
                            <div class="user-card-row">
                                <label>Allowed Camera IDs</label>
                                <input type="text" value="${(info.allowed_cameras || []).join(', ')}" class="inline-edit-input compact-camera-input" style="color:#1e293b;" onchange="updateUserCameras('${username}', this.value)" placeholder="CAM_01, CAM_02">
                                <details class="collapsible-block">
                                    <summary>チェックボックスから選ぶ</summary>
                                    <div class="collapsible-content">
                                        <div class="checkbox-panel">
                                            <div id="${checkboxId}" class="camera-checkbox-grid"></div>
                                        </div>
                                    </div>
                                </details>
                            </div>
                            <div class="user-card-actions">
                                <button class="btn btn-danger" style="padding:6px 12px;font-size:0.85rem;" onclick="deleteUserAccess('${username}')">Delete</button>
                            </div>
                        </div>
                    `;
                    container.appendChild(userCard);
                    renderCheckboxes(
                        checkboxId,
                        info.allowed_cameras || [],
                        '',
                        `updateUserCamerasFromCheckboxes('${username}', '${checkboxId}')`
                    );
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
                    allowed_cameras: mergeCameraSelections(
                        document.getElementById('new-user-cameras').value,
                        getCheckedCameraValues('new-user-camera-checkboxes')
                    )
                };

                persistUserAccess().then(() => {
                    document.getElementById('new-user-name').value = '';
                    document.getElementById('new-user-password').value = '';
                    document.getElementById('new-user-cameras').value = '';
                    renderUserAccess();
                    renderNewUserCameraOptions();
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
                persistUserAccess().then(() => {
                    renderUserAccess();
                    showToast('許可カメラを更新しました');
                });
            }

            function updateUserCamerasFromCheckboxes(username, checkboxId) {
                if (!currentUserAccess.users || !currentUserAccess.users[username]) return;
                const row = document.getElementById(checkboxId)?.closest('.user-card-row');
                const textInput = row ? row.querySelector('input[type="text"]') : null;
                const merged = mergeCameraSelections(textInput ? textInput.value : '', getCheckedCameraValues(checkboxId));
                currentUserAccess.users[username].allowed_cameras = merged;
                persistUserAccess().then(() => {
                    renderUserAccess();
                    showToast('許可カメラを更新しました');
                });
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
async def gallery(request: Request, credentials: HTTPBasicCredentials = Depends(security)):
    principal = get_optional_principal(request, credentials)
    if not principal:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    """
    Serve a simple HTML page to view raw and processed images.
    """
    is_admin_str = "true" if principal.get("role") == "admin" else "false"
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SLAB WILD ANIMALS Web</title>
        """ + THEME_TOGGLE_SCRIPT + f"""
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
            .item span { width: 100%; box-sizing: border-box; text-align: center; }
            .item-filename { padding: 16px 12px 8px 12px; font-size: 13px; color: #718096; font-weight: 500; word-break: break-all; }
            .item-detection { padding: 0 12px 16px 12px; font-size: 12px; color: #21543b; font-weight: 600; line-height: 1.5; }
            .item-detection.detected { color: #c53030; }
            .item-detection.not-detected { color: #4a5568; }
            .empty-msg { text-align: center; color: #718096; font-size: 16px; margin-top: 50px; font-weight: 500; }
            .camera-section { margin-bottom: 60px; background: #ffffff; border-radius: 16px; padding: 30px 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
            .camera-title { font-size: 1.5rem; color: #1c4532; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; margin-bottom: 30px; display: flex; align-items: center; justify-content: space-between; font-weight: 600; }
            .cycle-list { display: flex; flex-direction: column; gap: 18px; }
            .cycle-section { background: #f8fbf8; border: 1px solid #e2efe5; border-radius: 14px; padding: 18px 16px; }
            .cycle-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 1px solid #e2e8f0; color: #21543b; font-weight: 600; cursor: pointer; user-select: none; }
            .cycle-title .badge { background: #2f855a; color: white; font-size: 0.82rem; padding: 3px 10px; border-radius: 999px; font-weight: 600; }
            .cycle-title-main { display: flex; align-items: center; gap: 10px; min-width: 0; }
            .cycle-title-thumb { width: 50px; height: 50px; border-radius: 6px; object-fit: cover; box-shadow: 0 2px 5px rgba(0,0,0,0.1); flex-shrink: 0; background: #edf2f7; border: 1px solid #d9e5dd; }
            .cycle-title-text { overflow-wrap: anywhere; }
            .cycle-latest { margin-bottom: 22px; }
            .latest-container h3 { color: #276749; margin-bottom: 15px; font-weight: 500; }
            .controls-container { display: flex; justify-content: center; align-items: center; margin-bottom: 40px; position: relative; max-width: 1200px; margin-left: auto; margin-right: auto; padding: 0 20px; }
            .tabs { display: flex; gap: 12px; margin-bottom: 0; }
            .view-mode-selector { position: absolute; right: 20px; display: flex; align-items: center; gap: 10px; background: #ffffff; padding: 8px 16px; border-radius: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
            .filter-bar { max-width: 1200px; margin: 0 auto 28px auto; padding: 0 20px; display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
            .filter-card { background:#ffffff; border-radius:16px; padding:12px 14px; box-shadow:0 4px 12px rgba(0,0,0,0.04); display:flex; flex-direction:column; gap:8px; }
            .filter-card label { font-size:0.85rem; color:#4a5568; font-weight:600; }
            .filter-card select, .filter-card input { border:1px solid #d9e5dd; border-radius:10px; padding:8px 10px; font:inherit; background:#f9fcfa; color:#243b30; }
            .top-actions { display:flex; justify-content:center; gap:12px; margin: 0 0 24px 0; flex-wrap:wrap; }
            .action-link { display:inline-flex; align-items:center; justify-content:center; min-width:120px; padding:10px 16px; border-radius:999px; text-decoration:none; font-weight:600; transition: all 0.2s ease; }
            .action-link.primary { background:#2f855a; color:#fff; box-shadow: 0 4px 10px rgba(47,133,90,0.2); }
            .action-link.primary:hover { background:#276749; }
            .action-link.secondary { background:#ffffff; color:#334155; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
            .action-link.secondary:hover { background:#f8fafc; }
            .action-link.danger { background:#fff1f2; color:#be123c; box-shadow: 0 2px 8px rgba(190,18,60,0.1); }
            .action-link.danger:hover { background:#ffe4e6; }
            @media (max-width: 768px) {
                .controls-container { flex-direction: column; gap: 20px; }
                .view-mode-selector { position: static; }
            }
            .view-mode-selector label { font-size: 14px; font-weight: 500; color: #4a5568; }
            .view-mode-selector select { border: 1px solid #e2e8f0; border-radius: 8px; padding: 4px 8px; font-family: inherit; color: #2d3748; background: #f8fafc; outline: none; cursor: pointer; }
            .flat-cycle-item { background: #ffffff; border-radius: 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.06); padding: 16px; margin-bottom: 18px; border: 1px solid #e2e8f0; }
            .flat-cycle-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; cursor: pointer; user-select: none; padding-bottom: 12px; border-bottom: 1px solid #e2e8f0; }
            .flat-cycle-header:hover { opacity: 0.9; }
            .flat-cycle-thumb { width: 60px; height: 60px; border-radius: 8px; object-fit: cover; background: #f0f4f1; border: 1px solid #e2e8f0; flex-shrink: 0; }
            .flat-cycle-info { flex: 1; min-width: 0; }
            .flat-cycle-title { font-weight: 600; color: #1c4532; margin-bottom: 4px; word-break: break-word; }
            .flat-cycle-meta { font-size: 0.85rem; color: #718096; display: flex; gap: 12px; flex-wrap: wrap; }
            .flat-cycle-badges { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-left: auto; flex-shrink: 0; }
            .flat-cycle-badge { display: inline-flex; align-items: center; padding: 4px 12px; border-radius: 12px; font-size: 0.8rem; font-weight: 600; white-space: nowrap; }
            .flat-cycle-badge.count { background: #e2e8f0; color: #2d3748; }
            .flat-cycle-badge.labels { background: #fed7d7; color: #c53030; }
            .flat-cycle-badge.no-labels { background: #edf2f7; color: #4a5568; }
            .flat-cycle-arrow { font-size: 1.2rem; transition: transform 0.3s; flex-shrink: 0; }
            .flat-cycle-content { display: none; margin-top: 16px; }
            .flat-cycle-content.open { display: block; }
            .sort-controls { display: flex; gap: 12px; align-items: center; margin-bottom: 20px; justify-content: center; flex-wrap: wrap; }
            .sort-select { border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 12px; font-family: inherit; color: #2d3748; background: #ffffff; outline: none; cursor: pointer; font-weight: 500; }
            .sort-direction { display: flex; gap: 8px; }
            .sort-direction button { padding: 6px 12px; border: 1px solid #e2e8f0; border-radius: 6px; background: #ffffff; cursor: pointer; font-weight: 500; color: #4a5568; transition: all 0.2s; }
            .sort-direction button.active { background: #2f855a; color: white; border-color: #2f855a; }
            .overlay { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); z-index:9999; justify-content:center; align-items:center; cursor:zoom-out; }
            .overlay.active { display:flex; }
            .overlay img { max-width:95%; max-height:95%; border-radius:12px; box-shadow:0 12px 40px rgba(0,0,0,0.3); }
            .pagination-controls { display: flex; justify-content: space-between; align-items: center; background: #f8fbf8; padding: 10px 16px; border-radius: 12px; border: 1px solid #e2efe5; margin-bottom: 16px; gap: 10px; flex-wrap: wrap; }
            .pagination-controls select { padding: 6px 10px; border-radius: 8px; border: 1px solid #cbd5e0; font-family: inherit; font-size: 0.9rem; }
            .page-buttons { display: flex; gap: 8px; align-items: center; }
            .page-buttons button { padding: 6px 12px; border: 1px solid #cbd5e0; border-radius: 8px; background: white; cursor: pointer; font-weight: 500; color: #4a5568; transition: background 0.2s; }
            .page-buttons button:hover:not(:disabled) { background: #edf2f7; }
            .page-buttons button:disabled { opacity: 0.5; cursor: not-allowed; }
            .page-buttons span { font-size: 0.9rem; font-weight: 600; color: #2d3748; margin: 0 8px; }
            
            /* Calendar Styles */
            .calendar-header { display: flex; justify-content: space-between; align-items: center; background: #ffffff; padding: 15px 20px; border-radius: 16px; margin-bottom: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.04); border: 1px solid #e2e8f0; }
            .calendar-header h2 { margin: 0; font-size: 1.5rem; color: #1c4532; font-weight: 600; }
            .calendar-nav-btn { background: #e2e8f0; border: none; padding: 8px 16px; border-radius: 8px; font-weight: 600; color: #4a5568; cursor: pointer; transition: all 0.2s; }
                .calendar-nav-btn:hover { background: #cbd5e0; color: #2d3748; }
            .calendar-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 10px; margin-bottom: 30px; }
            .calendar-day-header { text-align: center; font-weight: 600; color: #718096; font-size: 0.9rem; padding: 10px 0; }
            .calendar-cell { background: #ffffff; border-radius: 12px; min-height: 100px; padding: 10px; border: 1px solid #e2e8f0; box-shadow: 0 2px 4px rgba(0,0,0,0.02); display: flex; flex-direction: column; cursor: pointer; transition: all 0.2s; position: relative; }
            .calendar-cell:hover { transform: translateY(-3px); box-shadow: 0 8px 15px rgba(47, 133, 90, 0.1); border-color: #9ae6b4; }
            .calendar-cell.empty { background: transparent; border: none; box-shadow: none; cursor: default; }
            .calendar-cell.empty:hover { transform: none; }
            .calendar-cell.active { border: 2px solid #38a169; background: #f0fdf4; }
            .calendar-date { font-weight: 600; color: #2d3748; font-size: 1.1rem; margin-bottom: 5px; }
            .calendar-cell.today .calendar-date { color: #e53e3e; }
            .calendar-badges { display: flex; flex-direction: column; gap: 4px; margin-top: auto; }
            .calendar-badge { background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px 6px; font-size: 0.75rem; color: #4a5568; display: flex; justify-content: space-between; align-items: center; }
            .calendar-badge.has-detection { background: #fff5f5; border-color: #feb2b2; color: #c53030; font-weight: 600; }
            .calendar-icon-list { font-size: 1rem; margin-top: 4px; display: flex; flex-wrap: wrap; gap: 4px; justify-content: flex-end; }
            #calendar-events-container { background: #ffffff; border-radius: 16px; padding: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.04); border: 1px solid #e2e8f0; display: none; }
            .calendar-events-title { font-size: 1.3rem; color: #1c4532; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 2px solid #e2e8f0; }
            
            [data-theme="dark"] body { background-color: #121915; color: #e2e8f0; }
            [data-theme="dark"] h1 { color: #a5d2b7; }
            [data-theme="dark"] h2, [data-theme="dark"] .latest-container h3, [data-theme="dark"] .calendar-header h2, [data-theme="dark"] .calendar-events-title { color: #86c4a0; border-color: #2d3a33; }
            [data-theme="dark"] .header-accent { background: #48bb78; }
            [data-theme="dark"] .tab { background: #1e2923; color: #cbd5e0; border: 1px solid #2d3a33; }
            [data-theme="dark"] .tab:hover { background: #2d3a33; }
            [data-theme="dark"] .tab.active { background: #38a169; color: #fff; border-color: #38a169; }
            [data-theme="dark"] .latest-item, [data-theme="dark"] .item, [data-theme="dark"] .camera-section, [data-theme="dark"] .flat-cycle-item, [data-theme="dark"] .calendar-cell, [data-theme="dark"] #calendar-events-container, [data-theme="dark"] .calendar-header { background: #1e2923; border-color: #2d3a33; box-shadow: 0 4px 15px rgba(0,0,0,0.2); }
            [data-theme="dark"] .latest-item img, [data-theme="dark"] .item .img-wrapper, [data-theme="dark"] .flat-cycle-thumb { background: #121915; border-color: #2d3a33; }
            [data-theme="dark"] .latest-item span, [data-theme="dark"] .item-filename, [data-theme="dark"] .flat-cycle-title, [data-theme="dark"] .calendar-date { color: #e2e8f0; }
            [data-theme="dark"] .item-detection { color: #86c4a0; }
            [data-theme="dark"] .item-detection.detected { color: #fc8181; }
            [data-theme="dark"] .item-detection.not-detected { color: #a0aec0; }
            [data-theme="dark"] .cycle-section { background: #1e2923; border-color: #2d3a33; }
            [data-theme="dark"] .cycle-title { color: #a5d2b7; border-color: #2d3a33; }
            [data-theme="dark"] .cycle-title .badge { background: #38a169; }
            [data-theme="dark"] .cycle-title-thumb { background: #121915; border-color: #2d3a33; }
            [data-theme="dark"] .view-mode-selector { background: #1e2923; }
            [data-theme="dark"] .view-mode-selector label { color: #cbd5e0; }
            [data-theme="dark"] .view-mode-selector select, [data-theme="dark"] .sort-select, [data-theme="dark"] .filter-card select, [data-theme="dark"] .filter-card input, [data-theme="dark"] .pagination-controls select { background: #121915; color: #e2e8f0; border-color: #2d3a33; }
            [data-theme="dark"] .filter-card { background: #1e2923; border: 1px solid #2d3a33; }
            [data-theme="dark"] .filter-card label { color: #cbd5e0; }
            [data-theme="dark"] .action-link.primary { background: #38a169; }
            [data-theme="dark"] .action-link.primary:hover { background: #2f855a; }
            [data-theme="dark"] .action-link.secondary { background: #1e2923; color: #e2e8f0; border: 1px solid #2d3a33; }
            [data-theme="dark"] .action-link.secondary:hover { background: #2d3a33; }
            [data-theme="dark"] .action-link.danger { background: #742a2a; color: #fc8181; }
            [data-theme="dark"] .action-link.danger:hover { background: #9b2c2c; }
            [data-theme="dark"] .flat-cycle-meta, [data-theme="dark"] .empty-msg { color: #a0aec0; }
            [data-theme="dark"] .flat-cycle-badge.count { background: #2d3748; color: #e2e8f0; }
            [data-theme="dark"] .flat-cycle-badge.labels { background: #742a2a; color: #fc8181; }
            [data-theme="dark"] .flat-cycle-badge.no-labels { background: #2d3748; color: #a0aec0; }
            [data-theme="dark"] .flat-cycle-header { border-color: #2d3a33; }
            [data-theme="dark"] .sort-direction button { background: #1e2923; color: #cbd5e0; border-color: #2d3a33; }
            [data-theme="dark"] .sort-direction button.active { background: #38a169; color: white; border-color: #38a169; }
            [data-theme="dark"] .pagination-controls { background: #1e2923; border-color: #2d3a33; }
            [data-theme="dark"] .page-buttons button { background: #121915; color: #e2e8f0; border-color: #2d3a33; }
            [data-theme="dark"] .page-buttons button:hover:not(:disabled) { background: #2d3a33; }
            [data-theme="dark"] .page-buttons span { color: #e2e8f0; }
            [data-theme="dark"] .calendar-nav-btn { background: #2d3a33; color: #cbd5e0; }
            [data-theme="dark"] .calendar-nav-btn:hover { background: #4a5568; color: #e2e8f0; }
            [data-theme="dark"] .calendar-day-header { color: #a0aec0; }
            [data-theme="dark"] .calendar-cell.active { border-color: #48bb78; background: #22332a; }
            [data-theme="dark"] .calendar-cell.today .calendar-date { color: #fc8181; }
            [data-theme="dark"] .calendar-badge { background: #121915; border-color: #2d3a33; color: #cbd5e0; }
            [data-theme="dark"] .calendar-badge.has-detection { background: #4a1d1d; border-color: #742a2a; color: #fc8181; }
        </style>
    </head>
    <body>
        """ + THEME_TOGGLE_UI + """
        <h1>SLAB WILD ANIMALS Web</h1>
        <div style="text-align:center; margin: 0 0 12px 0;">""" + get_env_badge() + """</div>
        <div class="header-accent"></div>
        <p style="text-align:center; color:#4a5568; margin:0 0 24px 0;">Logged in as: <strong>__USERNAME__</strong> (__ROLE__)</p>
        <div class="top-actions">
            __ADMIN_LINK__
            __STATISTICS_LINK__
            <a class="action-link danger" href="/logout">Logout</a>
        </div>
        
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
                    <option value="calendar">カレンダー (Calendar)</option>
                </select>
            </div>
        </div>
        <div id="sortControls" class="sort-controls" style="display:none;">
            <label for="sortBy" style="font-weight: 600; color: #2d3748;">並び替え:</label>
            <select id="sortBy" class="sort-select" onchange="updateSortAndRerender()">
                <option value="date_desc">日付 (新しい順)</option>
                <option value="date_asc">日付 (古い順)</option>
                <option value="detections_desc">検出数 (多い順)</option>
                <option value="detections_asc">検出数 (少ない順)</option>
            </select>
        </div>
        <div class="filter-bar">
            <div class="filter-card">
                <label for="filter-detection">検知結果</label>
                <select id="filter-detection" onchange="updateFilters()">
                    <option value="all">すべて</option>
                    <option value="detected">検知あり</option>
                    <option value="not_detected">検知なし</option>
                </select>
            </div>
            <div class="filter-card">
                <label for="filter-label">対象ラベル</label>
                <select id="filter-label" onchange="updateFilters()">
                    <option value="all">すべて</option>
                    <option value="animal">animal</option>
                    <option value="person">person</option>
                </select>
            </div>
            <div class="filter-card">
                <label for="filter-video">動画</label>
                <select id="filter-video" onchange="updateFilters()">
                    <option value="all">すべて</option>
                    <option value="with_video">動画あり</option>
                    <option value="without_video">動画なし</option>
                </select>
            </div>
            <div class="filter-card">
                <label for="filter-source">入力元</label>
                <select id="filter-source" onchange="updateFilters()">
                    <option value="all">すべて</option>
                    <option value="satos">統合サーバ</option>
                    <option value="pi">エッジサーバ</option>
                </select>
            </div>
            <div class="filter-card">
                <label for="filter-min-conf">最小信頼度</label>
                <input id="filter-min-conf" type="number" min="0" max="1" step="0.05" placeholder="0.00" onchange="updateFilters()">
            </div>
        </div>
        
        <div class="gallery-container active" id="gallery-processed"></div>
        <div class="gallery-container" id="gallery-raw"></div>
        
        <!-- Calendar View -->
        <div id="gallery-calendar" class="gallery-container" style="display:none; max-width: 1000px; margin: 0 auto; padding-bottom: 60px;">
            <div class="calendar-header">
                <button class="calendar-nav-btn" onclick="changeCalendarMonth(-1)">◀ 前月</button>
                <h2 id="calendar-title">2026年 5月</h2>
                <button class="calendar-nav-btn" onclick="changeCalendarMonth(1)">次月 ▶</button>
            </div>
            <div class="calendar-grid" id="calendar-grid">
                <!-- JavaScriptで生成 -->
            </div>
            
            <div id="calendar-events-container">
                <div class="calendar-events-title" id="calendar-events-title">日付を選択してください</div>
                <div id="calendar-events-content"></div>
            </div>
        </div>
        
        <div id="imageOverlay" class="overlay" onclick="closeOverlay()">
            <img id="overlayImage" src="" alt="Expanded Image">
        </div>

        <script>
            const isAdmin = {is_admin_str};
            // Initialization and state logic
            let currentProcessed = null;
            let currentRaw = null;
            let currentMetadata = null;
            let currentTelemetry = null;
            let currentViewMode = 'grouped';
            let currentExpandedSections = {};
            let currentCycleImageMode = {};
            let currentFilters = {detection: 'all', label: 'all', video: 'all', source: 'all', min_conf: ''};
            let currentSortMode = 'date_desc';

            let flatPagination = { page: 1, limit: 10 };
            let groupedPagination = {};

            function changeFlatPage(delta) {
                flatPagination.page += delta;
                renderGallery('gallery-processed', currentProcessed, '/images/processed');
                renderGallery('gallery-raw', currentRaw, '/images/raw');
            }
            function changeFlatLimit(limit) {
                flatPagination.limit = parseInt(limit, 10);
                flatPagination.page = 1;
                renderGallery('gallery-processed', currentProcessed, '/images/processed');
                renderGallery('gallery-raw', currentRaw, '/images/raw');
            }
            function changeGroupedPage(folder, delta) {
                if (!groupedPagination[folder]) groupedPagination[folder] = { page: 1, limit: 10 };
                groupedPagination[folder].page += delta;
                renderGallery('gallery-processed', currentProcessed, '/images/processed');
                renderGallery('gallery-raw', currentRaw, '/images/raw');
            }
            function changeGroupedLimit(folder, limit) {
                if (!groupedPagination[folder]) groupedPagination[folder] = { page: 1, limit: 10 };
                groupedPagination[folder].limit = parseInt(limit, 10);
                groupedPagination[folder].page = 1;
                renderGallery('gallery-processed', currentProcessed, '/images/processed');
                renderGallery('gallery-raw', currentRaw, '/images/raw');
            }

            function openOverlay(src) {
                document.getElementById('overlayImage').src = src;
                document.getElementById('imageOverlay').classList.add('active');
            }

            function closeOverlay() {
                document.getElementById('imageOverlay').classList.remove('active');
            }

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
                    currentExpandedSections[sectionId] = true;
                    if (arrow) arrow.style.transform = 'rotate(90deg)';
                } else {
                    el.style.display = 'none';
                    currentExpandedSections[sectionId] = false;
                    if (arrow) arrow.style.transform = 'rotate(0deg)';
                }
            }

            function changeViewMode(mode) {
                currentViewMode = mode;
                
                // カレンダーモードの時はProcessed/RawタブとSort/Filterを非表示にする
                const calendarContainer = document.getElementById('gallery-calendar');
                const processedContainer = document.getElementById('gallery-processed');
                const rawContainer = document.getElementById('gallery-raw');
                
                if (mode === 'calendar') {
                    calendarContainer.style.display = 'block';
                    processedContainer.style.display = 'none';
                    rawContainer.style.display = 'none';
                    document.getElementById('sortControls').style.display = 'none';
                    document.querySelector('.tabs').style.display = 'none';
                    renderCalendar();
                } else {
                    calendarContainer.style.display = 'none';
                    document.querySelector('.tabs').style.display = 'flex';
                    // 元のタブの表示状態を復元（activeなタブのコンテナを表示）
                    const activeTab = document.querySelector('.tab.active');
                    if (activeTab && activeTab.textContent.includes('Raw')) {
                        rawContainer.style.display = 'block';
                        processedContainer.style.display = 'none';
                    } else {
                        processedContainer.style.display = 'block';
                        rawContainer.style.display = 'none';
                    }
                    document.getElementById('sortControls').style.display = mode === 'flat' ? 'flex' : 'none';
                    renderGallery('gallery-processed', currentProcessed, '/images/processed');
                    renderGallery('gallery-raw', currentRaw, '/images/raw');
                }
            }

            function updateSortAndRerender() {
                currentSortMode = document.getElementById('sortBy').value;
                renderGallery('gallery-processed', currentProcessed, '/images/processed');
                renderGallery('gallery-raw', currentRaw, '/images/raw');
            }

            function updateFilters() {
                currentFilters = {
                    detection: document.getElementById('filter-detection').value,
                    label: document.getElementById('filter-label').value,
                    video: document.getElementById('filter-video').value,
                    source: document.getElementById('filter-source').value,
                    min_conf: document.getElementById('filter-min-conf').value.trim()
                };
                fetchImages();
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

            function extractCycleIdFromImagePath(imagePath) {
                const filename = imagePath.split('/').pop() || imagePath;
                const matchNew = filename.match(/^(.*?)_\\d{14}_(\\d+)_([1-3][nd]?)\\.jpg$/i);
                if (matchNew) return `${matchNew[1]}_${matchNew[2]}`;
                const matchOld = filename.match(/^(.*)-(\\d+)[nd]?\\.jpg$/i);
                if (matchOld) {
                    return matchOld[1].includes('_') ? matchOld[1].split('_').slice(1).join('_') : matchOld[1];
                }
                return filename.replace(/\\.[^.]+$/, '');
            }

            function extractTimestampFromImagePath(imagePath) {
                const filename = imagePath.split('/').pop() || imagePath;
                const matchNew = filename.match(/_(\\d{14})_/);
                if (matchNew) return matchNew[1];
                return '99999999999999';
            }

            function formatStatusDot(color) {
                return `<span style="width:8px; height:8px; border-radius:50%; background:${color}; display:inline-block; margin-right:4px; flex-shrink:0;"></span>`;
            }

            function formatTelemetryBadge(icon, label, value, color) {
                return `<span style="display:inline-flex; align-items:center; gap:6px; border:1px solid #cbd5e0; border-radius:999px; padding:6px 10px; font-size:0.85rem; color:#2d3748; background:#ffffff; white-space:nowrap;"><span>${formatStatusDot(color)}</span><span>${icon} ${label}: ${value}</span></span>`;
            }

            function formatUpdateAge(updatedAt) {
                const dt = new Date(updatedAt);
                const now = new Date();
                const diffMs = now - dt;
                const diffMins = Math.floor(diffMs / (1000 * 60));
                const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
                const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
                if (diffDays >= 1) {
                    return `${diffDays}日前`;
                }
                if (diffHours >= 1) {
                    return `${diffHours}時間前`;
                }
                return `${diffMins}分前`;
            }

            function getTemperatureColor(tempValue) {
                if (tempValue >= 35) return '#e53e3e';
                if (tempValue >= 30) return '#dd6b20';
                if (tempValue >= 20) return '#38a169';
                if (tempValue >= 10) return '#319795';
                if (tempValue >= 0) return '#3182ce';
                return '#2b6cb0';
            }

            function sortCycles(cycles, sortMode) {
                const entries = Object.entries(cycles);
                
                if (sortMode === 'date_desc') {
                    entries.sort((a, b) => {
                        const timeA = extractTimestampFromImagePath(a[1][0]);
                        const timeB = extractTimestampFromImagePath(b[1][0]);
                        return timeB.localeCompare(timeA);
                    });
                } else if (sortMode === 'date_asc') {
                    entries.sort((a, b) => {
                        const timeA = extractTimestampFromImagePath(a[1][0]);
                        const timeB = extractTimestampFromImagePath(b[1][0]);
                        return timeA.localeCompare(timeB);
                    });
                } else if (sortMode === 'detections_desc') {
                    entries.sort((a, b) => {
                        const countA = getDetectionCountForCycle(a[0]);
                        const countB = getDetectionCountForCycle(b[0]);
                        return countB - countA;
                    });
                } else if (sortMode === 'detections_asc') {
                    entries.sort((a, b) => {
                        const countA = getDetectionCountForCycle(a[0]);
                        const countB = getDetectionCountForCycle(b[0]);
                        return countA - countB;
                    });
                }
                
                const result = {};
                entries.forEach(([key, value]) => {
                    result[key] = value;
                });
                return result;
            }

            function groupImagesByCycle(images) {
                const groups = {};
                images.forEach(img => {
                    const cycleId = extractCycleIdFromImagePath(img);
                    if (!groups[cycleId]) groups[cycleId] = [];
                    groups[cycleId].push(img);
                });
                return groups;
            }

            function getDetectionCountForCycle(cycleId) {
                if (!currentMetadata) return 0;
                for (const key in currentMetadata) {
                    if (key.endsWith(`/${cycleId}`)) {
                        const meta = currentMetadata[key];
                        return (meta.labels && meta.labels.length) || 0;
                    }
                }
                return 0;
            }

            function sortCycles(cycles, sortMode) {
                const entries = Object.entries(cycles);
                
                if (sortMode === 'date_desc') {
                    entries.sort((a, b) => {
                        const timeA = extractTimestampFromImagePath(a[1][0]);
                        const timeB = extractTimestampFromImagePath(b[1][0]);
                        return timeB.localeCompare(timeA);
                    });
                } else if (sortMode === 'date_asc') {
                    entries.sort((a, b) => {
                        const timeA = extractTimestampFromImagePath(a[1][0]);
                        const timeB = extractTimestampFromImagePath(b[1][0]);
                        return timeA.localeCompare(timeB);
                    });
                } else if (sortMode === 'detections_desc') {
                    entries.sort((a, b) => {
                        const countA = getDetectionCountForCycle(a[0]);
                        const countB = getDetectionCountForCycle(b[0]);
                        return countB - countA;
                    });
                } else if (sortMode === 'detections_asc') {
                    entries.sort((a, b) => {
                        const countA = getDetectionCountForCycle(a[0]);
                        const countB = getDetectionCountForCycle(b[0]);
                        return countA - countB;
                    });
                }
                
                const result = {};
                entries.forEach(([key, value]) => {
                    result[key] = value;
                });
                return result;
            }

            function buildEventUrl(imagePath, sourceMode) {
                return `/event/${imagePath}?source=${sourceMode}`;
            }

            function rerenderGalleries() {
                renderGallery('gallery-processed', currentProcessed, '/images/processed');
                renderGallery('gallery-raw', currentRaw, '/images/raw');
            }

            function getImageSummary(folder, cycleId, filename) {
                if (!currentMetadata || !currentMetadata[`${folder}/${cycleId}`]) return '';
                const meta = currentMetadata[`${folder}/${cycleId}`];
                if (!meta.image_summaries || !meta.image_summaries[filename]) return '';
                const summary = meta.image_summaries[filename];
                return summary === 'No targets' ? 'Detections: none' : `Detections: ${summary}`;
            }

            function getCycleTime(folder, cycleId) {
                if (currentMetadata && currentMetadata[`${folder}/${cycleId}`]) {
                    const meta = currentMetadata[`${folder}/${cycleId}`];
                    if (meta.cycle_time) return meta.cycle_time;
                }
                if (cycleId.length === 14 && /^\\d+$/.test(cycleId)) {
                    return `${cycleId.substring(0,4)}/${cycleId.substring(4,6)}/${cycleId.substring(6,8)} ${cycleId.substring(8,10)}:${cycleId.substring(10,12)}:${cycleId.substring(12,14)}`;
                }
                return '';
            }

            function renderImageCard(imagePath, sourceMode, folder, cycleId, showTime = false) {
                const filename = imagePath.split('/').pop();
                const basePath = sourceMode === 'raw' ? '/images/raw' : '/images/processed';
                const summaryText = getImageSummary(folder, cycleId, filename);
                const summaryClass = summaryText && summaryText !== 'Detections: none' ? 'item-detection detected' : 'item-detection not-detected';
                const clickAction = `openOverlay('${basePath}/${imagePath}')`;

                const timeStr = getCycleTime(folder, cycleId);
                const timeHtml = showTime && timeStr ? `<span style="font-size: 0.8em; color: #4a5568; display: block; margin-top: 4px;">🕒 ${timeStr}</span>` : '';

                return `
                                    <div class="item">
                                        <div class="img-wrapper" onclick="${clickAction}" style="cursor: zoom-in;">
                                            <img src="${basePath}/${imagePath}" loading="lazy" decoding="async" title="Click to enlarge">
                                        </div>
                                        <span class="item-filename">${filename}</span>
                                        ${timeHtml}
                                        <span class="${summaryClass}">${summaryText || 'Detections: unavailable'}</span>
                                    </div>
                                `;
            }

            function renderGallery(containerId, images, basePath) {
                const container = document.getElementById(containerId);
                const isProcessed = containerId === 'gallery-processed';
                const defaultSourceMode = isProcessed ? 'processed' : 'raw';
                if (!images || images.length === 0) {
                    container.innerHTML = '<div class="empty-msg">No images found yet. Captured images will appear here.</div>';
                    return;
                }

                let html = '';

                if (currentViewMode === 'grouped') {
                    const groups = groupImagesByFolder(images);
                    for (const folder of Object.keys(groups).sort()) {
                        const folderImages = groups[folder];
                        const sectionId = `cam-section-${containerId}-${folder.replace(/[^a-z0-9]/gi, '_')}`;
                        const cycleGroups = groupImagesByCycle(folderImages);
                        const isSectionExpanded = !!currentExpandedSections[sectionId];

                        let teleHtml = '';
                        if (currentTelemetry && currentTelemetry[folder]) {
                            const t = currentTelemetry[folder];
                            teleHtml = '<div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">';

                            if (t.battery) {
                                const batteryValue = parseFloat(t.battery.replace(/[^0-9.-]/g, ''));
                                const batteryColor = batteryValue < 20 ? '#e53e3e' : batteryValue < 50 ? '#dd6b20' : '#38a169';
                                const batteryText = t.battery.replace('Median', '');
                                teleHtml += formatTelemetryBadge('🔋', 'バッテリー', batteryText, batteryColor);
                            }

                            if (t.signal) {
                                // "Very Good(4G)" のような括弧付きも正しく判定するため、括弧前の部分だけ取得
                                const signalBase = t.signal.trim().replace(/\(.*\)/, '').trim().toLowerCase();
                                let signalColor;
                                if (signalBase === 'very good') {
                                    signalColor = '#38a169';  // 緑
                                } else if (signalBase === 'good') {
                                    signalColor = '#68d391';  // 薄緑
                                } else if (signalBase === 'weak') {
                                    signalColor = '#dd6b20';  // 橙
                                } else {
                                    signalColor = '#e53e3e';  // 赤 (Very Weak)
                                }
                                teleHtml += formatTelemetryBadge('📶', '信号', t.signal, signalColor);
                            }

                            if (t.temperature) {
                                const tempValue = parseFloat(t.temperature.split(' ')[0]);
                                const tempColor = getTemperatureColor(tempValue);
                                teleHtml += formatTelemetryBadge('🌡️', '温度', `${tempValue}°C`, tempColor);
                            }

                            if (t.free_space) {
                                const spaceMatch = t.free_space.match(/(\d+(?:\.\d+)?)\s*(GB?|MB?|KB?|B)/i);
                                if (spaceMatch) {
                                    const spaceValue = parseFloat(spaceMatch[1]);
                                    const rawUnit = spaceMatch[2].toUpperCase();
                                    const spaceUnit = rawUnit === 'M' ? 'MB' : rawUnit === 'G' ? 'GB' : rawUnit === 'K' ? 'KB' : rawUnit;
                                    
                                    // デフォルトは絶対値ベースの色判定
                                    let spaceColor = '#38a169';
                                    if ((spaceUnit === 'GB' && spaceValue < 1) || (spaceUnit === 'MB' && spaceValue < 100)) {
                                        spaceColor = '#e53e3e';
                                    } else if ((spaceUnit === 'GB' && spaceValue < 2) || (spaceUnit === 'MB' && spaceValue < 500)) {
                                        spaceColor = '#dd6b20';
                                    }

                                    // %表示の計算（total_spaceがある場合）
                                    let spaceDisplay = t.free_space;
                                    if (t.total_space) {
                                        const totalMatch = t.total_space.match(/(\d+(?:\.\d+)?)\s*(GB?|MB?|KB?|B)/i);
                                        if (totalMatch) {
                                            const totalValue = parseFloat(totalMatch[1]);
                                            const rawTotalUnit = totalMatch[2].toUpperCase();
                                            const totalUnit = rawTotalUnit === 'M' ? 'MB' : rawTotalUnit === 'G' ? 'GB' : rawTotalUnit === 'K' ? 'KB' : rawTotalUnit;
                                            // 単位をMBに統一して計算
                                            const unitFactor = { 'GB': 1024, 'MB': 1, 'KB': 1/1024, 'B': 1/(1024*1024) };
                                            const freeInMB = spaceValue * (unitFactor[spaceUnit] || 1);
                                            const totalInMB = totalValue * (unitFactor[totalUnit] || 1);
                                            if (totalInMB > 0) {
                                                const pct = Math.round((freeInMB / totalInMB) * 100);
                                                spaceDisplay = `${t.free_space} (${pct}%)`;
                                                // %ベースで色を上書き（絶対値より優先）
                                                if (pct < 10) {
                                                    spaceColor = '#e53e3e';  // 赤: 残り10%未満
                                                } else if (pct < 20) {
                                                    spaceColor = '#dd6b20';  // 橙: 残り20%未満
                                                } else {
                                                    spaceColor = '#38a169';  // 緑: 残り20%以上
                                                }
                                            }
                                        }
                                    }
                                    teleHtml += formatTelemetryBadge('💾', '空き容量', spaceDisplay, spaceColor);
                                }
                            }

                            if (t.updated_at) {
                                const updateLabel = formatUpdateAge(t.updated_at);
                                const dt = new Date(t.updated_at);
                                const diffMs = new Date() - dt;
                                const diffDays = diffMs / (1000 * 60 * 60 * 24);
                                let timeColor;
                                if (diffDays > 3) {
                                    timeColor = '#e53e3e';   // 赤: 3日以上
                                } else if (diffDays > 1) {
                                    timeColor = '#dd6b20';   // 橙: 1〜3日
                                } else {
                                    timeColor = '#38a169';   // 緑: 1日以内
                                }
                                const fTime = `${dt.getMonth()+1}/${dt.getDate()} ${dt.getHours().toString().padStart(2, '0')}:${dt.getMinutes().toString().padStart(2, '0')}`;
                                teleHtml += formatTelemetryBadge('🕒', '更新', `${fTime} (${updateLabel})`, timeColor);
                            }

                            teleHtml += '</div>';
                        }

                        html += `
                            <div class="camera-section">
                                <div class="camera-title" onclick="toggleSection('${sectionId}')" style="cursor:pointer; user-select:none; display:flex; align-items:center;">
                                    <span>CAM: ${folder}</span>
                                    <div style="margin-left: auto; display: flex; align-items: center; gap: 15px;">
                                        ${teleHtml}
                                        <span id="${sectionId}-arrow" style="font-size:1.2rem; transition: transform 0.3s; transform:${isSectionExpanded ? 'rotate(90deg)' : 'rotate(0deg)'};">▶</span>
                                    </div>
                                </div>
                                <div id="${sectionId}" style="display:${isSectionExpanded ? 'block' : 'none'}; overflow:hidden; transition: all 0.3s ease;">
                        `;

                        const allCycleIds = Object.keys(cycleGroups).sort().reverse();
                        const totalCycles = allCycleIds.length;
                        if (!groupedPagination[folder]) groupedPagination[folder] = { page: 1, limit: 10 };
                        const limit = groupedPagination[folder].limit;
                        const totalPages = Math.ceil(totalCycles / limit) || 1;
                        let page = groupedPagination[folder].page;
                        if (page > totalPages) page = totalPages;
                        if (page < 1) page = 1;
                        groupedPagination[folder].page = page;

                        const startIdx = (page - 1) * limit;
                        const currentCycleIds = allCycleIds.slice(startIdx, startIdx + limit);

                        if (totalCycles > 0) {
                            html += `
                                <div class="pagination-controls" style="margin: 10px 15px;">
                                    <div>
                                        <label style="font-size: 0.85rem; font-weight: 600; color: #4a5568; margin-bottom: 0;">表示件数:</label>
                                        <select onchange="changeGroupedLimit('${folder}', this.value)" style="margin-left: 8px;">
                                            <option value="10" ${limit === 10 ? 'selected' : ''}>10件</option>
                                            <option value="25" ${limit === 25 ? 'selected' : ''}>25件</option>
                                            <option value="50" ${limit === 50 ? 'selected' : ''}>50件</option>
                                        </select>
                                        <span style="margin-left:10px; font-size:0.85rem; color:#718096;">(全 ${totalCycles} サイクル)</span>
                                    </div>
                                    <div class="page-buttons">
                                        <button onclick="changeGroupedPage('${folder}', -1)" ${page <= 1 ? 'disabled' : ''}>＜ 前へ</button>
                                        <span>${page} / ${totalPages}</span>
                                        <button onclick="changeGroupedPage('${folder}', 1)" ${page >= totalPages ? 'disabled' : ''}>次へ ＞</button>
                                    </div>
                                </div>
                            `;
                        }

                        html += `
                                    <div class="cycle-list">
                        `;

                        for (const cycleId of currentCycleIds) {
                            const cycleSourceMode = defaultSourceMode;
                            const cycleImages = cycleGroups[cycleId];
                            const previewImage = cycleImages[0];
                            const cycleSectionId = `cycle-section-${containerId}-${folder.replace(/[^a-z0-9]/gi, '_')}-${cycleId.replace(/[^a-z0-9]/gi, '_')}`;
                            const isCycleExpanded = !!currentExpandedSections[cycleSectionId];

                            let labelsHtml = '';
                            let cycleTimeHtml = '';
                            if (currentMetadata && currentMetadata[`${folder}/${cycleId}`]) {
                                const meta = currentMetadata[`${folder}/${cycleId}`];
                                if (meta.cycle_time) {
                                    cycleTimeHtml = `<span style="margin-left: 15px; font-size: 0.9em; color: #4a5568;">🕒 ${meta.cycle_time}</span>`;
                                }
                                if (meta.labels && meta.labels.length > 0) {
                                    labelsHtml = `<span style="margin-left: 15px; font-size: 0.85em; color: #fff; background: #e53e3e; padding: 3px 10px; border-radius: 12px; font-weight: bold; letter-spacing: 0.5px;">${meta.labels.join(', ')}</span>`;
                                } else {
                                    labelsHtml = `<span style="margin-left: 15px; font-size: 0.85em; color: #718096; background: #edf2f7; padding: 3px 10px; border-radius: 12px; font-weight: bold;">No detections</span>`;
                                }
                            }
                            
                            if (!cycleTimeHtml && cycleId.length === 14 && /^\\d+$/.test(cycleId)) {
                                cycleTimeHtml = `<span style="margin-left: 15px; font-size: 0.9em; color: #4a5568;">🕒 ${cycleId.substring(0,4)}/${cycleId.substring(4,6)}/${cycleId.substring(6,8)} ${cycleId.substring(8,10)}:${cycleId.substring(10,12)}:${cycleId.substring(12,14)}</span>`;
                            }

                            html += `
                                <div class="cycle-section">
                                    <div class="cycle-title" onclick="toggleSection('${cycleSectionId}')">
                                        <div class="cycle-title-main">
                                            <img src="${cycleSourceMode === 'raw' ? '/images/raw' : '/images/processed'}/${previewImage}" class="cycle-title-thumb" alt="thumb" loading="lazy">
                                            <span class="cycle-title-text">Cycle: ${cycleId}</span>
                                            ${cycleTimeHtml}
                                            <span class="badge" style="margin-left: 15px;">${cycleImages.length} images</span>
                                            ${isAdmin ? `<button style="margin-left:auto; padding: 2px 6px; font-size:1.2rem; margin-right:15px; border:none; background:transparent; cursor:pointer;" onclick="event.stopPropagation(); deleteCycle('${folder}', '${cycleId}')" title="Delete Cycle">🗑️</button>` : ''}
                                            ${labelsHtml}
                                        </div>
                                        <span id="${cycleSectionId}-arrow" style="font-size:1.05rem; transition: transform 0.3s; transform:${isCycleExpanded ? 'rotate(90deg)' : 'rotate(0deg)'};">▶</span>
                                    </div>
                                    <div id="${cycleSectionId}" style="display:${isCycleExpanded ? 'block' : 'none'}; overflow:hidden; transition: all 0.3s ease; padding: 20px 0;">
                                        <div style="text-align: right; margin-bottom: 15px; padding-right: 15px;">
                                            <a href="/event/${folder}/${cycleId}" class="action-link primary" style="padding: 6px 16px; font-size: 0.9rem; text-decoration: none;">View Event Details ↗</a>
                                        </div>
                            `;

                            if (currentMetadata && currentMetadata[`${folder}/${cycleId}`]) {
                                const meta = currentMetadata[`${folder}/${cycleId}`];
                                if (meta.video_paths && meta.video_paths.length > 0) {
                                    const videoPath = meta.video_paths[0];
                                    const posterPath = `${cycleSourceMode === 'raw' ? '/images/raw' : '/images/processed'}/${previewImage}`;
                                    html += `
                                        <div style="text-align: center; margin-bottom: 25px;">
                                            <video controls preload="none" poster="${posterPath}" style="max-width: 100%; max-height: 450px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); background: #000;">
                                                <source src="/videos/${videoPath}">
                                            </video>
                                        </div>
                                    `;
                                }
                            }

                            html += '<div class="gallery-grid" style="margin-bottom: 10px;">';
                            for (let i = 0; i < cycleImages.length; i++) {
                                const imagePath = cycleImages[i];
                                html += renderImageCard(imagePath, cycleSourceMode, folder, cycleId, false);
                            }
                            html += `
                                        </div>
                                    </div>
                                </div>
                            `;
                        }

                        html += `
                                    </div>
                                </div>
                            </div>
                        `;
                    }
                } else {
                    const sourceMode = defaultSourceMode;
                    const allCycles = groupImagesByCycle(images);
                    const sortedCycles = sortCycles(allCycles, currentSortMode);
                    
                    const cycleEntries = Object.entries(sortedCycles);
                    const totalCycles = cycleEntries.length;
                    const limit = flatPagination.limit;
                    const totalPages = Math.ceil(totalCycles / limit) || 1;
                    let page = flatPagination.page;
                    if (page > totalPages) page = totalPages;
                    if (page < 1) page = 1;
                    flatPagination.page = page;

                    const startIdx = (page - 1) * limit;
                    const currentCycleEntries = cycleEntries.slice(startIdx, startIdx + limit);

                    let paginationHtml = '';
                    if (totalCycles > 0) {
                        paginationHtml = `
                            <div class="pagination-controls" style="max-width: 1200px; margin: 0 auto 20px auto;">
                                <div>
                                    <label style="font-size: 0.85rem; font-weight: 600; color: #4a5568; margin-bottom: 0;">表示件数:</label>
                                    <select onchange="changeFlatLimit(this.value)" style="margin-left: 8px;">
                                        <option value="10" ${limit === 10 ? 'selected' : ''}>10件</option>
                                        <option value="25" ${limit === 25 ? 'selected' : ''}>25件</option>
                                        <option value="50" ${limit === 50 ? 'selected' : ''}>50件</option>
                                    </select>
                                    <span style="margin-left:10px; font-size:0.85rem; color:#718096;">(全 ${totalCycles} サイクル)</span>
                                </div>
                                <div class="page-buttons">
                                    <button onclick="changeFlatPage(-1)" ${page <= 1 ? 'disabled' : ''}>＜ 前へ</button>
                                    <span>${page} / ${totalPages}</span>
                                    <button onclick="changeFlatPage(1)" ${page >= totalPages ? 'disabled' : ''}>次へ ＞</button>
                                </div>
                            </div>
                        `;
                    }

                    html += paginationHtml;
                    html += '<div style="max-width: 1200px; margin: 0 auto; padding: 0 20px;">';
                    
                    currentCycleEntries.forEach((entry, idx) => {
                        const cycleId = entry[0];
                        const cycleImages = entry[1];
                        const previewImage = cycleImages[0];
                        const flatCycleSectionId = `flat-cycle-${containerId}-${cycleId.replace(/[^a-z0-9]/gi, '_')}`;
                        const isFlatCycleExpanded = !!currentExpandedSections[flatCycleSectionId];
                        
                        let cycleMetaKey = null;
                        let detectionCount = 0;
                        let labelsStr = 'No detections';
                        let badgeClass = 'no-labels';
                        
                        if (currentMetadata) {
                            for (const key in currentMetadata) {
                                if (key.endsWith(`/${cycleId}`)) {
                                    cycleMetaKey = key;
                                    const meta = currentMetadata[key];
                                    if (meta.labels && meta.labels.length > 0) {
                                        detectionCount = meta.labels.length;
                                        labelsStr = meta.labels.join(', ');
                                        badgeClass = 'labels';
                                    }
                                    break;
                                }
                            }
                        }
                        
                        const pathParts = previewImage.split('/');
                        const folder = pathParts.length > 1 ? pathParts[0] : 'Root';
                        const timeStr = getCycleTime(folder, cycleId);
                        const timeHtml = timeStr ? `<span style="font-size: 0.9em; color: #4a5568; margin-left: 12px;">🕒 ${timeStr}</span>` : '';
                        
                        html += `
                            <div class="flat-cycle-item">
                                <div class="flat-cycle-header" onclick="toggleSection('${flatCycleSectionId}')">
                                    <img src="${sourceMode === 'raw' ? '/images/raw' : '/images/processed'}/${previewImage}" class="flat-cycle-thumb" alt="thumb" loading="lazy">
                                    <div class="flat-cycle-info">
                                        <div class="flat-cycle-title">Cycle: ${cycleId} ${timeHtml}</div>
                                        <div class="flat-cycle-meta">
                                            <span>CAM: ${folder}</span>
                                        </div>
                                    </div>
                                    <div class="flat-cycle-badges">
                                        ${isAdmin ? `<button style="padding: 2px 6px; font-size:1.2rem; margin-right:10px; border:none; background:transparent; cursor:pointer;" onclick="event.stopPropagation(); deleteCycle('${folder}', '${cycleId}')" title="Delete Cycle">🗑️</button>` : ''}
                                        <span class="flat-cycle-badge count">${cycleImages.length} images</span>
                                        <span class="flat-cycle-badge ${badgeClass}">${labelsStr}</span>
                                    </div>
                                    <span class="flat-cycle-arrow" id="${flatCycleSectionId}-arrow" style="transform:${isFlatCycleExpanded ? 'rotate(90deg)' : 'rotate(0deg)'};">▶</span>
                                </div>
                                <div id="${flatCycleSectionId}" class="flat-cycle-content${isFlatCycleExpanded ? ' open' : ''}">
                                    <div style="text-align: right; margin-top: 10px; margin-bottom: 5px; padding-right: 5px;">
                                        <a href="/event/${folder}/${cycleId}" class="action-link primary" style="padding: 6px 16px; font-size: 0.9rem; text-decoration: none;">View Event Details ↗</a>
                                    </div>
                        `;

                        if (currentMetadata && currentMetadata[`${folder}/${cycleId}`]) {
                            const meta = currentMetadata[`${folder}/${cycleId}`];
                            if (meta.video_paths && meta.video_paths.length > 0) {
                                const videoPath = meta.video_paths[0];
                                const posterPath = `${sourceMode === 'raw' ? '/images/raw' : '/images/processed'}/${previewImage}`;
                                html += `
                                    <div style="text-align: center; margin-bottom: 25px;">
                                        <video controls preload="none" poster="${posterPath}" style="max-width: 100%; max-height: 450px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); background: #000;">
                                            <source src="/videos/${videoPath}">
                                        </video>
                                    </div>
                                `;
                            }
                        }

                        html += `
                                    <div class="gallery-grid" style="margin-top: 16px;">
                        `;
                        
                        cycleImages.forEach(imagePath => {
                            const imgPathParts = imagePath.split('/');
                            const imgFolder = imgPathParts.length > 1 ? imgPathParts[0] : 'Root';
                            html += renderImageCard(imagePath, sourceMode, imgFolder, cycleId, true);
                        });
                        
                        html += `
                                    </div>
                                </div>
                            </div>
                        `;
                    });
                    
                    html += '</div>';
                    
                    if (cycleEntries.length === 0) {
                        html += '<div class="empty-msg">No images found yet. Captured images will appear here.</div>';
                    }
                }

                container.innerHTML = html;
            }

            // --- Calendar Logic ---
            let currentCalendarDate = new Date();
            let currentSelectedDateKey = null;

            function getLabelIcon(labelStr) {
                const lower = labelStr.toLowerCase();
                if (lower.includes('person') || lower.includes('human')) return '👤';
                if (lower.includes('animal') || lower.includes('deer') || lower.includes('bear') || lower.includes('boar')) return '🐾';
                if (lower.includes('vehicle') || lower.includes('car')) return '🚙';
                return '❓';
            }

            function renderCalendar() {
                if (!currentMetadata) return;

                const year = currentCalendarDate.getFullYear();
                const month = currentCalendarDate.getMonth();
                
                document.getElementById('calendar-title').textContent = `${year}年 ${month + 1}月`;
                
                const firstDay = new Date(year, month, 1).getDay();
                const daysInMonth = new Date(year, month + 1, 0).getDate();
                
                const sourceMode = document.querySelector('.tab.active').textContent.includes('Raw') ? 'raw' : 'processed';
                const imagesSource = sourceMode === 'raw' ? currentRaw : currentProcessed;
                const allCyclesMap = groupImagesByCycle(imagesSource || []);

                const dailyData = {};
                for (const key in currentMetadata) {
                    const meta = currentMetadata[key];
                    if (!meta.cycle_time) continue;
                    
                    const parts = meta.cycle_time.split(' ')[0].split('/');
                    if (parts.length !== 3) continue;
                    const cYear = parseInt(parts[0], 10);
                    const cMonth = parseInt(parts[1], 10) - 1;
                    const cDate = parseInt(parts[2], 10);
                    
                    if (cYear !== year || cMonth !== month) continue;
                    
                    const dateKey = `${cYear}-${(cMonth+1).toString().padStart(2, '0')}-${cDate.toString().padStart(2, '0')}`;
                    if (!dailyData[dateKey]) {
                        dailyData[dateKey] = { totalCycles: 0, totalImages: 0, detectCycles: 0, iconCounts: {}, cycles: [] };
                    }
                    
                    const [folder, cycleId] = key.split('/');
                    const cycleImagesCount = allCyclesMap[cycleId] ? allCyclesMap[cycleId].length : 0;
                    
                    dailyData[dateKey].totalCycles++;
                    dailyData[dateKey].totalImages += cycleImagesCount;
                    dailyData[dateKey].cycles.push({folder, cycleId});
                    
                    if (meta.labels && meta.labels.length > 0) {
                        dailyData[dateKey].detectCycles++;
                        const uniqueIcons = new Set(meta.labels.map(lbl => getLabelIcon(lbl)));
                        uniqueIcons.forEach(icon => {
                            if (!dailyData[dateKey].iconCounts[icon]) dailyData[dateKey].iconCounts[icon] = 0;
                            dailyData[dateKey].iconCounts[icon]++;
                        });
                    }
                }

                let html = `
                    <div class="calendar-day-header">日</div>
                    <div class="calendar-day-header">月</div>
                    <div class="calendar-day-header">火</div>
                    <div class="calendar-day-header">水</div>
                    <div class="calendar-day-header">木</div>
                    <div class="calendar-day-header">金</div>
                    <div class="calendar-day-header">土</div>
                `;

                for (let i = 0; i < firstDay; i++) {
                    html += `<div class="calendar-cell empty"></div>`;
                }

                const today = new Date();
                const isCurrentMonth = today.getFullYear() === year && today.getMonth() === month;

                for (let d = 1; d <= daysInMonth; d++) {
                    const dateKey = `${year}-${(month+1).toString().padStart(2, '0')}-${d.toString().padStart(2, '0')}`;
                    const data = dailyData[dateKey];
                    const isToday = isCurrentMonth && today.getDate() === d;
                    
                    let badgesHtml = '';
                    if (data && data.detectCycles > 0) {
                        let linesHtml = '';
                        for (const [icon, count] of Object.entries(data.iconCounts)) {
                            linesHtml += `<div style="display: flex; justify-content: space-between; width: 100%; margin-bottom: 3px;"><span style="font-size: 1.1rem;">${icon}</span> <span style="font-weight: 700;">${count}件</span></div>`;
                        }
                        badgesHtml = `
                            <div class="calendar-badges">
                                <div class="calendar-badge has-detection" style="display: flex; flex-direction: column; align-items: flex-start; padding: 6px 10px;">
                                    ${linesHtml}
                                </div>
                            </div>
                        `;
                    }
                    
                    const totalImgStr = (data && data.totalCycles > 0) ? `<span style="font-size: 0.75rem; color: #718096; font-weight: 500; margin-left: 8px;">(総撮影数: ${data.totalCycles})</span>` : '';
                    
                    html += `
                        <div class="calendar-cell ${isToday ? 'today' : ''}" onclick="showCalendarDateEvents('${dateKey}')" id="cal-cell-${dateKey}">
                            <div class="calendar-date">${d}${totalImgStr}</div>
                            ${badgesHtml}
                        </div>
                    `;
                }
                
                document.getElementById('calendar-grid').innerHTML = html;
            }

            function changeCalendarMonth(delta) {
                currentCalendarDate.setMonth(currentCalendarDate.getMonth() + delta);
                renderCalendar();
                document.getElementById('calendar-events-container').style.display = 'none';
            }

            function showCalendarDateEvents(dateKey) {
                currentSelectedDateKey = dateKey;
                document.querySelectorAll('.calendar-cell').forEach(el => el.classList.remove('active'));
                const cell = document.getElementById(`cal-cell-${dateKey}`);
                if (cell) cell.classList.add('active');

                const container = document.getElementById('calendar-events-container');
                const titleEl = document.getElementById('calendar-events-title');
                const contentEl = document.getElementById('calendar-events-content');
                
                container.style.display = 'block';
                const parts = dateKey.split('-');
                titleEl.textContent = `${parts[0]}年 ${parts[1]}月 ${parts[2]}日の検知リスト`;
                
                if (!currentProcessed && !currentRaw) return;
                
                const targetCycles = [];
                for (const key in currentMetadata) {
                    const meta = currentMetadata[key];
                    if (!meta.cycle_time) continue;
                    const cDateStr = meta.cycle_time.split(' ')[0].replace(/\\//g, '-');
                    if (cDateStr === dateKey) {
                        const [folder, cycleId] = key.split('/');
                        targetCycles.push({folder, cycleId, meta});
                    }
                }
                
                if (targetCycles.length === 0) {
                    contentEl.innerHTML = '<div class="empty-msg">この日の検知イベントはありません。</div>';
                    return;
                }
                
                targetCycles.sort((a, b) => b.cycleId.localeCompare(a.cycleId));
                
                const sourceMode = document.querySelector('.tab.active').textContent.includes('Raw') ? 'raw' : 'processed';
                const imagesSource = sourceMode === 'raw' ? currentRaw : currentProcessed;
                const allCyclesMap = groupImagesByCycle(imagesSource || []);
                
                let html = '';
                targetCycles.forEach(target => {
                    const cycleId = target.cycleId;
                    const folder = target.folder;
                    const cycleImages = allCyclesMap[cycleId] || [];
                    if (cycleImages.length === 0) return;
                    
                    const previewImage = cycleImages[0];
                    const flatCycleSectionId = `cal-flat-${folder}-${cycleId}`;
                    const isFlatCycleExpanded = !!currentExpandedSections[flatCycleSectionId];
                    
                    let labelsStr = 'No detections';
                    let badgeClass = 'no-labels';
                    if (target.meta.labels && target.meta.labels.length > 0) {
                        labelsStr = target.meta.labels.join(', ');
                        badgeClass = 'labels';
                    }
                    
                    const timeStr = getCycleTime(folder, cycleId);
                    const timeHtml = timeStr ? `<span style="font-size: 0.9em; color: #4a5568; margin-left: 12px;">🕒 ${timeStr}</span>` : '';
                    
                    html += `
                        <div class="flat-cycle-item">
                            <div class="flat-cycle-header" onclick="toggleSection('${flatCycleSectionId}')">
                                <img src="/images/${sourceMode}/${previewImage}" class="flat-cycle-thumb" alt="thumb" loading="lazy">
                                <div class="flat-cycle-info">
                                    <div class="flat-cycle-title">Cycle: ${cycleId} ${timeHtml}</div>
                                    <div class="flat-cycle-meta">
                                        <span>CAM: ${folder}</span>
                                    </div>
                                </div>
                                <div class="flat-cycle-badges">
                                    ${isAdmin ? `<button style="padding: 2px 6px; font-size:1.2rem; margin-right:10px; border:none; background:transparent; cursor:pointer;" onclick="event.stopPropagation(); deleteCycle('${folder}', '${cycleId}')" title="Delete Cycle">🗑️</button>` : ''}
                                    <span class="flat-cycle-badge count">${cycleImages.length} images</span>
                                    <span class="flat-cycle-badge ${badgeClass}">${labelsStr}</span>
                                </div>
                                <span class="flat-cycle-arrow" id="${flatCycleSectionId}-arrow" style="transform:${isFlatCycleExpanded ? 'rotate(90deg)' : 'rotate(0deg)'};">▶</span>
                            </div>
                            <div id="${flatCycleSectionId}" class="flat-cycle-content${isFlatCycleExpanded ? ' open' : ''}">
                                <div style="text-align: right; margin-top: 10px; margin-bottom: 5px; padding-right: 5px;">
                                    <a href="/event/${folder}/${cycleId}" class="action-link primary" style="padding: 6px 16px; font-size: 0.9rem; text-decoration: none;">View Event Details ↗</a>
                                </div>
                    `;

                    if (target.meta.video_paths && target.meta.video_paths.length > 0) {
                        const videoPath = target.meta.video_paths[0];
                        const posterPath = `/images/${sourceMode}/${previewImage}`;
                        html += `
                            <div style="text-align: center; margin-bottom: 25px;">
                                <video controls preload="none" poster="${posterPath}" style="max-width: 100%; max-height: 450px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); background: #000;">
                                    <source src="/videos/${videoPath}">
                                </video>
                            </div>
                        `;
                    }

                    html += `
                                <div class="gallery-grid" style="margin-top: 16px;">
                    `;
                    
                    cycleImages.forEach(imagePath => {
                        const imgPathParts = imagePath.split('/');
                        const imgFolder = imgPathParts.length > 1 ? imgPathParts[0] : 'Root';
                        html += renderImageCard(imagePath, sourceMode, imgFolder, cycleId, true);
                    });
                    
                    html += `
                                </div>
                            </div>
                        </div>
                    `;
                });
                
                contentEl.innerHTML = html;
            }

            function fetchImages() {
                const params = new URLSearchParams();
                Object.entries(currentFilters).forEach(([key, value]) => {
                    if (value && value !== 'all') params.set(key, value);
                });
                const query = params.toString();
                Promise.all([
                    fetch('/api/images' + (query ? `?${query}` : '')).then(r => r.json()),
                    fetch('/api/telemetry').then(r => r.json())
                ]).then(([data, teleData]) => {
                    let teleChanged = false;
                    if (teleData.status === 'ok') {
                        const newTeleStr = JSON.stringify(teleData.telemetry || {});
                        if (JSON.stringify(currentTelemetry) !== newTeleStr) {
                            teleChanged = true;
                            currentTelemetry = teleData.telemetry || {};
                        }
                    }
                    if (data.status === 'ok') {
                        const processedChanged = !arraysEqual(currentProcessed, data.processed);
                        const rawChanged = !arraysEqual(currentRaw, data.raw);
                        
                        if (processedChanged || rawChanged || teleChanged) {
                            currentProcessed = data.processed;
                            currentRaw = data.raw;
                            currentMetadata = data.metadata;
                            if (currentViewMode === 'calendar') {
                                renderCalendar();
                                if (currentSelectedDateKey) {
                                    showCalendarDateEvents(currentSelectedDateKey);
                                }
                            } else {
                                renderGallery('gallery-processed', data.processed, '/images/processed');
                                renderGallery('gallery-raw', data.raw, '/images/raw');
                            }
                        }
                    } else {
                        console.error('API Error:', data.message);
                    }
                }).catch(err => {
                    console.error('Fetch Error:', err.message);
                });
            }

            async function deleteCycle(cameraId, cycleId) {
                if (!confirm("本当にこのサイクルを削除しますか？\n画像・動画・すべての記録が完全に削除されます。")) return;
                if (!confirm("【最終確認】この操作は元に戻せません。\n本当に削除を実行しますか？")) return;
                
                try {
                    const response = await fetch(`/api/cycle/${cameraId}/${cycleId}`, { method: 'DELETE' });
                    const result = await response.json();
                    if (response.ok) {
                        alert("サイクルを削除しました。");
                        fetchImages();
                    } else {
                        alert("削除に失敗しました: " + (result.detail || result.message));
                    }
                } catch (e) {
                    alert("エラーが発生しました: " + e.message);
                }
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
    admin_link = ""
    stat_link = ""
    if principal.get("role") == "admin":
        admin_link = '<a class="action-link secondary" href="/admin">Admin Settings</a>'
        stat_link = '<a class="action-link secondary" href="/statistics">📊 Statistics</a>'
    html_content = html_content.replace("__ADMIN_LINK__", admin_link)
    html_content = html_content.replace("__STATISTICS_LINK__", stat_link)
    return html_content

if __name__ == "__main__":
    import uvicorn
    server_port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=server_port)
