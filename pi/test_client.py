import asyncio
import httpx
import time
import os
import sys

# Configuration
SERVER_URL = "http://172.10.176.172:8000/upload"
IMAGE_FILE = "test.jpg"
NUM_REQUESTS = 5  # Reduced for stability

async def upload_image(client, i):
    start_time = time.time()
    try:
        # Re-open file for each request to simulate fresh read
        with open(IMAGE_FILE, "rb") as f:
            # Note: The server expects 'file' parameter
            files = {'file': (f'{os.path.basename(IMAGE_FILE)}', f, 'image/jpeg')}
            # Increased timeout for slow networks/large files
            response = await client.post(SERVER_URL, files=files, timeout=30.0)
        
        elapsed = time.time() - start_time
        print(f"Request {i}: Status {response.status_code}, Time {elapsed:.2f}s")
        if response.status_code != 200:
             print(f"  Response: {response.text}")
        return response.status_code
    except httpx.TimeoutException:
        print(f"Request {i}: Failed (Timeout)")
        return 0
    except Exception as e:
        print(f"Request {i}: Failed {e}")
        return 0

async def main():
    # Strict check for existing file
    if not os.path.exists(IMAGE_FILE):
        print(f"Error: '{IMAGE_FILE}' not found in current directory.")
        print("Please place the image file you want to send in this folder.")
        sys.exit(1)
        
    print(f"Sending '{IMAGE_FILE}' to {SERVER_URL}")

    async with httpx.AsyncClient() as client:
        tasks = []
        print(f"Starting {NUM_REQUESTS} concurrent uploads...")
        start_total = time.time()
        
        for i in range(NUM_REQUESTS):
            tasks.append(upload_image(client, i))
            
        results = await asyncio.gather(*tasks)
        
        total_time = time.time() - start_total
        print(f"Total time: {total_time:.2f}s")
        print(f"Success rate: {results.count(200)}/{NUM_REQUESTS}")

if __name__ == "__main__":
    asyncio.run(main())
