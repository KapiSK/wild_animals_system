import os
import datetime
import asyncio
import logging
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

# Semaphore to limit concurrent inference/forwarding
# Setting to 1 ensures we process one image at a time to save resources (CPU/RAM) on Pi
processing_semaphore = asyncio.Semaphore(1)

async def process_image(file_path: str, filename: str):
    """
    Background task to process the image:
    1. Run object detection
    2. If animal detected, forward to main server
    """
    async with processing_semaphore:
        logger.info(f"Starting processing for {filename}")
        try:
            # Define path for saving the inference result (annotated image)
            result_filename = f"{os.path.splitext(filename)[0]}_result.jpg"
            result_path = os.path.join(UPLOAD_DIR, result_filename)

            # Run detection in a separate thread to avoid blocking the event loop
            # This allows the server to continue receiving uploads while processing
            is_animal, label = await asyncio.to_thread(detector.detect, file_path, result_path)

            if is_animal:
                logger.info(f"Animal detected in {filename}: {label}")
                if MAIN_SERVER_URL:
                    await forward_image(file_path, filename, label)
                else:
                    logger.info("MAIN_SERVER_URL not set, skipping upload (Forwarding disabled)")
            else:
                logger.info(f"No animal detected in {filename}")

        except Exception as e:
            logger.error(f"Error processing {filename}: {e}")

async def forward_image(file_path: str, filename: str, label: str):
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
            data = {"label": label}
            
            response = await client.post(MAIN_SERVER_URL, files=files, data=data)
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
