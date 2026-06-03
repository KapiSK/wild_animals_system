#!/usr/bin/env python3
from __future__ import annotations

import email
import imaplib
import logging
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path
from typing import Optional, Sequence, Set, Tuple

MOV_MIME_TYPES = {"video/quicktime"}
MOV_EXTENSIONS = {".mov"}
DEFAULT_FILE_NAME_TEMPLATE = "{date}_{uid}_{part}_{filename}"
DEFAULT_FRAME_CAPTURE_OFFSETS_SECONDS = (0, 1, 2)
DEFAULT_FRAME_IMAGE_FORMAT = "jpg"


class ShutdownRequested(Exception):
    pass


@dataclass
class Config:
    gmail_address: str
    gmail_app_password: str
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_folder: str = "INBOX"
    imap_readonly: bool = False
    mark_as_seen_on_success: bool = True
    poll_interval_seconds: int = 60
    search_criteria: str = "UNSEEN"
    save_dir: Path = Path("./saved_videos")
    frame_save_dir: Path = Path("./saved_frames")
    state_file: Path = Path("./state.json")
    file_name_template: str = DEFAULT_FILE_NAME_TEMPLATE
    create_sender_subdir: bool = False
    log_level: str = "INFO"
    ffmpeg_path: str = "ffmpeg"
    frame_capture_offsets_seconds: Tuple[int, ...] = DEFAULT_FRAME_CAPTURE_OFFSETS_SECONDS
    frame_image_format: str = DEFAULT_FRAME_IMAGE_FORMAT
    cloud_server_url: str = ""
    cloud_api_key: str = "wild-animals-token-2026"
    enable_local_yolo: bool = True

    @staticmethod
    def _get_bool(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}

    @staticmethod
    def _get_int(name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None or raw.strip() == "":
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer: {raw!r}") from exc
        if value <= 0:
            raise ValueError(f"{name} must be > 0: {value}")
        return value

    @staticmethod
    def _parse_offsets(raw: str) -> Tuple[int, ...]:
        if not raw.strip():
            return DEFAULT_FRAME_CAPTURE_OFFSETS_SECONDS
        values = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                value = int(token)
            except ValueError as exc:
                raise ValueError(
                    f"FRAME_CAPTURE_OFFSETS_SECONDS must be comma-separated integers: {raw!r}"
                ) from exc
            if value < 0:
                raise ValueError(
                    f"FRAME_CAPTURE_OFFSETS_SECONDS cannot contain negative values: {raw!r}"
                )
            values.append(value)
        if not values:
            raise ValueError("FRAME_CAPTURE_OFFSETS_SECONDS must contain at least one value")
        return tuple(values)

    @classmethod
    def from_env(cls) -> "Config":
        gmail_address = os.getenv("GMAIL_ADDRESS", "").strip()
        gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip().replace(" ", "")
        if not gmail_address:
            raise ValueError("GMAIL_ADDRESS is required")
        if not gmail_app_password:
            raise ValueError("GMAIL_APP_PASSWORD is required")

        frame_image_format = (
            os.getenv("FRAME_IMAGE_FORMAT", DEFAULT_FRAME_IMAGE_FORMAT).strip().lower()
            or DEFAULT_FRAME_IMAGE_FORMAT
        )
        if frame_image_format not in {"jpg", "jpeg", "png"}:
            raise ValueError("FRAME_IMAGE_FORMAT must be one of: jpg, jpeg, png")

        config = cls(
            gmail_address=gmail_address,
            gmail_app_password=gmail_app_password,
            imap_host=os.getenv("IMAP_HOST", "imap.gmail.com").strip() or "imap.gmail.com",
            imap_port=cls._get_int("IMAP_PORT", 993),
            imap_folder=os.getenv("IMAP_FOLDER", "INBOX").strip() or "INBOX",
            imap_readonly=cls._get_bool("IMAP_READONLY", False),
            mark_as_seen_on_success=cls._get_bool("MARK_AS_SEEN_ON_SUCCESS", True),
            poll_interval_seconds=cls._get_int("POLL_INTERVAL_SECONDS", 60),
            search_criteria=os.getenv("SEARCH_CRITERIA", "UNSEEN").strip() or "UNSEEN",
            save_dir=Path(os.getenv("SAVE_DIR", "./saved_videos")).expanduser(),
            frame_save_dir=Path(os.getenv("FRAME_SAVE_DIR", "./saved_frames")).expanduser(),
            state_file=Path(os.getenv("STATE_FILE", "./state.json")).expanduser(),
            file_name_template=os.getenv("FILE_NAME_TEMPLATE", DEFAULT_FILE_NAME_TEMPLATE),
            create_sender_subdir=cls._get_bool("CREATE_SENDER_SUBDIR", False),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg").strip() or "ffmpeg",
            frame_capture_offsets_seconds=cls._parse_offsets(
                os.getenv(
                    "FRAME_CAPTURE_OFFSETS_SECONDS",
                    ",".join(str(x) for x in DEFAULT_FRAME_CAPTURE_OFFSETS_SECONDS),
                )
            ),
            frame_image_format=frame_image_format,
            cloud_server_url=os.getenv("CLOUD_SERVER_URL", "").strip(),
            cloud_api_key=os.getenv("CLOUD_SERVER_API_KEY", "wild-animals-token-2026").strip(),
            enable_local_yolo=cls._get_bool("ENABLE_LOCAL_YOLO", True),
        )

        if config.imap_readonly and config.mark_as_seen_on_success:
            logging.warning(
                "IMAP_READONLY=true is incompatible with MARK_AS_SEEN_ON_SUCCESS=true. "
                "Opening folder in read-write mode."
            )
            config.imap_readonly = False

        return config


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.uidvalidity: Optional[str] = None
        self.processed_uids: Set[str] = set()
        self.failed_uids: Set[str] = set()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            import json

            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            logging.exception("Failed to load state file. Starting with empty state.")
            return
        self.uidvalidity = data.get("uidvalidity")
        raw_uids = data.get("processed_uids", [])
        if isinstance(raw_uids, list):
            self.processed_uids = {str(x) for x in raw_uids}
        raw_failed = data.get("failed_uids", [])
        if isinstance(raw_failed, list):
            self.failed_uids = {str(x) for x in raw_failed}

    def save(self) -> None:
        import json

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "uidvalidity": self.uidvalidity,
            "processed_uids": sorted(self.processed_uids, key=_sort_uid),
            "failed_uids": sorted(self.failed_uids, key=_sort_uid),
            "updated_at": datetime.now().isoformat(),
        }
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)

    def reset_for_uidvalidity(self, uidvalidity: Optional[str]) -> None:
        if uidvalidity != self.uidvalidity:
            logging.info(
                "UIDVALIDITY changed (%s -> %s). Clearing processed UID state.",
                self.uidvalidity,
                uidvalidity,
            )
            self.uidvalidity = uidvalidity
            self.processed_uids.clear()
            self.failed_uids.clear()
            self.save()


class GmailMovProcessor:
    def __init__(self, config: Config):
        self.config = config
        self.state = StateStore(config.state_file)
        self.state.load()
        self.client: Optional[imaplib.IMAP4_SSL] = None
        self._running = True
        self.ffmpeg_path = resolve_ffmpeg_path(config.ffmpeg_path)
        
        self.video_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._worker_loop, name="VideoWorker", daemon=True)
        
        self.model = None
        self.target_classes = [0, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
        if self.config.cloud_server_url and self.config.enable_local_yolo:
            try:
                from ultralytics import YOLO
                logging.info("Loading YOLOv8n model...")
                self.model = YOLO("yolov8n.pt")
                logging.info("Model loaded successfully.")
            except ImportError as e:
                logging.error("ultralytics module not found. Check requirements.txt: %s", e)

    def stop(self, *_args) -> None:
        logging.info("Shutdown requested.")
        self._running = False
        self.video_queue.put(None)  # Signal worker to stop

    def run_forever(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        self.config.save_dir.mkdir(parents=True, exist_ok=True)
        self.config.frame_save_dir.mkdir(parents=True, exist_ok=True)

        self.worker_thread.start()
        consecutive_errors = 0

        while self._running:
            try:
                self.ensure_connected()
                self.poll_once()
                consecutive_errors = 0
                self._sleep_with_interrupt(self.config.poll_interval_seconds)
            except ShutdownRequested:
                break
            except KeyboardInterrupt:
                break
            except Exception as e:
                consecutive_errors += 1
                backoff = min(self.config.poll_interval_seconds * (2 ** (consecutive_errors - 1)), 600)
                logging.exception("Error in main loop: %s. Retrying after %d seconds.", e, backoff)
                self.close_client()
                self._sleep_with_interrupt(int(backoff))

        self.close_client()
        if self.worker_thread.is_alive():
            logging.info("Waiting for worker thread to finish remaining tasks...")
            self.worker_thread.join(timeout=30.0)
        logging.info("Stopped.")

    def _sleep_with_interrupt(self, seconds: int) -> None:
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        if not self._running:
            raise ShutdownRequested

    def ensure_connected(self) -> None:
        if self.client is not None:
            return

        client = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port)
        client.login(self.config.gmail_address, self.config.gmail_app_password)
        status, _ = client.select(self.config.imap_folder, readonly=self.config.imap_readonly)
        if status != "OK":
            raise RuntimeError(f"Failed to select mailbox: {self.config.imap_folder}")

        uidvalidity = self._get_uidvalidity(client)
        self.state.reset_for_uidvalidity(uidvalidity)
        self.client = client
        logging.info(
            "Connected to IMAP server %s:%s folder=%s readonly=%s",
            self.config.imap_host,
            self.config.imap_port,
            self.config.imap_folder,
            self.config.imap_readonly,
        )

    def close_client(self) -> None:
        if self.client is None:
            return
        try:
            try:
                self.client.close()
            except Exception:
                pass
            self.client.logout()
        except Exception:
            pass
        finally:
            self.client = None

    def poll_once(self) -> None:
        assert self.client is not None
        # Re-SELECT mailbox on every poll to ensure Gmail returns newly arrived messages.
        # Without this, the IMAP session uses a stale snapshot and misses new emails.
        sel_status, _ = self.client.select(self.config.imap_folder, readonly=self.config.imap_readonly)
        if sel_status != "OK":
            raise RuntimeError(f"Re-SELECT of mailbox failed: {sel_status!r}")

        status, response = self.client.uid("SEARCH", None, self.config.search_criteria)
        if status != "OK":
            raise RuntimeError(f"SEARCH failed: {response!r}")

        uid_bytes = response[0] if response else b""
        raw_uids = uid_bytes.decode("utf-8", errors="replace").strip()
        if not raw_uids:
            logging.debug("No matching messages.")
            return

        uids = [uid for uid in raw_uids.split() if uid]
        logging.debug("Matched UIDs: %s", ", ".join(uids))

        for uid in uids:
            if not self._running:
                raise ShutdownRequested
            if uid in self.state.processed_uids:
                if self.config.search_criteria == "UNSEEN" and self.config.mark_as_seen_on_success:
                    if uid not in self.state.failed_uids:
                        logging.info("UID=%s was successfully processed before but is now UNSEEN. Re-processing.", uid)
                    else:
                        continue
                else:
                    continue
            try:
                self._process_message(uid)
                self.state.processed_uids.add(uid)
                self.state.failed_uids.discard(uid)
            except Exception:
                logging.exception("Failed to process UID=%s. Skipping to avoid infinite retry.", uid)
                self.state.processed_uids.add(uid)
                self.state.failed_uids.add(uid)
            finally:
                # Always save state so we don't retry endlessly on next start
                self.state.save()

    def _process_message(self, uid: str) -> None:
        assert self.client is not None
        status, fetch_data = self.client.uid("FETCH", uid, "(RFC822)")
        if status != "OK":
            raise RuntimeError(f"FETCH failed for UID {uid}: {fetch_data!r}")

        raw_message = self._extract_rfc822(fetch_data)
        if raw_message is None:
            raise RuntimeError(f"RFC822 payload missing for UID {uid}")

        msg = email.message_from_bytes(raw_message)
        subject = decode_mime_header(msg.get("Subject")) or "(no subject)"
        sender = decode_mime_header(msg.get("From")) or "unknown"
        logging.info("Processing UID=%s Subject=%s From=%s", uid, subject, sender)

        email_body = ""
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                payload = part.get_payload(decode=True)
                if payload:
                    try:
                        email_body += payload.decode(errors="ignore")
                    except Exception:
                        pass
        
        telemetry = {}
        if email_body:
            import re as _re
            clean_body = _re.sub(r'<[^>]+>', ' ', email_body).replace('&nbsp;', ' ')
            sig = _re.search(r"Signal:\s*(.*)", clean_body, _re.IGNORECASE)
            bat = _re.search(r"Battery:\s*(.*)", clean_body, _re.IGNORECASE)
            temp = _re.search(r"Temperature:\s*(.*)", clean_body, _re.IGNORECASE)
            f_space = _re.search(r"Free space:\s*(.*)", clean_body, _re.IGNORECASE)
            t_space = _re.search(r"Total space:\s*(.*)", clean_body, _re.IGNORECASE)
            imei = _re.search(r"IMEI/MEID:\s*(.*)", clean_body, _re.IGNORECASE)
            
            if sig: telemetry['signal'] = sig.group(1).strip()
            if bat: telemetry['battery'] = bat.group(1).strip()
            if temp: telemetry['temperature'] = temp.group(1).strip()
            if f_space: telemetry['free_space'] = f_space.group(1).strip()
            if t_space: telemetry['total_space'] = t_space.group(1).strip()
            if imei: telemetry['imei'] = imei.group(1).strip()

        saved_videos = 0
        for part_index, part in enumerate(msg.walk(), start=1):
            saved_path = self._maybe_save_mov_part(uid, msg, part, part_index)
            if saved_path:
                self.video_queue.put((uid, saved_path, telemetry))
                saved_videos += 1

        if saved_videos == 0:
            logging.info("UID=%s contained no MOV attachments.", uid)
            return

        logging.info("UID=%s queued %d MOV attachment(s) for processing.", uid, saved_videos)
        if self.config.mark_as_seen_on_success:
            self._mark_seen(uid)

    def _maybe_save_mov_part(self, uid: str, msg: Message, part: Message, part_index: int) -> Optional[Path]:
        content_type = (part.get_content_type() or "").lower()
        disposition = (part.get_content_disposition() or "").lower()
        filename = decode_mime_header(part.get_filename()) if part.get_filename() else None
        extension = Path(filename).suffix.lower() if filename else ""

        is_mov = content_type in MOV_MIME_TYPES or extension in MOV_EXTENSIONS
        is_attachmentish = disposition == "attachment" or filename is not None
        if not (is_mov and is_attachmentish):
            return False

        payload = part.get_payload(decode=True)
        if not payload:
            logging.warning("UID=%s part=%s had empty MOV payload.", uid, part_index)
            return False

        msg_date = parse_message_date(msg.get("Date"))
        sender = sanitize_filename(extract_sender(msg.get("From")))
        safe_original_filename = sanitize_filename(filename or f"part-{part_index}.mov")

        formatted_name = self.config.file_name_template.format(
            date=msg_date,
            uid=uid,
            part=part_index,
            filename=safe_original_filename,
            sender=sender,
        )
        formatted_name = sanitize_filename(ensure_suffix(formatted_name, ".mov"))

        target_dir = self.config.save_dir
        if self.config.create_sender_subdir and sender:
            target_dir = target_dir / sender
        target_dir.mkdir(parents=True, exist_ok=True)

        destination = deduplicate_path(target_dir / formatted_name)
        with destination.open("wb") as f:
            f.write(payload)
        logging.info("Saved MOV attachment: %s", destination)

        return destination

    def _worker_loop(self) -> None:
        logging.info("Worker thread started.")
        while self._running or not self.video_queue.empty():
            try:
                # Block with timeout to periodically check exit signal
                item = self.video_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            
            if item is None:
                # Termination signal received
                self.video_queue.task_done()
                break
            
            if isinstance(item, tuple) and len(item) == 3:
                uid, video_path, telemetry = item
            elif isinstance(item, tuple) and len(item) == 2:
                uid = "unknown"
                video_path, telemetry = item
            else:
                uid = "unknown"
                video_path = item
                telemetry = {}

            try:
                logging.info("[Worker] Starting processing for %s", video_path)
                self._extract_frames(uid, video_path, telemetry)
                logging.info("[Worker] Finished processing for %s", video_path)
            except Exception:
                logging.exception("[Worker] Unhandled error while processing %s", video_path)
            finally:
                self.video_queue.task_done()
        
        logging.info("Worker thread stopped.")

    def _extract_frames(self, uid: str, video_path: Path, telemetry: dict = None) -> None:
        video_stem = sanitize_filename(video_path.stem)
        #frame_dir = self.config.frame_save_dir / video_stem
        frame_dir = self.config.frame_save_dir
        frame_dir.mkdir(parents=True, exist_ok=True)

        extracted_frames = []

        for index, offset in enumerate(self.config.frame_capture_offsets_seconds, start=1):
            frame_name = f"{video_stem}_frame_{index:02d}_{offset:02d}s.{self.config.frame_image_format}"
            frame_path = deduplicate_path(frame_dir / frame_name)
            cmd = [
                self.ffmpeg_path,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                str(offset),
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                str(frame_path),
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "").strip()
                raise RuntimeError(
                    f"ffmpeg frame extraction failed for {video_path} at {offset}s: {stderr}"
                ) from exc
            if not frame_path.exists() or frame_path.stat().st_size == 0:
                raise RuntimeError(f"ffmpeg did not produce frame file: {frame_path}")
            logging.info("Saved frame: %s", frame_path)
            extracted_frames.append((frame_path, index))

        if self.config.cloud_server_url:
            should_forward = False
            
            if self.config.enable_local_yolo and self.model:
                for frame_path, _ in extracted_frames:
                    try:
                        results = self.model(str(frame_path), verbose=False)
                        for result in results:
                            for box in result.boxes:
                                if int(box.cls[0]) in self.target_classes:
                                    should_forward = True
                                    break
                            if should_forward:
                                break
                    except Exception as e:
                        logging.error("YOLO inference failed on %s: %s", frame_path, e)
                    
                    if should_forward:
                        break
            else:
                # Bypass inference and forward directly
                should_forward = True

            if should_forward:
                logging.info("Criteria met for cycle %s. Forwarding...", video_stem)
                self._upload_to_cloud_server(uid, video_stem, video_path, extracted_frames, telemetry)
            else:
                logging.info("No targets detected in cycle %s. Skipping upload.", video_stem)

    def _upload_to_cloud_server(self, uid: str, video_stem: str, video_path: Path, frames: Sequence[Tuple[Path, int]], telemetry: dict = None) -> None:
        import requests
        import urllib3
        from datetime import datetime

        # Suppress insecure request warnings for self-signed certs
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        url = self.config.cloud_server_url
        logging.info("Starting upload of %d frames to cloud server: %s", len(frames), url)

        edge_rcv_time = datetime.now().strftime("%H%M%S")

        # Extract true camera ID and sequence from video_stem.
        # Supported formats:
        #   KD1_000121  → underscore separator (legacy)
        #   KD1X000121  → X separator (for cameras that can't use special chars)
        import re as _re
        # Remove trailing deduplication suffix if present (e.g. _1, _2)
        stem_for_cam = _re.sub(r'_\d+$', '', video_stem)

        _x_match = _re.match(r'^(.+?)X(\d+)$', stem_for_cam)
        _us_parts = stem_for_cam.rsplit("_", 1)

        if _x_match:
            cam_id = _x_match.group(1)
        elif len(_us_parts) == 2 and _us_parts[1].isdigit():
            cam_id = _us_parts[0]
        else:
            cam_id = stem_for_cam
            
        # Use email UID to guarantee unique sequence for cloud grouping
        seq = uid

        event_id = f"{cam_id}_{seq}"
        
        base_api_url = self.config.cloud_server_url.split("/upload")[0]

        if telemetry and base_api_url:
            telemetry_url = base_api_url.rstrip("/") + "/api/telemetry"
            telemetry_payload = {
                "camera_id": cam_id,
                **telemetry
            }
            try:
                t_resp = requests.post(telemetry_url, json=telemetry_payload, headers={"X-API-KEY": self.config.cloud_api_key}, verify=False, timeout=10)
                if t_resp.status_code == 200:
                    logging.info("Uploaded telemetry for %s", cam_id)
                else:
                    logging.warning("Telemetry upload returned status %s for %s", t_resp.status_code, cam_id)
            except Exception as e:
                logging.error("Failed to upload telemetry for %s: %s", cam_id, e)

        for frame_path, index in frames:
            x_file_name = f"satos_Rcv{edge_rcv_time}_{cam_id}-{seq}-{index}.{self.config.frame_image_format}"
            try:
                with frame_path.open("rb") as f:
                    files = {"file": (x_file_name, f, "image/jpeg")}
                    headers = {"X-API-KEY": self.config.cloud_api_key}
                    
                    resp = requests.post(url, files=files, headers=headers, verify=False, timeout=30)
                    
                    if resp.status_code == 200:
                        logging.info("Uploaded %s to cloud server.", x_file_name)
                    else:
                        logging.warning("Cloud server returned status %s for %s", resp.status_code, x_file_name)
            except Exception as e:
                logging.error("Failed to upload %s to cloud server: %s", x_file_name, e)

        video_upload_url = base_api_url.rstrip("/") + "/upload_video"
        try:
            with video_path.open("rb") as f:
                files = {"file": (video_path.name, f, "video/quicktime")}
                headers = {
                    "X-API-KEY": self.config.cloud_api_key,
                    "X-EVENT-ID": event_id,
                    "X-CAMERA-ID": cam_id,
                    "X-SEQUENCE": seq,
                }
                resp = requests.post(video_upload_url, files=files, headers=headers, verify=False, timeout=120)
                if resp.status_code == 200:
                    logging.info("Uploaded source video %s for event %s.", video_path.name, event_id)
                else:
                    logging.warning("Video upload returned status %s for event %s", resp.status_code, event_id)
        except Exception as e:
            logging.error("Failed to upload source video %s: %s", video_path, e)

    def _mark_seen(self, uid: str) -> None:
        assert self.client is not None
        status, response = self.client.uid("STORE", uid, "+FLAGS.SILENT", r"(\Seen)")
        if status != "OK":
            raise RuntimeError(f"Failed to mark UID {uid} as read: {response!r}")
        logging.info(r"Marked UID=%s as read (\Seen).", uid)

    @staticmethod
    def _extract_rfc822(fetch_data) -> Optional[bytes]:
        for item in fetch_data:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                return bytes(item[1])
        return None

    @staticmethod
    def _get_uidvalidity(client: imaplib.IMAP4_SSL) -> Optional[str]:
        status, response = client.response("UIDVALIDITY")
        if status == "OK" and response:
            raw = response[0]
            if isinstance(raw, bytes):
                return raw.decode("utf-8", errors="replace")
            return str(raw)
        return None


def resolve_ffmpeg_path(configured_path: str) -> str:
    configured_path = configured_path.strip()
    if configured_path:
        if os.path.isabs(configured_path) and os.access(configured_path, os.X_OK):
            return configured_path
        found = shutil.which(configured_path)
        if found:
            return found
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError(
            "ffmpeg was not found. Install ffmpeg, set FFMPEG_PATH, or install imageio-ffmpeg."
        ) from exc


def decode_mime_header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return value.strip()


_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_WHITESPACE = re.compile(r'\s+')
_EMAIL_RE = re.compile(r'<([^>]+)>')


def sanitize_filename(name: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name).strip(" .")
    cleaned = _WHITESPACE.sub("_", cleaned)
    return cleaned[:240] or "file"


def extract_sender(from_header: Optional[str]) -> str:
    if not from_header:
        return "unknown"
    match = _EMAIL_RE.search(from_header)
    if match:
        return match.group(1)
    return from_header


def ensure_suffix(name: str, suffix: str) -> str:
    if name.lower().endswith(suffix.lower()):
        return name
    return f"{name}{suffix}"


def parse_message_date(date_header: Optional[str]) -> str:
    if not date_header:
        return datetime.now().strftime("%Y%m%d")
    try:
        dt = email.utils.parsedate_to_datetime(date_header)
        return dt.strftime("%Y%m%d")
    except Exception:
        return datetime.now().strftime("%Y%m%d")


def deduplicate_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _sort_uid(value: str) -> Tuple[int, str]:
    return (0, value) if not value.isdigit() else (1, f"{int(value):020d}")


def configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
    )


def main() -> int:
    try:
        config = Config.from_env()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    configure_logging(config.log_level)
    logging.info("Starting Gmail MOV saver.")
    try:
        processor = GmailMovProcessor(config)
    except Exception:
        logging.exception("Initialization failed.")
        return 2
    processor.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
