"""FTP/SFTP spool protocol and SSH sender, independent of inference models.

A sender writes <token>.data.part, renames to .data, then publishes a JSON
manifest as <token>.ready. Only the application receiver writes receipts.
"""
import asyncio
import errno
import json
import logging
import os
from pathlib import Path
import posixpath
import re
import shutil
import time
import uuid

import httpx
from pipeline_common import image_identity, sync_directory, InvalidUpload

logger = logging.getLogger(__name__)
TOKEN_RE = re.compile(r'[a-zA-Z0-9_-]{8,96}')
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 8192


def validate_manifest(message, role):
    if not isinstance(message, dict) or message.get('version') != 1:
        raise InvalidUpload('Unsupported transfer manifest')
    kind = message.get('kind')
    if kind not in ('image', 'log') or (role == 'cloud' and kind != 'image'):
        raise InvalidUpload('Unsupported transfer kind')
    digest, size = message.get('sha256'), message.get('size')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise InvalidUpload('Invalid SHA256')
    limit = MAX_IMAGE_BYTES if kind == 'image' else MAX_LOG_BYTES
    if type(size) is not int or not 0 < size <= limit:
        raise InvalidUpload('Invalid file size')
    filename = message.get('filename')
    if not isinstance(filename, str) or len(filename) > 180 or '/' in filename or '\\' in filename:
        raise InvalidUpload('Invalid filename')
    if kind == 'image':
        if not isinstance(message.get('cycle_id'), str) or type(message.get('image_index')) is not int:
            raise InvalidUpload('Image requires cycle_id and image_index')
        cycle, index, key = image_identity(filename, message.get('cycle_id'), message.get('image_index'))
    else:
        cycle = message.get('cycle_id', '')
        if not isinstance(cycle, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', cycle):
            raise InvalidUpload('Invalid log cycle')
        key = 'log:' + digest
    for field in ('captured_at', 'edge_received_at', 'edge_decision', 'transfer_reason'):
        value = message.get(field)
        if value is not None and (not isinstance(value, (str, int, float)) or len(str(value)) > 160 or
                                  '\r' in str(value) or '\n' in str(value)):
            raise InvalidUpload('Invalid metadata')
    return key


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as file:
            json.dump(value, file, separators=(',', ':'))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class Inbox:
    def __init__(self, root, role, api_url, api_token, min_free=64*1024*1024):
        if role not in ('edge', 'cloud'):
            raise ValueError('role must be edge or cloud')
        self.root = Path(root).resolve()
        self.incoming = self.root / 'incoming'
        self.receipts = self.root / 'receipts'
        self.role, self.api_url, self.api_token = role, api_url.rstrip('/'), api_token
        self.min_free = min_free
        self.incoming.mkdir(parents=True, exist_ok=True)
        self.receipts.mkdir(parents=True, exist_ok=True)
        self.retry_after = {}

    async def submit(self, client, message, data):
        key = validate_manifest(message, self.role)
        if data.is_symlink() or not data.is_file() or data.stat().st_size != message['size']:
            raise InvalidUpload('Missing/incorrect data file')
        headers = {'X-API-KEY': self.api_token, 'X-Content-SHA256': message['sha256'],
                   'X-File-Name': message['filename'], 'X-Cycle-Id': message.get('cycle_id', '')}
        for source, target in [('captured_at','X-Captured-At'), ('edge_received_at','X-Edge-Received-At'),
                               ('edge_decision','X-Edge-Decision'), ('transfer_reason','X-Transfer-Reason')]:
            if message.get(source) is not None:
                headers[target] = str(message[source])
        if message['kind'] == 'image':
            headers['X-Img-Index'] = str(message['image_index'])
        if self.role == 'cloud':
            headers['X-File-Size'] = str(message['size'])
            with data.open('rb') as stream:
                response = await client.post(self.api_url+'/upload', headers=headers,
                    files={'file': (message['filename'], stream, 'image/jpeg')})
        else:
            async def chunks():
                with data.open('rb') as stream:
                    while chunk := await asyncio.to_thread(stream.read, 65536):
                        yield chunk
            headers['Content-Length'] = str(message['size'])
            endpoint = '/upload' if message['kind'] == 'image' else '/esp_log'
            response = await client.post(self.api_url+endpoint, headers=headers, content=chunks())
        # Retry service/storage errors without discarding the spool.
        if response.status_code in (409, 413, 422):
            raise InvalidUpload(f'Application rejected data (HTTP {response.status_code})')
        response.raise_for_status()
        receipt = response.json()
        if receipt.get('status') != 'ok' or receipt.get('sha256') != message['sha256']:
            raise RuntimeError('Application did not return a matching durable receipt')
        if message['kind'] == 'image' and receipt.get('receipt_id') != key:
            raise RuntimeError('Application receipt ID mismatch')
        return dict(receipt, receipt_id=key, utc_epoch=int(time.time()))

    async def process_once(self, client):
        # One consumer per inbox. Ready files survive receiver/API restarts.
        for manifest in list(self.incoming.glob('*.ready'))[:128]:
            token = manifest.stem
            if not TOKEN_RE.fullmatch(token) or manifest.is_symlink():
                continue
            if self.retry_after.get(token, 0) > time.monotonic():
                continue
            data = self.incoming / (token + '.data')
            receipt_path = self.receipts / (token + '.json')
            try:
                if receipt_path.exists():
                    # Crash after the receipt commit but before spool cleanup.
                    manifest.unlink(missing_ok=True)
                    data.unlink(missing_ok=True)
                    self.retry_after.pop(token, None)
                    continue
                if manifest.stat().st_size > MAX_MANIFEST_BYTES:
                    raise InvalidUpload('Manifest too large')
                message = json.loads(manifest.read_text(encoding='utf-8'))
                receipt = await self.submit(client, message, data)
                await asyncio.to_thread(atomic_json, receipt_path, receipt)
                manifest.unlink(missing_ok=True)
                data.unlink(missing_ok=True)
                self.retry_after.pop(token, None)
            except (InvalidUpload, ValueError, UnicodeError) as exc:
                logger.warning('Transfer %s rejected: %s', token, exc)
                await asyncio.to_thread(atomic_json, receipt_path, {'status':'error', 'message':str(exc)})
                manifest.unlink(missing_ok=True)
                data.unlink(missing_ok=True)
                self.retry_after.pop(token, None)
            except Exception:
                logger.exception('Transfer %s retained for retry', token)
                self.retry_after[token] = time.monotonic()+10

    async def publish_status(self, client):
        if self.role != 'edge':
            return
        status = {'status':'unavailable', 'utc_epoch':int(time.time())}
        try:
            response = await client.get(self.api_url+'/healthz', timeout=3)
            response.raise_for_status()
            if response.json().get('status') == 'ok' and shutil.disk_usage(self.root).free >= self.min_free:
                status['status'] = 'ok'
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.to_thread(atomic_json, self.root/'status.json', status)

    def cleanup(self, days=7):
        # Unacknowledged READY transfers are never pruned. Unpublished files
        # and completed receipts can be removed after the retention interval.
        cutoff = time.time()-days*86400
        for path in self.receipts.glob('*.json'):
            if path.stat().st_mtime < cutoff and not (self.incoming/(path.stem+'.ready')).exists():
                path.unlink(missing_ok=True)
        for path in self.incoming.iterdir():
            token = path.name.split('.')[0]
            if path.is_file() and not path.is_symlink() and path.suffix != '.ready' and path.stat().st_mtime < cutoff:
                if not (self.incoming/(token+'.ready')).exists():
                    path.unlink(missing_ok=True)

    async def run(self):
        last_cleanup = 0
        last_status = 0
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                try:
                    if time.monotonic()-last_status >= 2:
                        await self.publish_status(client)
                        last_status = time.monotonic()
                    await self.process_once(client)
                    if time.monotonic()-last_cleanup > 3600:
                        await asyncio.to_thread(self.cleanup)
                        last_cleanup = time.monotonic()
                except Exception:
                    logger.exception('Inbox scan failed; retrying')
                await asyncio.sleep(.25)


def send_sftp(path, message, config):
    """Blocking SSH work, called in the forwarding worker's thread executor."""
    import paramiko
    validate_manifest(message, 'cloud')
    required = ('host','username','key_filename','known_hosts','remote_root')
    if any(not config.get(key) for key in required):
        raise ValueError('SFTP requires host, username, key_filename, known_hosts and remote_root')
    token = uuid.uuid4().hex
    base = config['remote_root'].rstrip('/') or '/'
    incoming = posixpath.join(base, 'incoming', token)
    receipt_path = posixpath.join(base, 'receipts', token+'.json')
    timeout = float(config.get('timeout', 30))
    with paramiko.SSHClient() as ssh:
        ssh.load_host_keys(os.path.expanduser(config['known_hosts']))
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        ssh.connect(config['host'], port=int(config.get('port',22)), username=config['username'],
                    key_filename=os.path.expanduser(config['key_filename']),
                    passphrase=config.get('passphrase') or None, allow_agent=False, look_for_keys=False,
                    timeout=timeout, banner_timeout=timeout, auth_timeout=timeout)
        with ssh.open_sftp() as sftp:
            sftp.get_channel().settimeout(timeout)
            sftp.put(str(path), incoming+'.data.part', confirm=True)
            sftp.rename(incoming+'.data.part', incoming+'.data')
            with sftp.open(incoming+'.json.part', 'w') as manifest:
                manifest.write(json.dumps(message, separators=(',',':')))
            sftp.rename(incoming+'.json.part', incoming+'.ready')
            deadline = time.monotonic()+timeout
            while time.monotonic() < deadline:
                try:
                    with sftp.open(receipt_path, 'r') as receipt_file:
                        raw = receipt_file.read(MAX_MANIFEST_BYTES+1)
                    if len(raw) > MAX_MANIFEST_BYTES:
                        raise RuntimeError('SFTP receipt too large')
                    receipt = json.loads(raw)
                    expected = image_identity(message['filename'],message['cycle_id'],message['image_index'])[2]
                    if receipt.get('status') != 'ok' or receipt.get('receipt_id') != expected or receipt.get('sha256') != message['sha256']:
                        raise RuntimeError('SFTP receipt rejected/mismatched')
                    return receipt
                except OSError as exc:
                    if exc.errno != errno.ENOENT:
                        raise
                    time.sleep(.25)
            raise TimeoutError('SFTP application receipt timed out; image remains queued')
