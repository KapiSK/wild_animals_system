import os
import datetime
import time
import asyncio
import logging
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Request, Header, HTTPException, status, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import aiofiles
import httpx
from detector import Detector

# Load environment variables
load_dotenv()

# Configuration
# Images are saved here
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
# Optional: URL to forward images to (if not set in .env, forwarding is skipped)
# Optional: URL to forward images to (if not set in .env, forwarding is skipped)
MAIN_SERVER_URL = os.getenv("MAIN_SERVER_URL")
# Local Mode: If True, skips forwarding to external server
LOCAL_MODE = os.getenv("LOCAL_MODE", "False").lower() == "true"
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

# Ensure upload directory exists
os.makedirs(UPLOAD_DIR, exist_ok=True)

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
    # Initialize in background to avoid blocking startup
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

    async def add_result(self, cycle_id, file_path, filename, is_animal, timing_info):
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
                'is_animal': is_animal
            })
            cycle['timings'].append(timing_info)
            cycle['last_update'] = datetime.datetime.now()
            
            files = cycle['files']
            count = len(files)
            
            # Check condition if we have 3 images
            if count >= 3:
                cycle_end_time = time.perf_counter()
                total_cycle_time = (cycle_end_time - cycle['start_time']) * 1000 # ms
                
                animal_count = sum(1 for f in files if f['is_animal'])
                logger.info(f"Cycle {cycle_id} complete. Detected targets: {animal_count}/{count}")
                
                # Calculate total specific times
                total_receive_save = sum(t['save_duration'] for t in cycle['timings']) * 1000 # ms
                total_inference = sum(t['inference_duration'] for t in cycle['timings']) * 1000 # ms
                
                forward_start = time.perf_counter()
                if animal_count >= 1:
                    logger.info(f"Cycle {cycle_id} MET criteria (>=1 target). Forwarding all strings.")
                    await self.forward_cycle(files)
                else:
                    logger.info(f"Cycle {cycle_id} NOT met criteria. Not forwarding.")
                forward_duration = (time.perf_counter() - forward_start) * 1000 # ms

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
                        await f.write(f"{datetime.datetime.now().isoformat()},{cycle_id},{total_cycle_time:.0f},{total_receive_save:.0f},{total_inference:.0f},{forward_duration:.0f},{wait_overhead:.0f},{animal_count},{do_forward}\n")
                except Exception as e:
                    logger.error(f"Failed to write to {csv_file}: {e}")
                

                
                # Cleanup
                del self.cycles[cycle_id]
            else:
                 logger.info(f"Cycle {cycle_id} buffered. Count: {count}/3")

    async def forward_cycle(self, files):
        if LOCAL_MODE:
            logger.info("Local mode enabled. Skipping forwarding.")
            return

        if not MAIN_SERVER_URL:
             logger.info("MAIN_SERVER_URL not set, skipping forwarding.")
             return

        for file_info in files:
            await forward_image(file_info['path'], file_info['filename'])

    async def has_detected_animal(self, cycle_id):
        async with self.lock:
            if cycle_id in self.cycles:
                return any(f['is_animal'] for f in self.cycles[cycle_id]['files'])
            return False

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
            # Extract Cycle ID first
            cycle_id = extract_cycle_id(original_filename)
            logger.info(f"Cycle ID for {original_filename}: {cycle_id}")

            # Check for Early Exit
            skip_inference = False
            if cycle_id != "unknown" and await cycle_manager.has_detected_animal(cycle_id):
                logger.info(f"Early Exit: Cycle {cycle_id} already has a positive detection. Skipping inference for {filename}.")
                skip_inference = True
                is_animal = False
                label = "skipped (early exit)"

            # Measure Inference Time
            inference_start = time.perf_counter()
            if not skip_inference:
                # Run detection in background thread
                is_animal, label = await asyncio.to_thread(detector.detect, file_path, save_path=None)
                if is_animal:
                    logger.info(f"Target detected in {filename}: {label}")
                else:
                    logger.info(f"No target detected in {filename} (Result: {label})")
            
            inference_duration = time.perf_counter() - inference_start
            
            timing_info = {
                'receive_start': receive_start,
                'save_duration': save_duration,
                'inference_duration': inference_duration
            }

            if cycle_id != "unknown":
                await cycle_manager.add_result(cycle_id, file_path, filename, is_animal, timing_info)
            else:
                logger.warning(f"Could not extract Cycle ID from {filename}, skipping buffering.")

        except Exception as e:
            logger.error(f"Error processing {filename}: {e}")

async def forward_image(file_path: str, filename: str):
    """
    Forward the image to the main server
    """
    logger.info(f"Forwarding {filename} to {MAIN_SERVER_URL}")
    try:
        # verify=False is required to connect to the cloud server using a self-signed SSL certificate
        async with httpx.AsyncClient(verify=False) as client:
            # Open file asynchronously for reading
            async with aiofiles.open(file_path, "rb") as f:
                content = await f.read()
                
            files = {"file": (filename, content, "image/jpeg")}
            headers = {"X-API-KEY": API_TOKEN}
            
            # Note: External server (server.py) expects just the file and the API key header.
            response = await client.post(MAIN_SERVER_URL, files=files, headers=headers)
            response.raise_for_status()
            logger.info(f"Successfully forwarded {filename}. Status: {response.status_code}")
            
    except httpx.HTTPError as e:
        logger.error(f"Failed to forward {filename}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error forwarding {filename}: {e}")

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
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    logger.info(f"Receiving upload: {filename}")
    
    try:
        # Save file asynchronously by streaming the request body
        async with aiofiles.open(file_path, "wb") as buffer:
            async for chunk in request.stream():
                await buffer.write(chunk)
        
        save_end = time.perf_counter()
        save_duration = save_end - receive_start
        
        logger.info(f"Saved {filename}")
        
        # Schedule background processing
        background_tasks.add_task(process_image, file_path, filename, original_filename, receive_start, save_duration)
        
        return {"status": "ok", "filename": filename, "message": "Image received and queued for processing"}
        
    except Exception as e:
        logger.error(f"Failed to save upload {filename}: {e}")
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

@app.get("/gallery", response_class=HTMLResponse)
async def gallery():
    """
    Serve a simple HTML page to view the uploaded images.
    """
    html_content = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Edge Server Gallery</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
            body { font-family: 'Inter', 'Segoe UI', Tahoma, sans-serif; margin: 0; padding: 20px; background-color: #f2f7f4; color: #2d3748; }
            h1 { text-align: center; color: #1c4532; margin-bottom: 10px; font-weight: 600; letter-spacing: -0.5px; font-size: 2.2rem; }
            h2 { color: #276749; font-weight: 500; font-size: 1.2rem; margin-bottom: 20px; text-align: center; }
            .header-accent { display: block; width: 60px; height: 4px; background: #38a169; margin: 0 auto 40px auto; border-radius: 2px; }
            .latest-container { margin: 0 auto 50px auto; max-width: 900px; text-align: center; }
            .latest-item { background: #ffffff; border-radius: 16px; box-shadow: 0 20px 40px rgba(39, 103, 73, 0.08); overflow: hidden; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 0; border: 1px solid #e2e8f0; transition: transform 0.3s ease, box-shadow 0.3s ease; }
            .latest-item:hover { transform: translateY(-5px); box-shadow: 0 25px 50px rgba(39, 103, 73, 0.12); }
            .latest-item img { width: 100%; max-height: 550px; object-fit: contain; cursor: pointer; background: #f8fafc; border-bottom: 1px solid #edf2f7; }
            .latest-item span { padding: 18px; font-size: 15px; color: #4a5568; font-weight: 500; word-break: break-all; width: 100%; box-sizing: border-box; }
            .gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 24px; max-width: 1200px; margin: 0 auto; padding: 0 20px; }
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
        <h1>Edge Server Gallery</h1>
        <div class="header-accent"></div>
        <div id="gallery-wrapper"></div>
        <script>
            let currentImages = null;

            function arraysEqual(a, b) {
                if (a === b) return true;
                if (a == null || b == null) return false;
                if (a.length !== b.length) return false;
                for (let i = 0; i < a.length; ++i) {
                    if (a[i] !== b[i]) return false;
                }
                return true;
            }

            function fetchImages() {
                fetch('/api/images')
                    .then(response => response.json())
                    .then(data => {
                        const wrapper = document.getElementById('gallery-wrapper');
                        if (data.status === 'ok' && data.images && data.images.length > 0) {
                            if (arraysEqual(currentImages, data.images)) {
                                return; // No changes
                            }
                            currentImages = data.images;
                            const images = data.images;
                            const latestImg = images[0];
                            
                            let html = `
                                <div class="latest-container">
                                    <h2>Latest Capture</h2>
                                    <div class="latest-item">
                                        <img src="/images/${latestImg}" title="クリックしてフルサイズの画像を表示" onclick="window.open(this.src, '_blank')">
                                        <span>${latestImg}</span>
                                    </div>
                                </div>
                            `;
                            
                            if (images.length > 1) {
                                html += '<div class="gallery">';
                                for (let i = 1; i < images.length; i++) {
                                    html += `
                                        <div class="item">
                                            <div class="img-wrapper" onclick="window.open('/images/${images[i]}', '_blank')">
                                                <img src="/images/${images[i]}" title="クリックしてフルサイズの画像を表示">
                                            </div>
                                            <span>${images[i]}</span>
                                        </div>
                                    `;
                                }
                                html += '</div>';
                            }
                            
                            wrapper.innerHTML = html;
                        } else {
                            wrapper.innerHTML = '<div class="empty-msg">画像が見つかりません。カメラで撮影された画像がここに表示されます。</div>';
                        }
                    })
                    .catch(err => {
                        document.getElementById('gallery-wrapper').innerHTML = '<div class="empty-msg" style="color:#e53e3e;">エラーが発生しました: ' + err.message + '</div>';
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
