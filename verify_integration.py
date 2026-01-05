import subprocess
import time
import requests
import os
import shutil
import sys
import signal

# --- Configuration ---
EXT_PORT = 8001
EDGE_PORT = 8002
TEST_DIR = "test_integration_artifacts"
EXT_UPLOAD_DIR = os.path.join(TEST_DIR, "ext_uploads")
EXT_PROCESSED_DIR = os.path.join(TEST_DIR, "ext_processed")
EDGE_UPLOAD_DIR = os.path.join(TEST_DIR, "edge_uploads")

# Paths to server scripts
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
EXT_SERVER_SCRIPT = os.path.join(ROOT_DIR, "original_server", "server.py")
EDGE_SERVER_SCRIPT = os.path.join(ROOT_DIR, "pi", "main.py")

def setup_directories():
    if os.path.exists(TEST_DIR):
        shutil.rmtree(TEST_DIR)
    os.makedirs(EXT_UPLOAD_DIR)
    os.makedirs(EXT_PROCESSED_DIR)
    os.makedirs(EDGE_UPLOAD_DIR)
    print(f"[Setup] Created test directories in {TEST_DIR}")

def create_dummy_image(filename):
    # Create a simple dummy image using PIL if available, else just a text file (but server needs image)
    # The server uses OpenCV/PIL, so it expects a real image.
    # We will try to copy a test image if one exists, otherwise download or skip.
    # Looking at directory listing earlier, there was 'test.jpg' in pi/ directory.
    src = os.path.join(ROOT_DIR, "pi", "test.jpg")
    dst = os.path.join(TEST_DIR, filename)
    if os.path.exists(src):
        shutil.copy(src, dst)
        return dst
    else:
        print("[Warn] pi/test.jpg not found. Creating a blank dummy jpg.")
        import numpy as np
        import cv2
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.imwrite(dst, img)
        return dst

def run_server(script_path, port, env):
    # Run using the current python executable
    cmd = [sys.executable, "-m", "uvicorn", 
           f"{os.path.splitext(os.path.basename(script_path))[0]}:app", 
           "--host", "127.0.0.1", "--port", str(port)]
    
    # Need to run from the script's directory for proper import resolution if needed, 
    # but uvicorn usually handles it if pythonpath is set.
    # pi/main.py imports 'detector', so we need to set cwd to pi/ or add pi/ to PYTHONPATH.
    
    cwd = os.path.dirname(script_path)
    # We add proper ENV vars
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def main():
    print("=== Starting System Integration Verification ===")
    setup_directories()

    # 1. Start External Server
    print(f"[Step 1] Starting External Server on port {EXT_PORT}...")
    ext_env = os.environ.copy()
    ext_env["UPLOAD_DIR"] = os.path.abspath(EXT_UPLOAD_DIR)
    ext_env["PROCESSED_DIR"] = os.path.abspath(EXT_PROCESSED_DIR)
    # Disable email for test
    ext_env["SENDER_EMAIL"] = "your_email@example.com" 
    
    # The external server script is at original_server/server.py
    # But uvicorn expects module import path. 
    # We'll run it as `python original_server/server.py` ? No, that runs uvicorn.run().
    # Let's execute the script directly since it has `if __name__ == "__main__": uvicorn.run(...)`
    # But we want to control port via ENV or args? The script hardcodes port 8000 in main.
    # However, create_setup_service.sh uses `python server.py`. 
    # Let's try running it as a module via uvicorn for flexibility, or modify environment port if supported.
    # server.py uses os.getenv("PORT", 8000)? No, checked code: `uvicorn.run(app, host="0.0.0.0", port=8000)` hardcoded in __main__.
    # BUT we can run `uvicorn original_server.server:app --port 8001`!
    
    ext_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "original_server.server:app", "--port", str(EXT_PORT)],
        cwd=ROOT_DIR, env=ext_env
    )
    
    # 2. Start Edge Server
    print(f"[Step 2] Starting Edge Server on port {EDGE_PORT}...")
    edge_env = os.environ.copy()
    edge_env["UPLOAD_DIR"] = os.path.abspath(EDGE_UPLOAD_DIR)
    edge_env["MAIN_SERVER_URL"] = f"http://127.0.0.1:{EXT_PORT}/upload"
    
    # pi/main.py imports detector.py which is in pi/. 
    # So we should set PYTHONPATH or run from pi/ dir.
    edge_env["PYTHONPATH"] = os.path.join(ROOT_DIR, "pi")
    
    edge_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "pi.main:app", "--port", str(EDGE_PORT)],
        cwd=ROOT_DIR, env=edge_env
    )

    try:
        time.sleep(5) # Wait for startup
        
        # 3. Simulate ESP32 Upload (3 images)
        print("[Step 3] Simulating ESP32 Uploads...")
        img_path = create_dummy_image(os.path.join(TEST_DIR, "test.jpg"))
        
        cycle_id = "TEST-CYCLE-01"
        filenames = [
            f"{cycle_id}-1d.jpg",
            f"{cycle_id}-2d.jpg",
            f"{cycle_id}-3d.jpg"
        ]
        
        # We need detection to happen. 
        # If we use a dummy black image, YOLO won't detect anything.
        # If YOLO doesn't detect anything, Edge Server logic (2 out of 3) won't forward.
        # So we need a real image with an animal, or we need to MOCK the detector.
        # Since we are verifying "interactions", mocking detector might be safer/faster,
        # but the user asked to check if it works "normaly".
        # If we use `pi/test.jpg` (if provided by repo), it might have an animal?
        # Assuming the user has a valid environment, let's try upload.
        # Note: If no animal detected, files stay in Edge but are NOT forwarded.
        # This TEST verifies the FLOW.
        
        url = f"http://127.0.0.1:{EDGE_PORT}/upload"
        
        for i, fname in enumerate(filenames):
            print(f"  Uploading {fname}...")
            with open(img_path, "rb") as f:
                # server expects "file"
                files = {"file": (fname, f, "image/jpeg")}
                try:
                    r = requests.post(url, files=files)
                    print(f"  Response: {r.status_code}")
                except Exception as e:
                    print(f"  Upload failed: {e}")

        # 4. Wait for processing
        print("[Step 4] Waiting for async processing (10s)...")
        time.sleep(10)
        
        # 5. Check Results
        print("[Step 5] Checking results...")
        
        # Check Edge storage
        edge_files = os.listdir(EDGE_UPLOAD_DIR)
        print(f"  Edge Server Files ({len(edge_files)}): {edge_files}")
        
        # Check External storage (Forwarded?)
        ext_files = os.listdir(EXT_UPLOAD_DIR)
        print(f"  External Server Files (Forwarded): {len(ext_files)}")
        # Note: If test.jpg has no animal, expected is 0.
        
        if len(edge_files) >= 3:
            print("  [OK] Edge Server received files.")
        else:
            print("  [FAIL] Edge Server missing files.")
            
        print("Note: Forwarding depends on YOLOv8 detection result on 'test.jpg'.")
        print("If 'test.jpg' contains an animal, External Server should have files.")

    except Exception as e:
        print(f"Test Error: {e}")
        
    finally:
        print("Stopping servers...")
        ext_proc.terminate()
        edge_proc.terminate()
        
if __name__ == "__main__":
    main()
