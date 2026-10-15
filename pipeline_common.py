"""Durable image receipts and leased jobs shared by edge and cloud services.

Keep this module beside KD_pi_server/ and original_server/ when deploying.
SQLite transactions and fsync happen before acknowledging an upload.
"""
import asyncio
import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid

logger = logging.getLogger(__name__)


class ReceiptConflict(ValueError):
    pass


class InvalidUpload(ValueError):
    pass


class StorageFull(OSError):
    pass


def image_identity(filename, cycle=None, index=None):
    """Accept camera names and the timestamp prefixes used by older Pi clients."""
    name = re.sub(r"^\d{8}_\d{6}_\d+_", "", filename or "")
    name = re.sub(r"^(pi|satos)_Rcv\d{6}_", "", name)
    match = re.fullmatch(r"([A-Za-z0-9_-]+)-(\d+)-([123])[nd]?\.[jJ][pP][gG]", name)
    if match:
        inferred_cycle = f"{match[1]}-{match[2]}"
        inferred_index = int(match[3])
    else:
        match = re.fullmatch(r"([A-Za-z0-9_-]+)_\d{14}_(\d+)_([123])[nd]?\.[jJ][pP][gG]", name)
        if not match:
            raise InvalidUpload("Expected a camera/cycle/image-index JPEG filename")
        inferred_cycle, inferred_index = f"{match[1]}-{match[2]}", int(match[3])
    if cycle is not None and cycle != inferred_cycle:
        raise InvalidUpload("Cycle header does not match filename")
    if index is not None and str(index) != str(inferred_index):
        raise InvalidUpload("Image index header does not match filename")
    return inferred_cycle, inferred_index, f"{inferred_cycle}:{inferred_index}"


def sync_directory(path):
    if os.name != "nt":
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


async def receive_file(chunks, directory, expected_hash=None, expected_size=None,
                       max_bytes=16 * 1024 * 1024, min_free=64 * 1024 * 1024):
    """Stream to a unique temporary file. Caller commits it after validation."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if expected_hash and not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
        raise InvalidUpload("Invalid SHA256 header")
    try:
        expected_size = int(expected_size) if expected_size is not None else None
    except (TypeError, ValueError):
        raise InvalidUpload("Invalid size header")
    if expected_size is not None and (expected_size <= 0 or expected_size > max_bytes):
        raise InvalidUpload("Invalid upload size")
    if shutil.disk_usage(directory).free < min_free + (expected_size or max_bytes):
        raise StorageFull("Insufficient disk space")
    path = directory / (uuid.uuid4().hex + ".part")
    digest, size = hashlib.sha256(), 0
    try:
        with path.open("xb") as handle:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise InvalidUpload("Upload too large")
                await asyncio.to_thread(handle.write, chunk)
                digest.update(chunk)
            if not size or (expected_size is not None and size != expected_size):
                raise InvalidUpload("Upload size mismatch or empty file")
            if expected_hash and digest.hexdigest() != expected_hash.lower():
                raise InvalidUpload("SHA256 mismatch")
            await asyncio.to_thread(handle.flush)
            await asyncio.to_thread(os.fsync, handle.fileno())
        return str(path), digest.hexdigest(), size
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def validate_jpeg(path):
    # cv2 is already used by both detectors. Decode before durable acceptance.
    import cv2
    image = cv2.imread(str(path))
    if image is None or image.size == 0:
        raise InvalidUpload("Image cannot be decoded")


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS images (
                    key TEXT PRIMARY KEY, cycle TEXT NOT NULL, idx INTEGER NOT NULL,
                    hash TEXT NOT NULL, path TEXT NOT NULL, payload TEXT NOT NULL,
                    received REAL NOT NULL, result TEXT, terminal INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(cycle, idx));
                CREATE TABLE IF NOT EXISTS jobs (
                    key TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'ready', attempts INTEGER NOT NULL DEFAULT 0,
                    available REAL NOT NULL DEFAULT 0, lease REAL NOT NULL DEFAULT 0,
                    token TEXT, error TEXT, completed REAL);
                CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(kind,state,available);
                CREATE INDEX IF NOT EXISTS images_cycle ON images(cycle);
                CREATE TABLE IF NOT EXISTS sequences (
                    camera TEXT NOT NULL, event TEXT NOT NULL, value INTEGER NOT NULL,
                    PRIMARY KEY(camera,event));
            """)

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _enqueue(db, key, kind, payload):
        db.execute("INSERT OR IGNORE INTO jobs(key,kind,payload) VALUES(?,?,?)",
                   (key, kind, json.dumps(payload)))

    def enqueue(self, key, kind, payload):
        with self.connect() as db:
            self._enqueue(db, key, kind, payload)

    def accept(self, key, cycle, index, digest, temporary, destination, payload):
        """Atomically deduplicate + register a receipt and inference job.

        A crash between rename and commit leaves an unacknowledged orphan only;
        retrying the same upload safely replaces it. Never delete receipt rows
        when pruning images: they are the deduplication tombstones.
        """
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM images WHERE key=?", (key,)).fetchone()
            if old:
                if old['hash'] != digest:
                    raise ReceiptConflict("Same image ID has different content")
                Path(temporary).unlink(missing_ok=True)
                return dict(old), True
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, destination)
            sync_directory(Path(destination).parent)
            received = payload.get('received_at', time.time())
            db.execute("INSERT INTO images(key,cycle,idx,hash,path,payload,received) VALUES(?,?,?,?,?,?,?)",
                       (key, cycle, index, digest, str(destination), json.dumps(payload), received))
            self._enqueue(db, 'infer:' + key, 'infer', {'key': key})
        return self.image(key), False

    @staticmethod
    def decode(row):
        if row is None:
            return None
        result = dict(row)
        result['payload'] = json.loads(result['payload'])
        if 'result' in result:
            result['result'] = json.loads(result['result']) if result['result'] else None
        return result

    def image(self, key):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM images WHERE key=?", (key,)).fetchone())

    def images(self, cycle):
        with self.connect() as db:
            return [self.decode(r) for r in db.execute("SELECT * FROM images WHERE cycle=? ORDER BY idx", (cycle,))]

    def pending_cycles(self):
        with self.connect() as db:
            return [r[0] for r in db.execute("SELECT DISTINCT cycle FROM images WHERE terminal=0")]

    def manages_paths(self, paths):
        with self.connect() as db:
            return any(db.execute('SELECT 1 FROM images WHERE path=?', (str(path),)).fetchone()
                       for path in paths)

    def result(self, key, result):
        with self.connect() as db:
            db.execute("UPDATE images SET result=? WHERE key=?", (json.dumps(result), key))

    def terminal(self, key, value=True):
        with self.connect() as db:
            db.execute("UPDATE images SET terminal=? WHERE key=?", (int(value),key))

    def sequence(self, camera, event, floor=0):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT value FROM sequences WHERE camera=? AND event=?", (camera,event)).fetchone()
            if old:
                return old[0]
            highest = db.execute("SELECT MAX(value) FROM sequences WHERE camera=?", (camera,)).fetchone()[0] or 0
            value = max(highest, floor) + 1
            db.execute("INSERT INTO sequences VALUES(?,?,?)", (camera,event,value))
            return value

    def claim(self, kind, lease_seconds=120):
        now, token = time.time(), uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM jobs WHERE kind=? AND
                ((state='ready' AND available<=?) OR (state='working' AND lease<?))
                ORDER BY available,key LIMIT 1""", (kind,now,now)).fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET state='working',token=?,lease=?,attempts=attempts+1 WHERE key=?",
                       (token,now+lease_seconds,row['key']))
            job = self.decode(row)
            job.update(token=token, attempts=row['attempts']+1)
            return job

    def renew(self, job):
        with self.connect() as db:
            db.execute("UPDATE jobs SET lease=? WHERE key=? AND token=? AND state='working'",
                       (time.time()+120,job['key'],job['token']))

    def complete(self, job):
        with self.connect() as db:
            db.execute("UPDATE jobs SET state='done',completed=?,error=NULL WHERE key=? AND token=?",
                       (time.time(),job['key'],job['token']))

    def retry(self, job, error, delay=None):
        delay = min(3600, 2 ** min(job['attempts'], 11)) if delay is None else delay
        with self.connect() as db:
            db.execute("UPDATE jobs SET state='ready',available=?,error=?,token=NULL WHERE key=? AND token=?",
                       (time.time()+delay,str(error)[:1000],job['key'],job['token']))

    def job(self, key):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone())

    def cleanup(self, days=7):
        """Only delete terminal images from entirely settled cycles."""
        with self.connect() as db:
            rows = db.execute("""SELECT path FROM images WHERE received<? AND terminal=1
                AND cycle NOT IN (SELECT cycle FROM images WHERE terminal=0)""",
                (time.time()-days*86400,)).fetchall()
        for row in rows:
            Path(row['path']).unlink(missing_ok=True)

    def stats(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT kind,state,COUNT(*) AS count FROM jobs GROUP BY kind,state")]

    def metrics(self):
        with self.connect() as db:
            rows = db.execute("""SELECT images.*, jobs.state AS forward_state,
                jobs.attempts AS forward_attempts, jobs.error AS forward_error
                FROM images LEFT JOIN jobs ON jobs.key='forward:' || images.key
                ORDER BY images.received, images.idx""").fetchall()
        for raw in rows:
            row = self.decode(raw)
            payload, result = row['payload'], row['result'] or {}
            yield {'receipt_id': row['key'], 'cycle': row['cycle'], 'image_index': row['idx'],
                   'captured_at_utc_epoch': payload.get('captured_at'),
                   'received_at_utc_epoch': row['received'], 'inferred_at_utc_epoch': result.get('inferred_at'),
                   'save_ms': payload.get('save_ms'), 'inference_ms': result.get('inference_ms'),
                   'edge_decision': result.get('decision', payload.get('edge_decision')),
                   'transfer_reason': result.get('transfer_reason', payload.get('transfer_reason')),
                   'model': result.get('model'), 'confidence_threshold': result.get('confidence_threshold'),
                   'cloud_target_count': result.get('target_count'),
                   'forward_state': row['forward_state'], 'forward_attempts': row['forward_attempts'],
                   'forward_error': row['forward_error'], 'forwarded': row['forward_state'] == 'done',
                   'forward_ms': result.get('forward_ms'), 'end_to_end_ms': result.get('end_to_end_ms')}


async def worker(store, kind, handler):
    """Separate worker per stage; a slow transfer never holds the inference lock."""
    async def heartbeat(job):
        while True:
            await asyncio.sleep(30)
            await asyncio.to_thread(store.renew, job)

    while True:
        job = None
        renewal = None
        try:
            job = await asyncio.to_thread(store.claim, kind)
            if not job:
                await asyncio.sleep(1)
                continue
            renewal = asyncio.create_task(heartbeat(job))
            await handler(job['payload'])
            await asyncio.to_thread(store.complete, job)
        except asyncio.CancelledError:
            # Leave the lease in place: an outstanding to_thread call may still
            # be finishing. On restart the job is reclaimed after lease expiry.
            raise
        except Exception as exc:
            logger.exception("%s job failed; retained for retry", kind)
            if job:
                await asyncio.to_thread(store.retry, job, exc)
            else:
                await asyncio.sleep(2)
        finally:
            if renewal:
                renewal.cancel()
                # Collect the child's cancellation, but propagate cancellation
                # of this worker even when it arrives during renewal teardown.
                await asyncio.gather(renewal, return_exceptions=True)


if __name__ == '__main__':
    import argparse
    import csv
    parser = argparse.ArgumentParser(description='Export durable per-image pipeline metrics (UTC epoch).')
    parser.add_argument('--db', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if not Path(args.db).is_file():
        parser.error('Database does not exist')
    rows = list(Store(args.db).metrics())
    with open(args.output, 'w', newline='', encoding='utf-8') as output:
        if rows:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
