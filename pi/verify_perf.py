import asyncio
import httpx
import time
import os
import sys

# Configuration
SERVER_URL = "http://127.0.0.1:8000/upload"
SOURCE_IMAGE = "test.jpg"
CYCLE_ID = "PERF_TEST_CYCLE"

# Filenames that trigger a cycle: CycleID-1.jpg, CycleID-2.jpg, CycleID-3.jpg
FILENAMES = [
    f"{CYCLE_ID}-1.jpg",
    f"{CYCLE_ID}-2.jpg",
    f"{CYCLE_ID}-3.jpg"
]

async def upload_image(client, filename):
    print(f"Uploading {filename}...")
    try:
        # Read the source image content
        with open(SOURCE_IMAGE, "rb") as f:
            content = f.read()
            
        files = {'file': (filename, content, 'image/jpeg')}
        response = await client.post(SERVER_URL, files=files, timeout=30.0)
        
        print(f"Uploaded {filename}: Status {response.status_code}")
        return response.status_code
    except Exception as e:
        print(f"Failed to upload {filename}: {e}")
        return 0

async def main():
    if not os.path.exists(SOURCE_IMAGE):
        print(f"Error: '{SOURCE_IMAGE}' not found.")
        sys.exit(1)

    async with httpx.AsyncClient() as client:
        for filename in FILENAMES:
            await upload_image(client, filename)
            # Small delay to ensure order (optional, but realistic)
            await asyncio.sleep(0.5)

    print("All images sent. Checking server logs for [PERF] entries is required.")

if __name__ == "__main__":
    asyncio.run(main())
