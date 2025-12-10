import asyncio
import httpx
import time
import os

# Configuration
SERVER_URL = "http://localhost:8000/upload" # Change localhost to Pi's IP if running from PC
NUM_REQUESTS = 10

# Create a dummy image for testing
with open("test_image.jpg", "wb") as f:
    f.write(os.urandom(1024 * 100)) # 100KB dummy image

async def upload_image(client, i):
    start_time = time.time()
    try:
        files = {'file': (f'image_{i}.jpg', open('test_image.jpg', 'rb'), 'image/jpeg')}
        response = await client.post(SERVER_URL, files=files, timeout=10.0)
        elapsed = time.time() - start_time
        print(f"Request {i}: Status {response.status_code}, Time {elapsed:.2f}s")
        return response.status_code
    except Exception as e:
        print(f"Request {i}: Failed {e}")
        return 0

async def main():
    async with httpx.AsyncClient() as client:
        tasks = []
        print(f"Starting {NUM_REQUESTS} concurrent uploads to {SERVER_URL}...")
        start_total = time.time()
        
        for i in range(NUM_REQUESTS):
            tasks.append(upload_image(client, i))
            
        results = await asyncio.gather(*tasks)
        
        total_time = time.time() - start_total
        print(f"Total time: {total_time:.2f}s")
        print(f"Success rate: {results.count(200)}/{NUM_REQUESTS}")

if __name__ == "__main__":
    if "localhost" in SERVER_URL:
        print("Note: Testing against localhost. If testing a remote Pi, update SERVER_URL in the script.")
    
    # Check if server is running
    try:
        import socket
        host = SERVER_URL.split("//")[1].split(":")[0]
        port = int(SERVER_URL.split(":")[2].split("/")[0])
        with socket.create_connection((host, port), timeout=1):
            pass
    except Exception:
        print(f"Error: Could not connect to {SERVER_URL}. Is the server running?")
        exit(1)

    asyncio.run(main())
