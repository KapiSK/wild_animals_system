import asyncio
import httpx
import time
import os
import sys

# Configuration
# This script sends images to the EXTERNAL server (server.py)
SERVER_URL = "http://127.0.0.1:8000/upload"
SOURCE_IMAGE = "test.jpg"
CYCLE_ID = "EXT_PERF_TEST"

# Filenames that trigger a cycle: CycleID-1.jpg, CycleID-2.jpg, CycleID-3.jpg
# Note: server.py expects {CycleID}-{Index}.jpg suffix logic
FILENAMES = [
    f"{CYCLE_ID}-1.jpg",
    f"{CYCLE_ID}-2.jpg",
    f"{CYCLE_ID}-3.jpg"
]

async def upload_image(client, filename):
    print(f"Uploading {filename}...")
    try:
        # Read the source image content
        if not os.path.exists(SOURCE_IMAGE):
             # Create a dummy image if not exists
             with open(SOURCE_IMAGE, "wb") as f:
                 f.write(b"dummy image content strict enough? server relies on model... maybe not.")
             # Actually server uses cv2.imread, so dummy content might fail.
             # Ideally user should have a real jpg.
             pass

        if os.path.exists(SOURCE_IMAGE):
            with open(SOURCE_IMAGE, "rb") as f:
                content = f.read()
        else:
             print("Source image not found, cannot test properly.")
             return 0
            
        files = {'file': (filename, content, 'image/jpeg')}
        # longer timeout for external server inference
        response = await client.post(SERVER_URL, files=files, timeout=60.0)
        
        print(f"Uploaded {filename}: Status {response.status_code}")
        return response.status_code
    except Exception as e:
        print(f"Failed to upload {filename}: {e}")
        return 0

async def main():
    global SOURCE_IMAGE
    # Check for test.jpg existence or use a placeholder
    if not os.path.exists(SOURCE_IMAGE):
        print(f"Warning: '{SOURCE_IMAGE}' not found. Please provide a valid JPEG for true inference testing.")
        # Try to use any jpg in directory
        import glob
        jpgs = glob.glob("*.jpg")
        if jpgs:
            SOURCE_IMAGE = jpgs[0]
            print(f"Using {SOURCE_IMAGE} as test image.")
        else:
            print("No .jpg files found to use as test source.")
            return

    async with httpx.AsyncClient() as client:
        for filename in FILENAMES:
            await upload_image(client, filename)
            # Small delay
            await asyncio.sleep(1.0)

    print("All images sent. Please check server.log for [PERF] entries.")
    print("Expected:")
    print(f"  [PERF] Cycle {CYCLE_ID} Finished. Total Time: ...ms")
    print("  [PERF] Breakdown: Save=...ms, Inference=...ms, Email=...ms")

if __name__ == "__main__":
    asyncio.run(main())
