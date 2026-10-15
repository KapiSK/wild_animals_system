"""Single-writer JPEG receiver with HTTP/1.1 persistent connections."""
import argparse
import io
import json
import os
import re
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from PIL import Image
from common import append_json, digest, identifier, load_config, utc


class Receiver(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, settings):
        self.settings = settings
        self.storage = Path(settings["storage"])
        self.storage.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(self.server.settings.get("read_timeout_s", 130))

    def log_message(self, *args):
        pass

    def respond(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if status >= 400:
            self.close_connection = True
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.respond(200 if self.path == "/healthz" else 404, {"ready": self.path == "/healthz"})

    def do_POST(self):
        try:
            device = identifier(self.headers.get("X-Device-Id"))
            cycle = identifier(self.headers.get("X-Cycle-Id"))
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                raise ValueError("one Content-Length required; chunked encoding unsupported")
            size = int(self.headers["Content-Length"])
            limit = self.server.settings["max_image_bytes"] if self.path == "/upload" else 65536
            if not 0 < size <= limit:
                raise ValueError("invalid Content-Length")
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError("truncated body")
            with self.server.lock:
                folder = self.server.storage / device / cycle
                if self.path == "/upload":
                    index = int(self.headers.get("X-Img-Index", "0"))
                    sha = self.headers.get("X-Content-SHA256", "")
                    if not 1 <= index <= 32 or not re.fullmatch("[0-9a-f]{64}", sha):
                        raise ValueError("invalid index/hash")
                    if self.headers.get("Content-Type") != "image/jpeg" or digest(body) != sha:
                        raise ValueError("type or SHA-256 mismatch")
                    with Image.open(io.BytesIO(body)) as im:
                        if im.format != "JPEG":
                            raise ValueError("not JPEG")
                        im.verify()
                    folder.mkdir(parents=True, exist_ok=True)
                    target = folder / f"{index}.jpg"
                    duplicate = target.exists()
                    if duplicate and target.read_bytes() != body:
                        append_json(self.server.storage / "receiver.jsonl", dict(utc=utc(), device_id=device,
                                    cycle_id=cycle, index=index, status="conflict"))
                        self.respond(409, {"error": "conflict"})
                        return
                    if not duplicate:
                        temporary = folder / (uuid.uuid4().hex + ".tmp")
                        try:
                            with temporary.open("xb") as f:
                                f.write(body)
                                if self.server.settings.get("fsync"):
                                    f.flush()
                                    os.fsync(f.fileno())
                            os.replace(temporary, target)
                            if self.server.settings.get("fsync") and os.name == "posix":
                                fd = os.open(folder, os.O_RDONLY)
                                try:
                                    os.fsync(fd)
                                finally:
                                    os.close(fd)
                        finally:
                            temporary.unlink(missing_ok=True)
                    result = dict(device_id=device, cycle_id=cycle, index=index, bytes=size,
                                  sha256=sha, duplicate=duplicate)
                    append_json(self.server.storage / "receiver.jsonl", dict(utc=utc(), status="saved", **result))
                    self.respond(200, result)
                elif self.path == "/complete":
                    expected = json.loads(body)["images"]
                    if not isinstance(expected, list) or not 1 <= len(expected) <= 32:
                        raise ValueError("invalid expected images")
                    if [r["index"] for r in expected] != list(range(1, len(expected) + 1)):
                        raise ValueError("expected indices must be contiguous")
                    received = []
                    for r in expected:
                        target = folder / f'{r["index"]}.jpg'
                        if target.exists():
                            data = target.read_bytes()
                            if len(data) == r["bytes"] and digest(data) == r["sha256"]:
                                received.append(r["index"])
                    result = dict(device_id=device, cycle_id=cycle, received_indices=received,
                                  complete=len(received) == len(expected))
                    append_json(self.server.storage / "receiver.jsonl", dict(utc=utc(), status="complete_check", **result))
                    self.respond(200 if result["complete"] else 409, result)
                else:
                    self.respond(404, {"error": "unknown endpoint"})
        except (ValueError, KeyError, TypeError, OSError) as exc:
            try:
                self.respond(400 if not isinstance(exc, OSError) else 500, {"error": str(exc)})
            except (OSError, socket.timeout):
                pass


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="config.yaml")
    c = load_config(p.parse_args().config)["server"]
    server = Receiver((c["host"], c["port"]), c)
    print(f'Receiver http://{c["host"]}:{server.server_port}; storage={server.storage}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
