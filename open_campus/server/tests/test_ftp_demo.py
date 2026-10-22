import ftplib
import importlib
import io
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeDetector:
    calls = 0

    def detect(self, path, save_path=None):
        FakeDetector.calls += 1
        with Image.open(path) as image:
            ImageDraw.Draw(image).rectangle((2, 2, 20, 20), outline="red", width=2)
            image.save(save_path)
        return False, 0.0  # Even images without people must be published.


class FTPDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.env = patch.dict(os.environ, {
            "FTP_HOST": "127.0.0.1", "FTP_PORT": "0",
            "FTP_USER": "camera", "FTP_PASSWORD": "test-password",
            "FTP_INBOX": str(root / "inbox"),
            "PROCESSING_DIR": str(root / "processing"),
            "UPLOAD_DIR": str(root / "uploads"),
        })
        cls.env.start()
        fake = types.ModuleType("detector")
        fake.Detector = FakeDetector
        with patch.dict(sys.modules, {"detector": fake}):
            cls.main = importlib.import_module("main")
        real = cls.main.CameraFTP

        def factory(*args):
            cls.receiver = real(*args)
            cls.port = cls.receiver.server.socket.getsockname()[1]
            return cls.receiver

        cls.factory_patch = patch.object(cls.main, "CameraFTP", factory)
        cls.factory_patch.start()
        cls.client = TestClient(cls.main.app)
        cls.client.__enter__()
        data = io.BytesIO()
        Image.new("RGB", (32, 32), "white").save(data, "JPEG")
        cls.jpeg = data.getvalue()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.factory_patch.stop()
        cls.env.stop()
        cls.temp.cleanup()

    def connect(self):
        ftp = ftplib.FTP()
        ftp.connect("127.0.0.1", self.port, timeout=5)
        ftp.login("camera", "test-password")
        return ftp

    def images(self):
        return self.client.get("/api/images").json()["images"]

    def wait_count(self, count):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if len(self.images()) == count:
                return
            time.sleep(0.05)
        self.fail(f"Expected {count} images, got {self.images()}")

    def test_upload_nested_repeat_and_rename(self):
        before = len(self.images())
        calls = FakeDetector.calls
        with self.connect() as ftp:
            ftp.mkd("camera")
            ftp.cwd("camera")
            for _ in range(2):
                ftp.storbinary("STOR same.jpg", io.BytesIO(self.jpeg))
            ftp.storbinary("STOR image.tmp", io.BytesIO(self.jpeg))
            ftp.rename("image.tmp", "renamed.jpg")
        self.wait_count(before + 3)
        self.assertEqual(FakeDetector.calls, calls + 3)
        latest = self.images()[0]
        response = self.client.get("/images/" + latest)
        self.assertEqual(response.status_code, 200)
        with Image.open(io.BytesIO(response.content)) as image:
            red, green, blue = image.getpixel((3, 3))
            self.assertGreater(red, green + 50)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_invalid_and_partial_are_not_published(self):
        before = len(self.images())
        with self.connect() as ftp:
            ftp.storbinary("STOR invalid.jpg", io.BytesIO(b"not an image"))
            ftp.voidcmd("TYPE I")
            data_socket = ftp.transfercmd("STOR partial.jpg")
            data_socket.sendall(self.jpeg[:100])
            time.sleep(0.2)
            self.assertEqual(len(self.images()), before)
            data_socket.close()
            ftp.voidresp()
        time.sleep(0.3)
        self.assertEqual(len(self.images()), before)

    def test_authentication_required(self):
        with ftplib.FTP() as ftp:
            ftp.connect("127.0.0.1", self.port, timeout=5)
            with self.assertRaises(ftplib.error_perm):
                ftp.login("camera", "wrong-password")


if __name__ == "__main__":
    unittest.main()
