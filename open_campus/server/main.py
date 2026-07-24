import os
import datetime
import time
import asyncio
import logging
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Request, Header, HTTPException, status, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import aiofiles
from detector import Detector

# Load environment variables
load_dotenv()

# Configuration
# Images are saved here
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
PROCESSING_DIR = os.getenv("PROCESSING_DIR", "processing")
API_TOKEN = os.getenv("API_TOKEN", "wild-animals-token-2026")

async def verify_api_token(x_api_key: str = Header(None)):
    if x_api_key != API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Token"
        )

LOG_FILE = "server.log"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("edge_server.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PROCESSING_DIR, exist_ok=True)

detector = None

async def cleanup_old_files(days=7):
    logger.info(f"Running cleanup for files older than {days} days")
    now = time.time()
    cutoff = now - (days * 86400)
    try:
        files = os.listdir(UPLOAD_DIR)
        for f in files:
            filepath = os.path.join(UPLOAD_DIR, f)
            if os.path.isfile(filepath):
                mtime = os.path.getmtime(filepath)
                if mtime < cutoff:
                    os.remove(filepath)
                    logger.info(f"Deleted old file: {f}")
    except Exception as e:
        logger.error(f"Failed to cleanup files: {e}")

async def periodic_cleanup():
    while True:
        try:
            await cleanup_old_files()
        except Exception as e:
            logger.error(f"Periodic cleanup error: {e}")
        await asyncio.sleep(86400) # Run daily

@asynccontextmanager
async def lifespan(app: FastAPI):
    global detector
    logger.info("Initializing YOLO Detector...")
    # Initialize in background to avoid blocking startup (downloads yolov8n.pt if missing)
    detector = await asyncio.to_thread(Detector)
    logger.info("Detector initialized.")
    cleanup_task = asyncio.create_task(periodic_cleanup())
    yield
    cleanup_task.cancel()

app = FastAPI(lifespan=lifespan)

# Mount the static directory to serve images
app.mount("/images", StaticFiles(directory=UPLOAD_DIR), name="images")

# Semaphore to limit concurrent inference
# Setting to 1 ensures we process one image at a time to save resources (CPU/RAM) on Pi
processing_semaphore = asyncio.Semaphore(1)


class CycleManager:
    def __init__(self):
        # Stores cycle data: { cycle_id: { 'files': [], 'last_update': timestamp, 'start_time': float, 'timings': [] } }
        self.cycles = defaultdict(lambda: {
            'files': [], 
            'last_update': datetime.datetime.now(),
            'start_time': None,
            'timings': [] # List of dicts with timing info for each image
        })
        self.lock = asyncio.Lock()

    async def add_result(self, cycle_id, file_path, filename, is_person, confidence, timing_info):
        async with self.lock:
            cycle = self.cycles[cycle_id]
            
            # Set cycle start time if it's the first image
            if cycle['start_time'] is None:
                cycle['start_time'] = timing_info['receive_start']
            # Or keep the earliest one if images arrive out of order/parallel (though we lock)
            elif timing_info['receive_start'] < cycle['start_time']:
                cycle['start_time'] = timing_info['receive_start']

            cycle['files'].append({
                'path': file_path,
                'filename': filename,
                'is_person': is_person,
                'confidence': confidence
            })
            cycle['timings'].append(timing_info)
            cycle['last_update'] = datetime.datetime.now()
            
            files = cycle['files']
            count = len(files)
            
            # Check condition if we have 3 images
            if count >= 3:
                cycle_end_time = time.perf_counter()
                total_cycle_time = (cycle_end_time - cycle['start_time']) * 1000 # ms
                
                person_count = sum(1 for f in files if f['is_person'])
                logger.info(f"Cycle {cycle_id} complete. Detected persons: {person_count}/{count}")

                if person_count > 0:
                    best_file = max(files, key=lambda x: x['confidence'])
                    final_path = os.path.join(UPLOAD_DIR, best_file['filename'])
                    try:
                        os.rename(best_file['path'], final_path)
                        logger.info(f"Published best image to gallery: {best_file['filename']} (Conf: {best_file['confidence']:.2f})")
                    except Exception as e:
                        logger.error(f"Failed to publish {best_file['filename']}: {e}")
                else:
                    logger.info(f"No person detected in cycle {cycle_id}. Discarding cycle (no web update).")

                # Cleanup all remaining files in processing dir for this cycle
                for f in files:
                    if os.path.exists(f['path']):
                        try:
                            os.remove(f['path'])
                        except Exception as e:
                            pass
                
                # Calculate total specific times
                total_receive_save = sum(t['save_duration'] for t in cycle['timings']) * 1000 # ms
                total_inference = sum(t['inference_duration'] for t in cycle['timings']) * 1000 # ms
                
                # Cloud forwarding logic removed for local demo
                forward_duration = 0

                # Calculate Overhead/Wait time
                # Total = (Receive/Save + Inference) + Forward + Overhead
                # Note: Receive/Save happens in parallel with nothing (it's the first step), 
                # but "Wait" is the idle time between images.
                # Strictly speaking: overhead = total - (process_time_sum)
                # But process_time shares timeline. 
                # Let's define overhead as: Total - (Sum of active processing phases)
                # Active phases: Max(Receive, Inference)? No, they are sequential per image.
                # Actually, images arrive sequentially so we process them.
                # So the "Work" time is roughly sum of Receive+Inference for all images + Forward.
                # The rest is "Wait" for the next image to arrive.
                work_time = total_receive_save + total_inference + forward_duration
                wait_overhead = total_cycle_time - work_time

                # Log Performance Metrics
                logger.info(f"[PERF] Cycle {cycle_id} Finished. Total: {total_cycle_time:.0f}ms")
                logger.info(f"[PERF] Breakdown: Recv+Save={total_receive_save:.0f}ms, Infer={total_inference:.0f}ms, Fwd={forward_duration:.0f}ms, Wait/Overhead={wait_overhead:.0f}ms")

                # --- CSV Logging ---
                try:
                    csv_file = "edge_metrics.csv"
                    file_exists = os.path.isfile(csv_file)
                    async with aiofiles.open(csv_file, "a") as f:
                        if not file_exists:
                            await f.write("timestamp,cycle_id,total_time_ms,total_recv_save_ms,total_inference_ms,forward_ms,wait_overhead_ms,animal_count,forwarded\n")
                        
                        do_forward = (animal_count >= 1)
                        await f.write(f"{datetime.datetime.now().isoformat()},{cycle_id},{total_cycle_time:.0f},{total_receive_save:.0f},{total_inference:.0f},{wait_overhead:.0f},{animal_count},{do_forward}\n")
                except Exception as e:
                    logger.error(f"Failed to write to {csv_file}: {e}")
                

                
                # Cleanup
                del self.cycles[cycle_id]
            else:
                 logger.info(f"Cycle {cycle_id} buffered. Count: {count}/3")


    async def cleanup_old_cycles(self, max_age_seconds=300):
        # Potentially clean up incomplete cycles that are too old
        # Not implemented for simplicity in this phase, but good practice
        pass

cycle_manager = CycleManager()


def extract_cycle_id(original_filename: str):
    # original_filename from ESP32 is expected to be e.g. "MAC-SEQUENCE-1.jpg"
    stem = os.path.splitext(original_filename)[0]
    
    # Remove receiving timestamp prefix to ensure images from the same sequence get the identical Cycle ID
    stem = re.sub(r"^(pi|satos)_Rcv\d{6}_", "", stem)

    match = re.search(r"-(1|2|3)[nd]?$", stem)
    if match:
        return stem[:match.start()]
    return "unknown"


async def process_image(file_path: str, filename: str, original_filename: str, receive_start: float, save_duration: float):
    """
    Background task to process the image:
    1. Run object detection
    2. Add to cycle buffer
    3. Forward if cycle complete and condition met
    """
    async with processing_semaphore:
        logger.info(f"Starting processing for {filename}")
        try:
            # Measure Inference Time
            inference_start = time.perf_counter()
            # Determine save path for bounding box image
            file_root, file_ext = os.path.splitext(file_path)
            save_path = f"{file_root}_det{file_ext}"
            
            # Run detection (save_path draws bounding boxes)
            is_person, confidence = await asyncio.to_thread(detector.detect, file_path, save_path=save_path)
            inference_duration = time.perf_counter() - inference_start
            
            if os.path.exists(save_path):
                os.remove(file_path) # Delete original to avoid duplicates in gallery
                file_path = save_path
                file_name_root, _ = os.path.splitext(filename)
                filename = f"{file_name_root}_det{file_ext}"

            if is_person:
                logger.info(f"Person detected in {filename} with confidence {confidence:.2f}")
            else:
                logger.info(f"No person detected in {filename}")

            # Extract Cycle ID
            cycle_id = extract_cycle_id(original_filename)
            logger.info(f"Cycle ID for {original_filename}: {cycle_id}")
            
            timing_info = {
                'receive_start': receive_start,
                'save_duration': save_duration,
                'inference_duration': inference_duration
            }

            if cycle_id != "unknown":
                await cycle_manager.add_result(cycle_id, file_path, filename, is_person, confidence, timing_info)
            else:
                logger.warning(f"Could not extract Cycle ID from {filename}, skipping buffering.")

        except Exception as e:
            logger.error(f"Error processing {filename}: {e}")


@app.post("/upload")
async def upload_image(request: Request, background_tasks: BackgroundTasks, api_key: str = Depends(verify_api_token)):
    """
    Handle image upload (Raw Binary):
    1. Save image to disk asynchronously (fast, non-blocking)
    2. Return 200 OK immediately
    3. Schedule processing in background
    """
    receive_start = time.perf_counter()
    
    # Get filename from header
    original_filename = request.headers.get("X-File-Name")
    if not original_filename:
        # Fallback if header missing
        original_filename = "unknown.jpg"

    # Annotate with Pi edge receiving time for Cloud Server reporting
    edge_rcv_time = datetime.datetime.now().strftime("%H%M%S")
    original_filename = f"pi_Rcv{edge_rcv_time}_{original_filename}"

    # Generate timestamp for storage
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{timestamp}_{original_filename}"
    file_path = os.path.join(PROCESSING_DIR, filename)
    
    logger.info(f"Receiving upload: {filename}")
    
    try:
        # Save file asynchronously by streaming the request body
        # Use .tmp extension while writing to avoid race conditions with GET /images
        tmp_file_path = file_path + ".tmp"
        async with aiofiles.open(tmp_file_path, "wb") as buffer:
            async for chunk in request.stream():
                await buffer.write(chunk)
        
        # Rename to final filename (which makes it visible to /api/images)
        os.rename(tmp_file_path, file_path)
        
        save_end = time.perf_counter()
        save_duration = save_end - receive_start
        
        logger.info(f"Saved {filename}")
        
        # Schedule background processing
        background_tasks.add_task(process_image, file_path, filename, original_filename, receive_start, save_duration)
        
        return {"status": "ok", "filename": filename, "message": "Image received and queued for processing"}
        
    except Exception as e:
        logger.error(f"Failed to save upload {filename}: {e}")
        # Clean up tmp file if exists
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)
        return {"status": "error", "message": str(e)}

@app.get("/healthz")
async def health_check():
    """
    Health check endpoint for ESP32.
    """
    return {"status": "ok"}

@app.post("/esp_log")
async def upload_esp_log(request: Request, api_key: str = Depends(verify_api_token)):
    """
    Receive log file from ESP32 (Raw Binary).
    """
    original_filename = request.headers.get("X-File-Name")
    if not original_filename:
        original_filename = "esp.log"
        
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"esp_{timestamp}_{original_filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    logger.info(f"Receiving ESP log: {filename}")
    try:
        async with aiofiles.open(file_path, "wb") as buffer:
            async for chunk in request.stream():
                await buffer.write(chunk)
        return {"status": "ok", "message": "Log received"}
    except Exception as e:
        logger.error(f"Failed to save ESP log: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/images")
async def get_images():
    """
    Return a list of images in the upload directory, sorted by newest first.
    """
    try:
        files = [f for f in os.listdir(UPLOAD_DIR) if os.path.isfile(os.path.join(UPLOAD_DIR, f)) and f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
        # Sort by modification time descending (newest first)
        files.sort(key=lambda x: os.path.getmtime(os.path.join(UPLOAD_DIR, x)), reverse=True)
        return {"status": "ok", "images": files}
    except Exception as e:
        logger.error(f"Failed to get image list: {e}")
        return {"status": "error", "message": str(e)}

# Mount frontend static files
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
