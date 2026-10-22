"""Camera FTP inbox. Only completed transfers are handed to the application."""
import logging
import os
import shutil
from pathlib import Path
import threading
import uuid

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.ioloop import IOLoop
from pyftpdlib.servers import FTPServer

logger = logging.getLogger(__name__)


class CameraFTP:
    def __init__(self, inbox, processing, on_received):
        inbox, processing = Path(inbox).resolve(), Path(processing).resolve()
        inbox.mkdir(parents=True, exist_ok=True)
        processing.mkdir(parents=True, exist_ok=True)
        password = os.getenv("FTP_PASSWORD", "")
        if not password:
            raise ValueError("Set FTP_PASSWORD in .env before starting the FTP receiver")
        authorizer = DummyAuthorizer()
        authorizer.add_user(os.getenv("FTP_USER", "camera"), password, str(inbox), perm="elradfmwMT")

        class Handler(FTPHandler):
            def on_file_received(self, file):
                source = Path(file)
                # A camera may upload with a temporary extension; detect the
                # actual image format later rather than relying on its name.
                target = processing / (uuid.uuid4().hex + ".incoming")
                try:
                    # Keep the inbox entry for cameras using RNFR/RNTO after STOR.
                    # The private snapshot cannot be overwritten by a later upload.
                    shutil.copyfile(source, target)
                    on_received(target)
                except Exception:
                    target.unlink(missing_ok=True)
                    logger.exception("Failed to queue FTP upload")

            def on_incomplete_file_received(self, file):
                Path(file).unlink(missing_ok=True)

        Handler.authorizer = authorizer
        first = int(os.getenv("FTP_PASSIVE_PORT_MIN", "60000"))
        last = int(os.getenv("FTP_PASSIVE_PORT_MAX", "60009"))
        if not 1024 <= first <= last <= 65535:
            raise ValueError("Invalid FTP passive port range")
        Handler.passive_ports = range(first, last + 1)
        Handler.masquerade_address = os.getenv("FTP_MASQUERADE_ADDRESS") or None
        self.loop = IOLoop()
        self.server = FTPServer((os.getenv("FTP_HOST", "0.0.0.0"), int(os.getenv("FTP_PORT", "2121"))), Handler, ioloop=self.loop)
        self.server.max_cons = 16
        self.server.max_cons_per_ip = 4
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, name="camera-ftp", daemon=True)

    def _run(self):
        logger.info("Camera FTP listening on %s", self.server.socket.getsockname())
        try:
            while not self.stopped.is_set():
                self.loop.loop(timeout=0.1, blocking=False)
        finally:
            self.server.close_all()
            self.loop.close()

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped.set()
        self.thread.join()
