import csv
import http.client
import io
import json
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from PIL import Image
from common import digest, write_json
from server import Handler, Receiver
from sender import send_event
from analyze import reconcile, summarize, wilson
from energy import integrate
from run_iperf import receiver_stats


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.storage = self.root / "received"
        self.server = Receiver(("127.0.0.1",0),dict(storage=str(self.storage),max_image_bytes=1000000,read_timeout_s=2))
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        b = io.BytesIO()
        Image.new("RGB",(32,32),"green").save(b,format="JPEG")
        self.data=b.getvalue()
        p=self.root / "input.jpg"
        p.write_bytes(self.data)
        self.images=[dict(index=i,path=str(p),bytes=len(self.data),sha256=digest(self.data)) for i in range(1,4)]
        self.job=dict(device_id="cam01",cycle_id="trial1",images=self.images,image_count=3,payload_bytes=3*len(self.data),
                      condition_id="test",trial_id=1,planned_utc="2026-10-08T00:00:00+00:00")
        self.settings=dict(host="127.0.0.1",port=self.server.server_port,source_ip="127.0.0.1",
                           connect_timeout_s=1,event_deadline_s=5,max_retries=0,reuse_connection=True)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self,path="/upload",data=None,index=1,device="cam01",sha=None):
        data=self.data if data is None else data
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=2)
        conn.request("POST",path,data,{"X-Device-Id":device,"X-Cycle-Id":"trial1","X-Img-Index":str(index),
                                      "X-Content-SHA256":sha or digest(data),"Content-Type":"image/jpeg"})
        r=conn.getresponse()
        result=(r.status,json.loads(r.read()))
        conn.close()
        return result

    def test_success_and_idempotent_event_retry(self):
        first=send_event(self.settings,self.job)
        second=send_event(self.settings,self.job)
        self.assertTrue(first["ack_received"])
        self.assertTrue(second["ack_received"])
        self.assertEqual(len(list(self.storage.rglob("*.jpg"))),3)

    def test_hash_path_conflict_and_missing(self):
        self.assertEqual(self.request(sha="0"*64)[0],400)
        self.assertEqual(self.request(device="../escape")[0],400)
        self.assertEqual(self.request()[0],200)
        self.assertTrue(self.request()[1]["duplicate"])
        b=io.BytesIO()
        Image.new("RGB",(32,32),"red").save(b,format="JPEG")
        self.assertEqual(self.request(data=b.getvalue())[0],409)
        self.assertEqual(self.request(path="/complete",data=json.dumps({"images":self.images}).encode())[0],409)

    def test_partial_upload_never_saved(self):
        sock=socket.create_connection(("127.0.0.1",self.server.server_port))
        header=(f"POST /upload HTTP/1.1\r\nHost: localhost\r\nX-Device-Id: cam01\r\nX-Cycle-Id: trial1\r\n"
                f"X-Img-Index: 1\r\nX-Content-SHA256: {digest(self.data)}\r\nContent-Type: image/jpeg\r\n"
                f"Content-Length: {len(self.data)}\r\n\r\n").encode()
        sock.sendall(header+self.data[:10])
        sock.shutdown(socket.SHUT_WR)
        sock.recv(1024)
        sock.close()
        self.assertFalse(list(self.storage.rglob("*.jpg")))

    def test_total_deadline_with_stalled_response(self):
        class Slow(BaseHTTPRequestHandler):
            def do_POST(self):
                time.sleep(2)
            def log_message(self,*args):
                pass
        slow=ThreadingHTTPServer(("127.0.0.1",0),Slow)
        slow.daemon_threads=True
        t=threading.Thread(target=slow.serve_forever,daemon=True)
        t.start()
        try:
            started=time.perf_counter()
            result=send_event(dict(self.settings,port=slow.server_port,event_deadline_s=.6),self.job)
            self.assertEqual(result["status"],"deadline_exceeded")
            self.assertLess(time.perf_counter()-started,1.8)
        finally:
            slow.shutdown()
            slow.server_close()

    def test_lost_ack_reconciled_from_disk_and_unknown_without_disk(self):
        for i in range(1,4):
            self.assertEqual(self.request(index=i)[0],200)
        jobs=self.root / "run" / "jobs"
        jobs.mkdir(parents=True)
        write_json(jobs / "001.json",self.job)
        # Simulate sender death after storage and before its final trial record.
        rows=reconcile(jobs.parent,self.storage)
        summary=summarize(rows)
        self.assertEqual(summary["ack_lost_after_storage"],1)
        self.assertEqual(summary["failures"],1)
        self.assertEqual(summary["server_event_rate"],1)
        self.assertIsNone(summarize(reconcile(jobs.parent))["server_event_rate"])

    def test_connection_refused_is_failure(self):
        probe=socket.socket()
        probe.bind(("127.0.0.1",0))
        port=probe.getsockname()[1]
        probe.close()
        result=send_event(dict(self.settings,port=port),self.job)
        self.assertFalse(result["ack_received"])
        self.assertEqual(result["status"],"failed")

    def test_energy_and_confidence_interval(self):
        p=self.root / "energy.csv"
        p.write_text("device_id,cycle_id,time_s,voltage_v,current_a\ncam01,trial1,0,5,1\ncam01,trial1,2,5,3\n",encoding="utf-8")
        self.assertEqual(integrate(p)[0]["energy_j"],20)
        self.assertLess(wilson(100,100)[0],.99)
        self.assertEqual(wilson(0,0),[None,None])

    def test_actual_complete_ack_loss_and_bounded_retry(self):
        original = Handler.respond
        dropped = []

        def drop_once(handler, status, obj):
            if handler.path == "/complete" and obj.get("complete") and not dropped:
                dropped.append(True)
                handler.close_connection = True
                handler.connection.shutdown(socket.SHUT_RDWR)
                return
            return original(handler,status,obj)

        with patch.object(Handler,"respond",drop_once):
            result = send_event(dict(self.settings,max_retries=1,retry_delay_s=0),self.job)
        self.assertTrue(result["ack_received"])
        self.assertEqual(result["app_retries"],1)
        self.assertEqual(len(list(self.storage.rglob("*.jpg"))),3)

    def test_missing_snapshot_rejected_and_torn_log_recovered(self):
        jobs=self.root / "run" / "jobs"
        jobs.mkdir(parents=True)
        write_json(jobs / "001.json",self.job)
        with self.assertRaises(ValueError):
            reconcile(jobs.parent,self.root / "does_not_exist")
        (jobs.parent / "trials.jsonl").write_text('{"cycle_id":',encoding="utf-8")
        with self.assertWarns(UserWarning):
            rows=reconcile(jobs.parent)
        self.assertEqual(rows[0]["status"],"interrupted_unknown")

    def test_iperf_does_not_substitute_sender_stats(self):
        self.assertIsNone(receiver_stats({"end":{"sum_sent":{"bits_per_second":100}}}))
        self.assertIsNone(receiver_stats({"end":{"sum":{"sender":True}}},True))
        self.assertEqual(receiver_stats({"end":{"sum_received":{"bits_per_second":99}}})["bits_per_second"],99)


if __name__ == "__main__":
    unittest.main()
