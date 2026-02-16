import os
import datetime
import logging
from fastapi import FastAPI, Request, BackgroundTasks
import aiofiles
import uvicorn

# Configuration
LOG_FILE = "server.log"
# CSV_FILE will be set dynamically in startup
CSV_FILE = f"experiment_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
UPLOAD_DIR = "uploads"

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

def log_to_csv(timestamp, seq, rssi, file_size, throughput, status, client_ip):
    """Logs experiment data to CSV."""
    file_exists = os.path.isfile(CSV_FILE)
    try:
        with open(CSV_FILE, "a") as f:
            if not file_exists:
                f.write("timestamp,seq,rssi,file_size,throughput_kbps,status,client_ip\n")
            f.write(f"{timestamp},{seq},{rssi},{file_size},{status},{client_ip}\n")
    except Exception as e:
        logger.error(f"Failed to write to CSV: {e}")

@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting experiment logging to: {CSV_FILE}")
    print(f"--- Experiment Session Started ---")
    print(f"Log File: {CSV_FILE}")
    print(f"Please RESET the ESP32 to start Sequence from 1.")

@app.post("/upload")
async def upload_image(request: Request):
    """
    Handle dummy image upload for range experiment.
    Expects X-Seq-Num and X-Rssi headers.
    """
    receive_start = datetime.datetime.now()
    client_ip = request.client.host
    
    # Extract headers
    seq = request.headers.get("X-Seq-Num", "-1")
    rssi = request.headers.get("X-Rssi", "0")
    
    logger.info(f"Received upload request. Seq: {seq}, RSSI: {rssi}, IP: {client_ip}")

    try:
        # Read the body to calculate size (we don't strictly need to save it, but we can)
        body = await request.body()
        file_size = len(body)
        
        # Optional: Save file if needed for debugging, but for range test speed is key.
        # Let's Skip saving to disk to minimize server-side latency affecting measurement?
        # Actually plan said "Save image to disk" but also "Dummy data".
        # Let's save it to be safe, but maybe overwrite a temp file or just log size?
        # Re-reading plan: "画像受信ログを記録するFastAPIサーバー... 受信完了を確認"
        # Since it's dummy data, saving it fills up disk unnecessarily. 
        # I will just measure size.
        
        # Calculate Throughput
        # This is a rough estimate: Size / (Now - Start)
        # Note: This only measures server-side receive time (transfer over network + buffering).
        # It's a good proxy for "Effective Throughput".
        # duration in seconds
        duration = (datetime.datetime.now() - receive_start).total_seconds()
        if duration <= 0: duration = 0.001 # avoid div by zero
        
        # Throughput in Kbps (Kilobits per second)
        # size * 8 bits / duration / 1000
        throughput_kbps = (file_size * 8) / duration / 1000
        
        status = "success"
        logger.info(f"Received {file_size} bytes in {duration:.3f}s. Throughput: {throughput_kbps:.2f} Kbps. Status: {status}")
        
        # Log to CSV
        log_to_csv(receive_start.isoformat(), seq, rssi, file_size, f"{throughput_kbps:.2f}", status, client_ip)
        
        return {"status": "ok", "seq": seq, "size": file_size}

    except Exception as e:
        logger.error(f"Error processing upload: {e}")
        log_to_csv(receive_start.isoformat(), seq, rssi, 0, "error", client_ip)
        return {"status": "error", "message": str(e)}

from fastapi.responses import HTMLResponse

@app.get("/logs", response_class=HTMLResponse)
async def get_logs():
    """
    Simple web viewer for the smartphone.
    Refreshes every 2 seconds.
    """
    html_content = """
    <html>
        <head>
            <title>Experiment Logs</title>
            <meta http-equiv="refresh" content="2">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body { font-family: monospace; padding: 10px; background: #222; color: #fff; }
                table { width: 100%; border-collapse: collapse; }
                th, td { padding: 5px; border-bottom: 1px solid #444; text-align: left; }
                .success { color: #4caf50; }
                .error { color: #f44336; }
                h2 { font-size: 1.2rem; margin: 0 0 10px; }
            </style>
        </head>
        <body>
            <h2>📡 Live Data</h2>
            <table>
                <tr>
                    <th>Seq</th>
                    <th>RSSI</th>
                    <th>Mbps</th>
                    <th>Status</th>
                </tr>
    """
    
    if os.path.exists(CSV_FILE):
        # Read last 20 lines (reversed)
        try:
            with open(CSV_FILE, "r") as f:
                lines = f.readlines()
                header = lines[0]
                rows = lines[1:][-20:] # Last 20
                
                for row in reversed(rows):
                    parts = row.strip().split(',')
                    if len(parts) >= 6:
                        # timestamp,seq,rssi,file_size,throughput_kbps,status,client_ip
                        # parts indices changed: ts=0, seq=1, rssi=2, size=3, kbps=4, stat=5, ip=6
                        seq_val = parts[1]
                        rssi_val = parts[2]
                        kbps_val = parts[4]
                        stat_val = parts[5]
                        
                        color_class = "success" if stat_val == "success" else "error"
                        
                        # Convert Kbps to Mbps for display if needed, or keep Kbps
                        # simple display
                        html_content += f"""
                        <tr class="{color_class}">
                            <td>{seq_val}</td>
                            <td>{rssi_val}</td>
                            <td>{kbps_val}</td>
                            <td>{stat_val}</td>
                        </tr>
                        """
        except Exception as e:
            html_content += f"<tr><td colspan='4'>Error reading log: {e}</td></tr>"
    else:
        html_content += "<tr><td colspan='4'>No log file yet. Waiting for data...</td></tr>"

    html_content += """
            </table>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    # Run with uvicorn
    # host="0.0.0.0" is crucial for external access
    uvicorn.run(app, host="0.0.0.0", port=8000)
