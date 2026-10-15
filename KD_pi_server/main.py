import os
import sys
import datetime
import time
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import hashlib
import json
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse
from dotenv import load_dotenv
import httpx
from detector import Detector

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline_common import (Store, worker, receive_file, validate_jpeg,
                             image_identity, InvalidUpload, ReceiptConflict,
                             StorageFull, sync_directory)

from file_transfer import send_sftp

load_dotenv()
UPLOAD_DIR = os.path.abspath(os.getenv("UPLOAD_DIR", "uploads"))
MAIN_SERVER_URL = os.getenv("MAIN_SERVER_URL")
CLOUD_TRANSFER_MODE = os.getenv("CLOUD_TRANSFER_MODE", "http").lower()
if CLOUD_TRANSFER_MODE not in ("http", "sftp"):
    raise ValueError("CLOUD_TRANSFER_MODE must be http or sftp")
LOCAL_MODE = os.getenv("LOCAL_MODE", "False").lower() == "true"
API_TOKEN = os.getenv("API_TOKEN", "wild-animals-token-2026")
CYCLE_TIMEOUT = int(os.getenv("CYCLE_TIMEOUT_SECONDS", "300"))
NEGATIVE_SAMPLE_RATE = float(os.getenv("NEGATIVE_SAMPLE_RATE", "0.01"))
MIN_FREE_BYTES = int(os.getenv("MIN_FREE_MB", "64")) * 1024 * 1024
if not 0 <= NEGATIVE_SAMPLE_RATE <= 1:
    raise ValueError("NEGATIVE_SAMPLE_RATE must be between 0 and 1")
os.makedirs(UPLOAD_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[RotatingFileHandler("edge_server.log", maxBytes=5*1024*1024,
                                                  backupCount=3, encoding='utf-8', delay=True), logging.StreamHandler()])
logger = logging.getLogger(__name__)
store = Store(os.getenv("PIPELINE_DB", os.path.join(UPLOAD_DIR, "pipeline.sqlite3")))
detector = None


async def verify_api_token(x_api_key: str = Header(None)):
    if x_api_key != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API Token")


def sampled_negative(cycle):
    # Stable across retries/restarts: sample entire cycles, not isolated frames.
    fraction = int(hashlib.sha256(cycle.encode()).hexdigest()[:8], 16) / 2**32
    return fraction < NEGATIVE_SAMPLE_RATE


async def infer_image(payload):
    row = await asyncio.to_thread(store.image, payload['key'])
    if row['result'] is not None:
        return
    siblings = await asyncio.to_thread(store.images, row['cycle'])
    started = time.perf_counter()
    if any(r['result'] and r['result']['decision'] == 'positive' for r in siblings):
        result = {'decision': 'skipped', 'label': 'early exit after positive detection'}
    else:
        positive, label = await asyncio.to_thread(detector.detect, row['path'])
        result = {'decision': 'positive' if positive else 'negative', 'label': label}
    result.update(inference_ms=(time.perf_counter()-started)*1000,
                  inferred_at=time.time(), model=detector.model_path,
                  confidence_threshold=detector.confidence)
    await asyncio.to_thread(store.result, row['key'], result)


async def aggregate_once():
    for cycle in await asyncio.to_thread(store.pending_cycles):
        rows = await asyncio.to_thread(store.images, cycle)
        analyzed = [r for r in rows if r['result'] is not None]
        complete = {r['idx'] for r in analyzed} == {1, 2, 3}
        expired = time.time() - min(r['received'] for r in rows) >= CYCLE_TIMEOUT
        if not complete and not expired:
            continue
        # On timeout process available successful results; a failed inference
        # remains pending and can join the same cycle after a retry.
        if not analyzed:
            continue
        positive = any(r['result']['decision'] == 'positive' for r in analyzed)
        audit = not positive and sampled_negative(cycle)
        for row in analyzed:
            if positive or audit:
                # A late positive may reopen an earlier negative decision.
                await asyncio.to_thread(store.terminal, row['key'], False)
                await asyncio.to_thread(store.enqueue, 'forward:'+row['key'], 'forward',
                                        {'key': row['key'], 'reason': 'positive' if positive else 'negative_sample'})
                job = await asyncio.to_thread(store.job, 'forward:'+row['key'])
                if job['state'] == 'done':
                    await asyncio.to_thread(store.terminal, row['key'])
            else:
                await asyncio.to_thread(store.terminal, row['key'])
        logger.info("Cycle=%s complete=%s images=%s positive=%s audit=%s",
                    cycle, complete, [r['idx'] for r in analyzed], positive, audit)


async def aggregate_loop():
    while True:
        try:
            await aggregate_once()
        except Exception:
            logger.exception("Cycle aggregation failed; will retry")
        await asyncio.sleep(5)


async def forward_image(payload):
    if LOCAL_MODE or (CLOUD_TRANSFER_MODE == "http" and not MAIN_SERVER_URL):
        raise RuntimeError("Cloud forwarding disabled/unconfigured; retaining queued image")
    row = await asyncio.to_thread(store.image, payload['key'])
    metadata = row['payload']
    headers = {'X-API-KEY': API_TOKEN, 'X-Cycle-Id': row['cycle'],
               'X-Img-Index': str(row['idx']), 'X-Content-SHA256': row['hash'],
               'X-File-Size': str(metadata['size']),
               'X-Edge-Received-At': str(row['received']),
               'X-Edge-Decision': row['result']['decision'],
               'X-Transfer-Reason': payload['reason']}
    if metadata.get('captured_at'):
        headers['X-Captured-At'] = metadata['captured_at']
    started = time.perf_counter()
    if CLOUD_TRANSFER_MODE == 'sftp':
        message = {'version':1, 'kind':'image', 'filename':metadata['original_filename'],
                   'cycle_id':row['cycle'], 'image_index':row['idx'], 'sha256':row['hash'],
                   'size':metadata['size'], 'captured_at':metadata.get('captured_at'),
                   'edge_received_at':str(row['received']), 'edge_decision':row['result']['decision'],
                   'transfer_reason':payload['reason']}
        config = {'host':os.getenv('SFTP_HOST'), 'port':os.getenv('SFTP_PORT','22'),
                  'username':os.getenv('SFTP_USER'), 'key_filename':os.getenv('SFTP_KEY_FILE'),
                  'known_hosts':os.getenv('SFTP_KNOWN_HOSTS'), 'remote_root':os.getenv('SFTP_REMOTE_ROOT','/transfer'),
                  'passphrase':os.getenv('SFTP_KEY_PASSPHRASE'), 'timeout':os.getenv('SFTP_TIMEOUT','30')}
        await asyncio.to_thread(send_sftp, row['path'], message, config)
    else:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            with open(row['path'], 'rb') as image_file:
                response = await client.post(MAIN_SERVER_URL,
                    files={'file': (metadata['original_filename'], image_file, 'image/jpeg')}, headers=headers)
            response.raise_for_status()
            receipt = response.json()
            if receipt.get('status') != 'ok' or receipt.get('receipt_id') != row['key'] or receipt.get('sha256') != row['hash']:
                raise RuntimeError("Cloud did not confirm a matching durable receipt")
    # Do not mark terminal here: worker must commit job completion first.
    result = dict(row['result'])
    result.update(forwarded=True, forwarded_at=time.time(),
                  forward_ms=(time.perf_counter()-started)*1000,
                  end_to_end_ms=max(0, (time.time()-row['received'])*1000),
                  transfer_reason=payload['reason'], transport=CLOUD_TRANSFER_MODE)
    await asyncio.to_thread(store.result, row['key'], result)
    logger.info("[PERF] receipt=%s forwarded=true save_ms=%.1f inference_ms=%.1f forward_ms=%.1f end_to_end_ms=%.1f",
                row['key'], metadata['save_ms'], result['inference_ms'], result['forward_ms'], result['end_to_end_ms'])


async def periodic_cleanup():
    while True:
        try:
            await asyncio.to_thread(store.cleanup, int(os.getenv('RETENTION_DAYS', '7')))
            await asyncio.to_thread(cleanup_auxiliary_files)
        except Exception:
            logger.exception("Cleanup failed")
        await asyncio.sleep(3600)


def cleanup_auxiliary_files():
    # Received logs have no downstream jobs. Stale .part files were never ACKed.
    for directory, age in [('logs', 7*86400), ('incoming', 86400)]:
        for path in (Path(UPLOAD_DIR)/directory).glob('*'):
            if path.is_file() and path.stat().st_mtime < time.time()-age:
                path.unlink(missing_ok=True)


async def periodic_heartbeat():
    while True:
        try:
            if MAIN_SERVER_URL and not LOCAL_MODE:
                parsed = urlparse(MAIN_SERVER_URL)
                async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                    await client.post(f"{parsed.scheme}://{parsed.netloc}/api/v1/heartbeat",
                        headers={'X-API-KEY': API_TOKEN}, json={'node_id': 'pi', 'status': 'alive'})
        except Exception:
            logger.exception("Heartbeat failed")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app):
    global detector
    detector = await asyncio.to_thread(Detector)
    tasks = [asyncio.create_task(worker(store, 'infer', infer_image)),
             asyncio.create_task(worker(store, 'forward', forward_image)),
             asyncio.create_task(aggregate_loop()), asyncio.create_task(periodic_cleanup()),
             asyncio.create_task(periodic_heartbeat())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(lifespan=lifespan)
# Keep queue databases and temporary uploads out of the image-serving directory.
IMAGE_DIR = os.path.join(UPLOAD_DIR, 'images')
os.makedirs(IMAGE_DIR, exist_ok=True)
@app.get('/images/{filename}')
async def serve_image(filename: str):
    # Preserve old gallery URLs without exposing the receipt database/logs.
    if Path(filename).name != filename or '/' in filename or '\\' in filename or Path(filename).suffix.lower() not in ('.jpg','.jpeg','.png','.gif'):
        raise HTTPException(404, 'Image not found')
    for directory in (IMAGE_DIR, UPLOAD_DIR):
        path = Path(directory)/filename
        if path.is_file():
            return FileResponse(path)
    raise HTTPException(404, 'Image not found')


def upload_error(exc):
    if isinstance(exc, ReceiptConflict):
        return HTTPException(409, str(exc))
    if isinstance(exc, InvalidUpload):
        return HTTPException(422, str(exc))
    if isinstance(exc, StorageFull) or getattr(exc, 'errno', None) == 28:
        return HTTPException(507, 'Insufficient storage')
    logger.exception('Upload could not be durably accepted')
    return HTTPException(500, 'Upload was not accepted; retry later')


@app.post('/upload')
async def upload_image(request: Request, api_key: str = Depends(verify_api_token)):
    temporary = None
    received, started = time.time(), time.perf_counter()
    try:
        original = request.headers.get('X-File-Name', '')
        cycle, index, key = image_identity(original, request.headers.get('X-Cycle-Id'), request.headers.get('X-Img-Index'))
        digest_header = request.headers.get('X-Content-SHA256')
        if not digest_header:
            raise InvalidUpload('SHA256 header required')
        temporary, digest, size = await receive_file(request.stream(), os.path.join(UPLOAD_DIR, 'incoming'),
            digest_header, request.headers.get('Content-Length'), min_free=MIN_FREE_BYTES)
        await asyncio.to_thread(validate_jpeg, temporary)
        filename = f"{cycle}-{index}.jpg"
        row, duplicate = await asyncio.to_thread(store.accept, key, cycle, index, digest, temporary,
            os.path.join(IMAGE_DIR, filename),
            {'original_filename': 'pi_Rcv'+datetime.datetime.now().strftime('%H%M%S')+'_'+original,
             'received_at': received, 'captured_at': request.headers.get('X-Captured-At'),
             'size': size, 'save_ms': (time.perf_counter()-started)*1000})
        return {'status': 'ok', 'receipt_id': key, 'sha256': digest, 'duplicate': duplicate, 'filename': Path(row['path']).name}
    except Exception as exc:
        raise upload_error(exc) from exc
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


@app.post('/esp_log')
async def upload_esp_log(request: Request, api_key: str = Depends(verify_api_token)):
    temporary = None
    try:
        digest_header = request.headers.get('X-Content-SHA256')
        if not digest_header:
            raise InvalidUpload('SHA256 header required')
        temporary, digest, size = await receive_file(request.stream(), os.path.join(UPLOAD_DIR, 'incoming'),
            digest_header, request.headers.get('Content-Length'), max_bytes=2*1024*1024, min_free=MIN_FREE_BYTES)
        logs = Path(UPLOAD_DIR) / 'logs'
        logs.mkdir(exist_ok=True)
        destination = logs / (digest+'.log')
        await asyncio.to_thread(os.replace, temporary, destination)
        await asyncio.to_thread(sync_directory, logs)
        return {'status': 'ok', 'sha256': digest, 'size': size}
    except Exception as exc:
        raise upload_error(exc) from exc
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


@app.get('/healthz')
async def health_check():
    import shutil
    free = await asyncio.to_thread(lambda: shutil.disk_usage(UPLOAD_DIR).free)
    if free < MIN_FREE_BYTES:
        raise HTTPException(507, 'Insufficient storage')
    return {'status': 'ok', 'utc_epoch': int(time.time()), 'free_bytes': free,
            'queue': await asyncio.to_thread(store.stats)}


@app.get("/api/images")
async def get_images():
    """
    Return a list of images in the upload directory, sorted by newest first.
    """
    try:
        paths = {p.name:p for directory in (UPLOAD_DIR, IMAGE_DIR) for p in Path(directory).iterdir()
                 if p.is_file() and p.suffix.lower() in ('.png','.jpg','.jpeg','.gif')}
        files = sorted(paths, key=lambda name: paths[name].stat().st_mtime, reverse=True)
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
