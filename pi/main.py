import os
import datetime
import asyncio
import logging
import re
from collections import defaultdict
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
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
MAIN_SERVER_URL = os.getenv("MAIN_SERVER_URL")

LOG_FILE = "server.log"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Ensure upload directory exists
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI()
detector = Detector()

# Semaphore to limit concurrent inference
# Setting to 1 ensures we process one image at a time to save resources (CPU/RAM) on Pi
processing_semaphore = asyncio.Semaphore(1)


class CycleManager:
    def __init__(self):
        # Stores cycle data: { cycle_id: { 'files': [{'path': str, 'filename': str, 'is_animal': bool}], 'last_update': timestamp } }
        self.cycles = defaultdict(lambda: {'files': [], 'last_update': datetime.datetime.now()})
        self.lock = asyncio.Lock()

    async def add_result(self, cycle_id, file_path, filename, is_animal):
        async with self.lock:
            self.cycles[cycle_id]['files'].append({
                'path': file_path,
                'filename': filename,
                'is_animal': is_animal
            })
            self.cycles[cycle_id]['last_update'] = datetime.datetime.now()
            
            files = self.cycles[cycle_id]['files']
            count = len(files)
            
            # Check condition if we have 3 images
            if count >= 3:
                animal_count = sum(1 for f in files if f['is_animal'])
                logger.info(f"Cycle {cycle_id} complete. Detected animals: {animal_count}/{count}")
                
                if animal_count >= 2:
                    logger.info(f"Cycle {cycle_id} MET criteria (>=2 animals). Forwarding all strings.")
                    await self.forward_cycle(files)
                else:
                    logger.info(f"Cycle {cycle_id} NOT met criteria. Not forwarding.")
                
                # Cleanup
                del self.cycles[cycle_id]
            else:
                 logger.info(f"Cycle {cycle_id} buffered. Count: {count}/3")

    async def forward_cycle(self, files):
        if not MAIN_SERVER_URL:
             logger.info("MAIN_SERVER_URL not set, skipping forwarding.")
             return

        for file_info in files:
            await forward_image(file_info['path'], file_info['filename'])

    async def cleanup_old_cycles(self, max_age_seconds=300):
        # Potentially clean up incomplete cycles that are too old
        # Not implemented for simplicity in this phase, but good practice
        pass

cycle_manager = CycleManager()


def extract_cycle_id(filename: str):
    # Expected filename formats from upload:
    # "TIMESTAMP_{CycleID}-{Index}{Suffix}.jpg" e.g. "20250101_120000_MAC123-1.jpg"
    # or just "{CycleID}-{Index}.jpg" if not prefixed (but our upload prepends timestamp)
    # Strategy: Look for the pattern containing the CycleID.
    # CycleID usually looks like "MAC-SEQ" or similar.
    # Filename on ESP32: "{CycleID}-{Index}.jpg"
    # CycleID = "MAC-SEQUENCE"
    # e.g. "AABBCCDDEEFF-00000001-1.jpg"
    # Just split by last '-'?
    # Cycle ID might contain dashes (MAC address).
    # The suffix is "-{1,2,3}{n,d}.jpg"
    # So we want everything before the last dash (that precedes the index).
    
    # Remove the timestamp prefix first (YYYYMMDD_HHMMSS_ffffff_)
    # 26 chars? 
    # Let's rely on finding the "-{Index}" pattern at the end.
    
    # Remove extension
    stem = os.path.splitext(filename)[0]
    
    # Finding the index part: "-1", "-2", "-3" optionally followed by "n" or "d"
    # Regex: r"-(1|2|3)[nd]?$"
    match = re.search(r"-(1|2|3)[nd]?$", stem)
    if match:
        # The Cycle ID is everything before this match
        # But wait, main.py PREPENDS timestamp "TIMESTAMP_"
        # We should iterate past the timestamp if present.
        # CycleID starts after the first few underscores?
        # Actually, CycleID itself is unique.
        
        # If we take everything before the index, it includes the timestamp.
        # "20250101_..._MAC-001-1" -> ID "20250101_..._MAC-001"
        # Is this ID unique per cycle? Yes, definitely.
        # Is it the SAME for all 3 images of the cycle? 
        # The timestamp is generated at UPLOAD receive time.
        # If 3 images are uploaded in separate requests, they get DIFFERENT timestamps!
        # CRITICAL ISSUE: We cannot use the prepended timestamp as part of the Cycle ID.
        # We MUST extract the original Cycle ID from the filename.
        
        # The original filename is after the FIRST "timestamp_" block.
        # The code does: `filename = f"{timestamp}_{file.filename}"`
        # file.filename is what ESP32 sent.
        # So we just need to parse `file.filename`.
        # However, `process_image` receives `filename` (the full saved one).
        # We can reconstruct or parse.
        
        # Let's strip the timestamp prefix we added. 
        # It's fixed length? "YYYYMMDD_HHMMSS_%f" -> 15+1+6+1+6 = ~29 chars.
        # Format: "%Y%m%d_%H%M%S_%f" -> 8+1+6+1+6 = 22 chars?
        # Let's just look for the `_` separator? The user might upload files with underscores.
        # Safe bet: We know `file.filename` is passed to `upload_image`. 
        # Just pass `file.filename` (original) to `process_image` too? 
        # Yes, let's modify `upload_image` to pass `original_filename` or parsing logic.
        
        # Better: Extract the CycleID from the *end* of the string, ignoring the timestamp prefix.
        # ESP32 Filename: `[CycleID]-[Index][Suffix].jpg`
        # We need `[CycleID]`.
        # So we look for the suffix match, and take the string before it, 
        # AND remove the timestamp prefix?
        # If we just group by "everything before suffix", and the timestamp differs, we fail to group.
        # SO: We MUST strip the timestamp.
        
        parts = filename.split('_', 3) # Split by underscores
        # timestamp format has 2 underscores? 20250101_120000_123456_Original.jpg
        # Wait, strftime("%Y%m%d_%H%M%S_%f") -> 20230101_120000_123456
        # So it creates "DATE_TIME_MS_OriginalFilename".
        # So 3 splits.
        if len(parts) >= 4:
            original_filename = parts[3]
            stem_orig = os.path.splitext(original_filename)[0]
            match_orig = re.search(r"-(1|2|3)[nd]?$", stem_orig)
            if match_orig:
                 return stem_orig[:match_orig.start()]
        
    return "unknown"


async def process_image(file_path: str, filename: str):
    """
    Background task to process the image:
    1. Run object detection
    2. Add to cycle buffer
    3. Forward if cycle complete and condition met
    """
    async with processing_semaphore:
        logger.info(f"Starting processing for {filename}")
        try:
            # Define path for saving the inference result (annotated image)
            # Not strictly required to save annotated image on Pi if we just filter,
            # but good for debugging.
            result_filename = f"{os.path.splitext(filename)[0]}_result.jpg"
            result_path = os.path.join(UPLOAD_DIR, result_filename)

            # Run detection
            is_animal, label = await asyncio.to_thread(detector.detect, file_path, result_path)
            if is_animal:
                logger.info(f"Animal detected in {filename}: {label}")
            else:
                logger.info(f"No animal detected in {filename}")

            # Extract Cycle ID
            cycle_id = extract_cycle_id(filename)
            logger.info(f"Cycle ID for {filename}: {cycle_id}")
            
            if cycle_id != "unknown":
                await cycle_manager.add_result(cycle_id, file_path, filename, is_animal)
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
        async with httpx.AsyncClient() as client:
            # Open file asynchronously for reading
            async with aiofiles.open(file_path, "rb") as f:
                content = await f.read()
                
            files = {"file": (filename, content, "image/jpeg")}
            
            # Note: External server (server.py) expects just the file.
            response = await client.post(MAIN_SERVER_URL, files=files)
            response.raise_for_status()
            logger.info(f"Successfully forwarded {filename}. Status: {response.status_code}")
            
    except httpx.HTTPError as e:
        logger.error(f"Failed to forward {filename}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error forwarding {filename}: {e}")

@app.post("/upload")
async def upload_image(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    Handle image upload:
    1. Save image to disk asynchronously (fast, non-blocking)
    2. Return 200 OK immediately
    3. Schedule processing in background
    """
    # Generate timestamp for storage, but we must handle it in CycleID extraction
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    logger.info(f"Receiving upload: {filename}")
    
    try:
        # Save file asynchronously
        async with aiofiles.open(file_path, "wb") as buffer:
            while content := await file.read(1024 * 1024): # Read in chunks
                await buffer.write(content)
        
        logger.info(f"Saved {filename}")
        
        # Schedule background processing
        background_tasks.add_task(process_image, file_path, filename)
        
        return {"status": "ok", "filename": filename, "message": "Image received and queued for processing"}
        
    except Exception as e:
        logger.error(f"Failed to save upload {filename}: {e}")
        return {"status": "error", "message": str(e)}
