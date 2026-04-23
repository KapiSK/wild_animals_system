import os
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Depends, HTTPException, status, Header, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
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

APP_VERSION = "1.0.0"

PORT_STR = os.getenv("PORT", "8000")
if PORT_STR == "8000":
    ENV_BADGE = f'<span style="display:inline-block; background: #28a745; color: white; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 0.95rem;">Production (v{APP_VERSION})</span><br><span style="display:inline-block; background: #2f855a; color: white; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 0.95rem; margin-top: 4px;">Gallery</span>'
else:
    ENV_BADGE = f'<span style="display:inline-block; background: #dc3545; color: white; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 0.95rem;">Test Environment (v{APP_VERSION} - Port {PORT_STR})</span><br><span style="display:inline-block; background: #2f855a; color: white; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 0.95rem; margin-top: 4px;">Gallery</span>'

security = HTTPBasic(auto_error=False)
SESSION_COOKIE_NAME = "wild_animals_session"
SESSION_STORE = {}


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
                "has_video": len(get_video_relpaths_for_event(camera_id, cycle_id)) > 0,
                "cycle_time": cycle_time,
                "updated_at": datetime.now().isoformat(),
            }
            save_event_metadata(camera_id, cycle_id, event_metadata)
        except Exception as e:
            logger.error(f"Failed to save event metadata for {cycle_id}: {e}")

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

    for index, row in df.iterrows():
        cls = int(row['class'])
        if cls in TARGET_CLASSES:
            target_found = True
            label = row['name']
            conf = float(row['confidence'])
            detected_targets[label] = detected_targets.get(label, 0) + 1
            if conf > max_conf:
                max_conf = conf

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
        'event_id': cycle_id
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
    safe_seq = re.sub(r"[^0-9A-Za-z_-]", "", x_sequence.strip()) or "001"
    suffix = os.path.splitext(file.filename or "")[1] or ".mov"
    filename = build_video_filename(pure_cam_id, safe_seq, suffix)

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
    if pure_cam_id not in current_data:
        current_data[pure_cam_id] = {}
        
    for k, v in payload.items():
        if k != "camera_id":
            current_data[pure_cam_id][k] = v
    current_data[pure_cam_id]["updated_at"] = datetime.now().isoformat()
    
    save_telemetry(current_data)
    return {"status": "ok"}

@app.get("/api/telemetry")
async def get_telemetry(principal: dict = Depends(verify_credentials)):
    return {"status": "ok", "telemetry": load_telemetry()}

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


@app.get("/event/{image_path:path}", response_class=HTMLResponse)
async def event_detail(
    image_path: str,
    request: Request,
    source: str = "processed",
    credentials: HTTPBasicCredentials = Depends(security)
):
    principal = get_optional_principal(request, credentials)
    if not principal:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    verify_camera_access(principal, image_path)
    selected_source = "raw" if source == "raw" else "processed"
    selected_base_dir = UPLOAD_DIR if selected_source == "raw" else PROCESSED_DIR
    selected_abs = resolve_image_path(selected_base_dir, image_path)
    if not os.path.isfile(selected_abs):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    camera_id = image_path.replace("\\", "/").split("/", 1)[0]
    image_name = os.path.basename(selected_abs)
    event_id = extract_cycle_id(image_name)
    event_metadata = load_event_metadata(camera_id, event_id) or {}

    related_processed = get_related_processed_images(camera_id, event_id)
    related_raw = get_related_raw_images(camera_id, event_id)
    related_videos = get_video_relpaths_for_event(camera_id, event_id)
    primary_video = related_videos[0] if related_videos else ""

    current_images = related_raw if selected_source == "raw" else related_processed
    fallback_images = related_processed if selected_source == "raw" else related_raw
    if not current_images:
        current_images = fallback_images
        selected_source = "processed" if selected_source == "raw" else "raw"

    if current_images:
        selected_rel = next((rel for rel in current_images if os.path.basename(rel) == image_name), current_images[0])
    else:
        selected_rel = image_path
    selected_filename = os.path.basename(selected_rel)
    selected_image_url = f"/images/{selected_source}/{selected_rel}"

    image_summaries = event_metadata.get("image_summaries", {}) if isinstance(event_metadata, dict) else {}
    selected_summary = image_summaries.get(selected_filename, "")
    if selected_summary == "No targets":
        selected_summary = "Detections: none"
    elif selected_summary:
        selected_summary = f"Detections: {selected_summary}"
    else:
        selected_summary = "Detections: unavailable"

    def build_event_link(rel_path: str, image_source: str) -> str:
        return f"/event/{rel_path}?source={image_source}"

    def find_rel_for_source(rel_paths: list, filename: str) -> str:
        if not rel_paths:
            return ""
        for rel in rel_paths:
            if os.path.basename(rel) == filename:
                return rel
        return rel_paths[0]

    processed_link_target = find_rel_for_source(related_processed, selected_filename)
    raw_link_target = find_rel_for_source(related_raw, selected_filename)

    cycle_time = ""
    match_new = re.search(r"^(.*?)_(\d{14})_(\d+)_([1-3][nd]?)\.jpg$", image_name, re.IGNORECASE)
    if match_new:
        time_raw = match_new.group(2)
        cycle_time = f"{time_raw[:4]}/{time_raw[4:6]}/{time_raw[6:8]} {time_raw[8:10]}:{time_raw[10:12]}:{time_raw[12:14]}"

    thumbs_html = ""
    for rel in current_images:
        file_label = os.path.basename(rel)
        active_class = " active" if rel == selected_rel else ""
        thumbs_html += f"""
            <a class="thumb{active_class}" href="{build_event_link(rel, selected_source)}">
                <img src="/images/{selected_source}/{rel}" alt="{file_label}">
                <span>{file_label}</span>
            </a>
        """

    video_block = """
        <div class="empty-video">No related video yet.</div>
    """
    if primary_video:
        video_block = f"""
            <video controls preload="metadata" class="video-player">
                <source src="/videos/{primary_video}">
                Your browser cannot play this video.
            </video>
            <a class="download-link" href="/videos/{primary_video}" target="_blank">Download video</a>
        """

    labels = event_metadata.get("labels", []) if isinstance(event_metadata, dict) else []
    labels_text = ", ".join(labels) if labels else "none"
    detected_count = event_metadata.get("detected_images_count", 0) if isinstance(event_metadata, dict) else 0
    source_label = "No box" if selected_source == "raw" else "With box"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Event Detail</title>
        <style>
            body {{ font-family: 'Inter', 'Segoe UI', sans-serif; margin: 0; padding: 24px; background: #f3f8f4; color: #22332b; }}
            .shell {{ max-width: 1280px; margin: 0 auto; }}
            .topbar {{ display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:20px; }}
            .back-link, .download-link {{ display:inline-flex; align-items:center; justify-content:center; padding:10px 16px; border-radius:999px; text-decoration:none; background:#ffffff; color:#2d4a3a; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
            .panel {{ background:#ffffff; border-radius:20px; padding:20px; box-shadow:0 12px 30px rgba(34,51,43,0.06); }}
            .panel h2 {{ margin:0 0 14px 0; font-size:1.2rem; color:#21543b; }}
            .viewer-panel {{ text-align:center; }}
            .viewer-head {{ display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:18px; }}
            .viewer-title {{ margin:0; font-size:1.25rem; color:#21543b; }}
            .image-mode-toggle {{ display:flex; gap:8px; flex-wrap:wrap; }}
            .toggle-link {{ display:inline-flex; align-items:center; justify-content:center; padding:8px 14px; border-radius:999px; text-decoration:none; background:#edf6f0; color:#21543b; font-weight:600; border:1px solid #d4e5d8; }}
            .toggle-link.active {{ background:#21543b; color:#ffffff; border-color:#21543b; }}
            .main-image-wrap {{ display:flex; justify-content:center; align-items:center; padding:16px; border-radius:18px; background:#f8fbf8; min-height:420px; }}
            .main-image {{ max-width:100%; max-height:72vh; border-radius:16px; background:#f8fbf8; box-shadow:0 12px 32px rgba(34,51,43,0.12); }}
            .selected-summary {{ margin-top:16px; font-size:0.96rem; font-weight:600; color:#21543b; }}
            .video-player {{ width:100%; border-radius:16px; background:#111; min-height:320px; }}
            .meta {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-bottom:20px; }}
            .meta-card {{ background:#ffffff; border-radius:16px; padding:14px 16px; box-shadow:0 8px 22px rgba(34,51,43,0.05); }}
            .meta-label {{ display:block; font-size:0.82rem; color:#6b7f74; margin-bottom:6px; }}
            .meta-value {{ font-weight:600; word-break:break-word; }}
            .thumbs {{ display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:14px; margin-top:22px; }}
            .thumb {{ text-decoration:none; color:inherit; background:#ffffff; border-radius:14px; padding:10px; box-shadow:0 8px 20px rgba(34,51,43,0.05); border:2px solid transparent; transition:transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease; }}
            .thumb:hover {{ transform:translateY(-2px); }}
            .thumb.active {{ border-color:#2f855a; box-shadow:0 14px 28px rgba(47,133,90,0.18); background:#f2fbf5; }}
            .thumb img {{ width:100%; height:130px; object-fit:contain; border-radius:10px; display:block; background:#f8fbf8; }}
            .thumb span {{ display:block; margin-top:8px; font-size:0.85rem; color:#52645a; word-break:break-all; text-align:center; font-weight:600; }}
            .empty-video {{ min-height:320px; border-radius:16px; display:flex; align-items:center; justify-content:center; background:#f6faf7; color:#6b7f74; border:1px dashed #cfe0d5; }}
            @media (max-width: 960px) {{ .thumbs {{ grid-template-columns: 1fr; }} .main-image-wrap {{ min-height:260px; }} }}
        </style>
    </head>
    <body>
        <div class="shell">
            <div class="topbar">
                <a class="back-link" href="/gallery">Gallery</a>
                <a class="back-link" href="/logout">Logout</a>
            </div>
            <div class="meta">
                <div class="meta-card"><span class="meta-label">Camera ID</span><span class="meta-value">{camera_id}</span></div>
                <div class="meta-card"><span class="meta-label">Event ID</span><span class="meta-value">{event_id}</span></div>
                <div class="meta-card"><span class="meta-label">Detected At</span><span class="meta-value">{cycle_time or '-'}</span></div>
                <div class="meta-card"><span class="meta-label">Detected Labels</span><span class="meta-value">{labels_text}</span></div>
                <div class="meta-card"><span class="meta-label">Detected Images</span><span class="meta-value">{detected_count}</span></div>
                <div class="meta-card"><span class="meta-label">Video</span><span class="meta-value">{'yes' if primary_video else 'no'}</span></div>
            </div>
            <section class="panel viewer-panel">
                <div class="viewer-head">
                    <h2 class="viewer-title">Selected Image</h2>
                    <div class="image-mode-toggle">
                        {f'<a class="toggle-link {"active" if selected_source == "processed" else ""}" href="{build_event_link(processed_link_target, "processed")}">With box</a>' if processed_link_target else ''}
                        {f'<a class="toggle-link {"active" if selected_source == "raw" else ""}" href="{build_event_link(raw_link_target, "raw")}">No box</a>' if raw_link_target else ''}
                    </div>
                </div>
                <div class="main-image-wrap">
                    <img class="main-image" src="{selected_image_url}" alt="{selected_filename}">
                </div>
                <div class="selected-summary">{selected_summary}</div>
            </section>
            <section class="panel" style="margin-top:24px;">
                <h2>Cycle Images</h2>
                <div class="thumbs">{thumbs_html or '<div class="empty-video" style="min-height:140px;">No images available.</div>'}</div>
            </section>
            <section class="panel" style="margin-top:24px;">
                <h2>Video</h2>
                {video_block}
            </section>
        </div>
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
        <style>
            body { font-family: 'Inter', 'Segoe UI', sans-serif; margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #eef7f1 0%, #d8efe3 100%); color: #234034; }
            .card { width: min(420px, 92vw); background: rgba(255,255,255,0.92); border: 1px solid rgba(255,255,255,0.7); border-radius: 20px; padding: 32px; box-shadow: 0 20px 40px rgba(35, 64, 52, 0.08); }
            h1 { margin: 0 0 8px 0; font-size: 2rem; text-align: center; }
            p { margin: 0 0 24px 0; text-align: center; color: #4a6a5b; line-height: 1.6; }
            label { display: block; margin-bottom: 8px; font-weight: 600; color: #315745; }
            input { width: 100%; box-sizing: border-box; padding: 12px 14px; border-radius: 12px; border: 1px solid #cfe0d6; background: #fbfdfb; margin-bottom: 18px; font: inherit; }
            button { width: 100%; padding: 12px 16px; border: none; border-radius: 12px; background: #2f855a; color: #fff; font: inherit; font-weight: 600; cursor: pointer; }
            button:hover { background: #276749; }
        </style>
    </head>
    <body>
        <form class="card" method="post" action="/login">
            <h1>Wild Animals Login</h1>
            <div style="text-align:center; margin: 0 0 12px 0;">""" + ENV_BADGE + """</div>
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
        </style>
    </head>
    <body>
        <div class="blob"></div>
        <div class="container">
            <h1>Admin Dashboard</h1>
            <div style="text-align:center; margin: 0 0 16px 0;">""" + ENV_BADGE + """</div>
            
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
    html_content = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SLAB WILD ANIMALS Web</title>
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
        </style>
    </head>
    <body>
        <h1>SLAB WILD ANIMALS Web</h1>
        <div style="text-align:center; margin: 0 0 12px 0;">""" + ENV_BADGE + """</div>
        <div class="header-accent"></div>
        <p style="text-align:center; color:#4a5568; margin:0 0 24px 0;">Logged in as: <strong>__USERNAME__</strong> (__ROLE__)</p>
        <div class="top-actions">
            __ADMIN_LINK__
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
        
        <script>
            let currentProcessed = null;
            let currentRaw = null;
            let currentMetadata = null;
            let currentTelemetry = null;
            let currentViewMode = 'grouped';
            let currentExpandedSections = {};
            let currentFilters = {detection: 'all', label: 'all', video: 'all', source: 'all', min_conf: ''};
            let currentSortMode = 'date_desc';

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
                document.getElementById('sortControls').style.display = mode === 'flat' ? 'flex' : 'none';
                renderGallery('gallery-processed', currentProcessed, '/images/processed');
                renderGallery('gallery-raw', currentRaw, '/images/raw');
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

            function renderImageCard(imagePath, sourceMode, folder, cycleId) {
                const filename = imagePath.split('/').pop();
                const basePath = sourceMode === 'raw' ? '/images/raw' : '/images/processed';
                const summaryText = getImageSummary(folder, cycleId, filename);
                const summaryClass = summaryText && summaryText !== 'Detections: none' ? 'item-detection detected' : 'item-detection not-detected';
                const clickAction = `window.location.href='${buildEventUrl(imagePath, sourceMode)}'`;

                return `
                                    <div class="item">
                                        <div class="img-wrapper" onclick="${clickAction}">
                                            <img src="${basePath}/${imagePath}" title="Click to open event detail">
                                        </div>
                                        <span class="item-filename">${filename}</span>
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

                            // Battery status with color coding
                            if (t.battery) {
                                const batteryValue = parseFloat(t.battery.replace('Median', '').replace('%', ''));
                                const batteryColor = batteryValue < 20 ? '#e53e3e' : batteryValue < 50 ? '#dd6b20' : '#38a169';
                                teleHtml += `<span style="display: inline-flex; align-items: center; gap: 4px; background: ${batteryColor}; color: white; padding: 3px 8px; border-radius: 12px; font-size: 0.8rem; font-weight: 600;" title="Battery Level"><span>🔋</span>${t.battery.replace('Median', 'Mid')}</span>`;
                            }

                            // Signal strength with color coding
                            if (t.signal) {
                                const signalValue = parseInt(t.signal.replace('%', ''));
                                const signalColor = signalValue < 30 ? '#e53e3e' : signalValue < 70 ? '#dd6b20' : '#38a169';
                                teleHtml += `<span style="display: inline-flex; align-items: center; gap: 4px; background: ${signalColor}; color: white; padding: 3px 8px; border-radius: 12px; font-size: 0.8rem; font-weight: 600;" title="Signal Strength"><span>📶</span>${t.signal}</span>`;
                            }

                            // Temperature
                            if (t.temperature) {
                                const tempValue = parseFloat(t.temperature.split(' ')[0]);
                                const tempColor = tempValue > 60 ? '#e53e3e' : tempValue > 40 ? '#dd6b20' : '#38a169';
                                teleHtml += `<span style="display: inline-flex; align-items: center; gap: 4px; background: ${tempColor}; color: white; padding: 3px 8px; border-radius: 12px; font-size: 0.8rem; font-weight: 600;" title="Temperature"><span>🌡️</span>${t.temperature.split(' ')[0]}°C</span>`;
                            }

                            // Free space with color coding
                            if (t.free_space) {
                                const spaceMatch = t.free_space.match(/(\d+(?:\.\d+)?)\s*(GB|MB|KB|B)/i);
                                if (spaceMatch) {
                                    const spaceValue = parseFloat(spaceMatch[1]);
                                    const spaceUnit = spaceMatch[2].toUpperCase();
                                    const spaceColor = (spaceUnit === 'GB' && spaceValue < 1) || (spaceUnit === 'MB' && spaceValue < 100) ? '#e53e3e' : (spaceUnit === 'GB' && spaceValue < 2) || (spaceUnit === 'MB' && spaceValue < 500) ? '#dd6b20' : '#38a169';
                                    teleHtml += `<span style="display: inline-flex; align-items: center; gap: 4px; background: ${spaceColor}; color: white; padding: 3px 8px; border-radius: 12px; font-size: 0.8rem; font-weight: 600;" title="Free Storage"><span>💾</span>${t.free_space}</span>`;
                                }
                            }

                            // Last update time
                            if (t.updated_at) {
                                const dt = new Date(t.updated_at);
                                const now = new Date();
                                const diffMs = now - dt;
                                const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
                                const diffMins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

                                let timeColor = '#38a169'; // green for recent
                                if (diffHours > 24) timeColor = '#e53e3e'; // red for very old
                                else if (diffHours > 6) timeColor = '#dd6b20'; // orange for old

                                const fTime = `${dt.getMonth()+1}/${dt.getDate()} ${dt.getHours().toString().padStart(2, '0')}:${dt.getMinutes().toString().padStart(2, '0')}`;
                                teleHtml += `<span style="display: inline-flex; align-items: center; gap: 4px; background: ${timeColor}; color: white; padding: 3px 8px; border-radius: 12px; font-size: 0.8rem; font-weight: 600;" title="Last Update"><span>🕒</span>${fTime}</span>`;
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
                                    <div class="cycle-list">
                        `;

                        for (const cycleId of Object.keys(cycleGroups).sort().reverse()) {
                            const cycleSourceMode = defaultSourceMode;
                            const cycleImages = cycleGroups[cycleId];
                            const previewImage = cycleImages[0];
                            const cycleSectionId = `cycle-section-${containerId}-${folder.replace(/[^a-z0-9]/gi, '_')}-${cycleId.replace(/[^a-z0-9]/gi, '_')}`;
                            const isCycleExpanded = !!currentExpandedSections[cycleSectionId];

                            let labelsHtml = '';
                            if (currentMetadata && currentMetadata[`${folder}/${cycleId}`]) {
                                const meta = currentMetadata[`${folder}/${cycleId}`];
                                if (meta.labels && meta.labels.length > 0) {
                                    labelsHtml = `<span style="margin-left: 10px; font-size: 0.85em; color: #fff; background: #e53e3e; padding: 3px 10px; border-radius: 12px; font-weight: bold; letter-spacing: 0.5px;">${meta.labels.join(', ')}</span>`;
                                } else {
                                    labelsHtml = `<span style="margin-left: 10px; font-size: 0.85em; color: #718096; background: #edf2f7; padding: 3px 10px; border-radius: 12px; font-weight: bold;">No detections</span>`;
                                }
                            }

                            html += `
                                <div class="cycle-section">
                                    <div class="cycle-title" onclick="toggleSection('${cycleSectionId}')">
                                        <div class="cycle-title-main">
                                            <img src="${cycleSourceMode === 'raw' ? '/images/raw' : '/images/processed'}/${previewImage}" class="cycle-title-thumb" alt="thumb" loading="lazy">
                                            <span class="cycle-title-text">Cycle: ${cycleId}</span>
                                            <span class="badge">${cycleImages.length} images</span>
                                            ${labelsHtml}
                                        </div>
                                        <span id="${cycleSectionId}-arrow" style="font-size:1.05rem; transition: transform 0.3s; transform:${isCycleExpanded ? 'rotate(90deg)' : 'rotate(0deg)'};">▶</span>
                                    </div>
                                    <div id="${cycleSectionId}" style="display:${isCycleExpanded ? 'block' : 'none'}; overflow:hidden; transition: all 0.3s ease; padding: 20px 0;">
                            `;

                            if (currentMetadata && currentMetadata[`${folder}/${cycleId}`]) {
                                const meta = currentMetadata[`${folder}/${cycleId}`];
                                if (meta.video_paths && meta.video_paths.length > 0) {
                                    const videoPath = meta.video_paths[0];
                                    html += `
                                        <div style="text-align: center; margin-bottom: 25px;">
                                            <video controls preload="metadata" style="max-width: 100%; max-height: 450px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); background: #000;">
                                                <source src="/videos/${videoPath}">
                                            </video>
                                        </div>
                                    `;
                                }
                            }

                            html += '<div class="gallery-grid" style="margin-bottom: 10px;">';
                            for (let i = 0; i < cycleImages.length; i++) {
                                const imagePath = cycleImages[i];
                                html += renderImageCard(imagePath, cycleSourceMode, folder, cycleId);
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
                    
                    html += '<div style="max-width: 1200px; margin: 0 auto; padding: 0 20px;">';
                    
                    cycleEntries.forEach((entry, idx) => {
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
                        
                        html += `
                            <div class="flat-cycle-item">
                                <div class="flat-cycle-header" onclick="toggleSection('${flatCycleSectionId}')">
                                    <img src="${sourceMode === 'raw' ? '/images/raw' : '/images/processed'}/${previewImage}" class="flat-cycle-thumb" alt="thumb" loading="lazy">
                                    <div class="flat-cycle-info">
                                        <div class="flat-cycle-title">Cycle: ${cycleId}</div>
                                        <div class="flat-cycle-meta">
                                            <span>${cycleImages.length} images</span>
                                        </div>
                                    </div>
                                    <div class="flat-cycle-badges">
                                        <span class="flat-cycle-badge count">${cycleImages.length} images</span>
                                        <span class="flat-cycle-badge ${badgeClass}">${labelsStr}</span>
                                    </div>
                                    <span class="flat-cycle-arrow" id="${flatCycleSectionId}-arrow" style="transform:${isFlatCycleExpanded ? 'rotate(90deg)' : 'rotate(0deg)'};">▶</span>
                                </div>
                                <div id="${flatCycleSectionId}" class="flat-cycle-content${isFlatCycleExpanded ? ' open' : ''}">
                                    <div class="gallery-grid" style="margin-top: 16px;">
                        `;
                        
                        cycleImages.forEach(imagePath => {
                            const pathParts = imagePath.split('/');
                            const folder = pathParts.length > 1 ? pathParts[0] : 'Root';
                            html += renderImageCard(imagePath, sourceMode, folder, cycleId);
                        });
                        
                        html += `
                                    </div>
                                </div>
                            </div>
                        `;
                    });
                    
                    html += '</div>';
                    
                    if (cycleEntries.length === 0) {
                        html = '<div class="empty-msg">No images found yet. Captured images will appear here.</div>';
                    }
                }

                container.innerHTML = html;
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
                            renderGallery('gallery-processed', data.processed, '/images/processed');
                            renderGallery('gallery-raw', data.raw, '/images/raw');
                        }
                    } else {
                        console.error('API Error:', data.message);
                    }
                }).catch(err => {
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
    admin_link = ""
    if principal.get("role") == "admin":
        admin_link = '<a class="action-link secondary" href="/admin">Admin Settings</a>'
    html_content = html_content.replace("__ADMIN_LINK__", admin_link)
    return html_content

if __name__ == "__main__":
    import uvicorn
    server_port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=server_port)
