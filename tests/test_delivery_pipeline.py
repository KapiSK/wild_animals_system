"""Offline failure/retry tests. Models and SMTP are never executed."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch, AsyncMock

import cv2
import numpy as np
import httpx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline_common import (Store, ReceiptConflict, InvalidUpload, StorageFull,
                             receive_file, image_identity, worker)
from file_transfer import Inbox


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'queue.sqlite3')

    def accept(self, idx=1, content=b'image', cycle='CAM-1', age=0):
        temporary = self.root / 'incoming.part'
        temporary.write_bytes(content)
        key = f'{cycle}:{idx}'
        return self.store.accept(key, cycle, idx, hashlib.sha256(content).hexdigest(),
            temporary, self.root/f'{cycle}-{idx}.jpg', {'received_at': time.time()-age})

    def test_receipt_and_job_survive_restart_and_deduplicate(self):
        self.accept()
        self.store = Store(self.store.path)
        _, duplicate = self.accept()
        self.assertTrue(duplicate)
        self.assertEqual(len(self.store.images('CAM-1')), 1)
        self.assertIsNotNone(self.store.claim('infer'))
        self.assertIsNone(self.store.claim('infer'))

    def test_different_bytes_same_identity_rejected(self):
        self.accept()
        with self.assertRaises(ReceiptConflict):
            self.accept(content=b'changed')
        self.assertEqual(Path(self.store.image('CAM-1:1')['path']).read_bytes(), b'image')

    def test_expired_lease_reclaimed_and_old_owner_cannot_complete(self):
        self.accept()
        first = self.store.claim('infer', lease_seconds=-1)
        second = self.store.claim('infer')
        self.store.complete(first)
        self.assertEqual(self.store.job('infer:CAM-1:1')['state'], 'working')
        self.store.retry(second, 'offline', delay=0)
        third = self.store.claim('infer')
        self.store.complete(third)
        self.assertEqual(self.store.job('infer:CAM-1:1')['state'], 'done')

    def test_cleanup_protects_unsettled_cycles_and_keeps_receipts(self):
        self.accept(age=10*86400)
        self.accept(idx=2, age=10*86400)
        self.store.terminal('CAM-1:1')
        self.store.cleanup()
        self.assertTrue(Path(self.store.image('CAM-1:1')['path']).exists())
        self.store.terminal('CAM-1:2')
        self.store.cleanup()
        self.assertFalse(Path(self.store.image('CAM-1:1')['path']).exists())
        self.assertIsNotNone(self.store.image('CAM-1:1'))

    def test_sequence_stable_after_other_events(self):
        self.assertEqual(self.store.sequence('CAM', 'old', 20), 21)
        self.assertEqual(self.store.sequence('CAM', 'new'), 22)
        self.assertEqual(Store(self.store.path).sequence('CAM', 'old', 99), 21)

    def test_stream_rejects_corruption_empty_and_size_mismatch(self):
        async def chunks(data):
            yield data
        for data, digest, length in [(b'x','0'*64,1),(b'',None,0),(b'x',None,2)]:
            with self.assertRaises(InvalidUpload):
                asyncio.run(receive_file(chunks(data), self.root, digest, length, min_free=0))
        self.assertEqual(list(self.root.glob('*.part')), [])

    def test_no_success_when_fsync_fails(self):
        async def chunks():
            yield b'x'
        with patch('pipeline_common.os.fsync', side_effect=OSError('disk failed')):
            with self.assertRaises(OSError):
                asyncio.run(receive_file(chunks(), self.root, min_free=0))
        self.assertEqual(list(self.root.glob('*.part')), [])

    def test_prefixes_and_headers_resolve_same_identity(self):
        expected = ('AABB-00000001', 1, 'AABB-00000001:1')
        self.assertEqual(image_identity('20261002_010203_123_pi_Rcv010203_AABB-00000001-1n.jpg'), expected)
        with self.assertRaises(InvalidUpload):
            image_identity('AABB-00000001-1n.jpg', index='2')

    def test_atomic_receipt_rolls_back_if_job_registration_fails(self):
        with patch.object(self.store, '_enqueue', side_effect=OSError('DB full')):
            with self.assertRaises(OSError):
                self.accept()
        self.assertIsNone(self.store.image('CAM-1:1'))
        # The unacknowledged orphan is safely replaced by the retry.
        self.accept()
        self.assertIsNotNone(self.store.claim('infer'))

    def test_slow_forward_worker_does_not_block_inference(self):
        self.store.enqueue('forward:x','forward',{})
        self.store.enqueue('infer:x','infer',{})
        async def exercise():
            blocked, inferred = asyncio.Event(), asyncio.Event()
            async def forward(_):
                await blocked.wait()
            async def infer(_):
                inferred.set()
            tasks = [asyncio.create_task(worker(self.store,'forward',forward)),
                     asyncio.create_task(worker(self.store,'infer',infer))]
            try:
                await asyncio.wait_for(inferred.wait(), timeout=5)
                self.assertFalse(blocked.is_set())
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
        asyncio.run(exercise())

    def test_worker_cancellation_during_lease_cleanup_is_not_swallowed(self):
        self.store.enqueue('infer:shutdown', 'infer', {})
        async def exercise():
            create_task = asyncio.create_task
            renewal_started, renewal_stopping = asyncio.Event(), asyncio.Event()
            def delayed_renewal(coro):
                async def renewal():
                    renewal_started.set()
                    try:
                        await coro
                    finally:
                        renewal_stopping.set()
                        await asyncio.Event().wait()
                return create_task(renewal())
            async def handle(_):
                await renewal_started.wait()
            with patch('pipeline_common.asyncio.create_task', side_effect=delayed_renewal):
                task = create_task(worker(self.store, 'infer', handle))
                try:
                    await asyncio.wait_for(renewal_stopping.wait(), timeout=5)
                    task.cancel()
                    done, _ = await asyncio.wait({task}, timeout=2)
                    self.assertIn(task, done)
                    self.assertTrue(task.cancelled())
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        asyncio.run(exercise())


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        old_cwd = os.getcwd()
        os.chdir(cls.root)
        (cls.root/'md_v5a.0.0.pt').touch()
        model = types.SimpleNamespace(names={0:'animal',1:'person'})
        stub_detector = types.SimpleNamespace(Detector=lambda: None)
        variables = {'UPLOAD_DIR': str(cls.root/'uploads'), 'PROCESSED_DIR': str(cls.root/'processed'),
                     'VIDEO_DIR': str(cls.root/'videos'), 'EVENT_METADATA_DIR': str(cls.root/'events'),
                     'SERVER_SEQUENCE_FILE': str(cls.root/'seq.json'), 'PIPELINE_DB': str(cls.root/'initial.sqlite3')}
        def load(name, path):
            spec = importlib.util.spec_from_file_location(name, ROOT/path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module
        try:
            with patch.dict(os.environ, variables), patch.dict(sys.modules, {
                'detector': stub_detector, 'yolov5': types.SimpleNamespace(load=lambda _:model),
                'torch': types.SimpleNamespace(load=lambda *a, **kw:None)}):
                cls.edge = load('edge_delivery_test', 'KD_pi_server/main.py')
                cls.cloud = load('cloud_delivery_test', 'original_server/server.py')
        finally:
            os.chdir(old_cwd)
        _, jpeg = cv2.imencode('.jpg', np.zeros((8,8,3), dtype=np.uint8))
        cls.jpeg = jpeg.tobytes()
        cls.digest = hashlib.sha256(cls.jpeg).hexdigest()

    @classmethod
    def tearDownClass(cls):
        import logging
        for handler in list(logging.getLogger().handlers):
            if isinstance(handler, logging.FileHandler) and str(cls.root) in handler.baseFilename:
                handler.close()
                logging.getLogger().removeHandler(handler)
        cls.temp.cleanup()

    def setUp(self):
        self.folder = self.root / self._testMethodName
        self.folder.mkdir()
        self.edge.store = Store(self.folder/'edge.sqlite3')
        self.cloud.delivery_store = Store(self.folder/'cloud.sqlite3')
        self.edge.NEGATIVE_SAMPLE_RATE = 0
        self.edge.CYCLE_TIMEOUT = 300
        self.edge.LOCAL_MODE = False
        self.edge.CLOUD_TRANSFER_MODE = 'http'
        self.edge.MAIN_SERVER_URL = 'http://cloud/upload'
        self.edge.detector = types.SimpleNamespace(model_path='fake.onnx', confidence=.004,
                                                   detect=lambda _: (False, 'empty'))
        self.cloud.replace_mac_in_filename = lambda name:name
        self.cloud.get_camera_id = lambda name:name
        self.cloud.load_server_sequence = lambda:{}
        self.cloud.save_server_sequence = lambda _:None
        self.cloud._EVENT_METADATA_CACHE.clear()
        self.edge_client = TestClient(self.edge.app)
        self.cloud_client = TestClient(self.cloud.app)
        self.addCleanup(self.edge_client.close)
        self.addCleanup(self.cloud_client.close)

    def upload_edge(self, idx=1, data=None, digest=None):
        return self.edge_client.post('/upload', content=self.jpeg if data is None else data, headers={
            'X-API-KEY': self.edge.API_TOKEN, 'X-Cycle-Id':'AABB-00000001', 'X-Img-Index':str(idx),
            'X-File-Name':f'AABB-00000001-{idx}n.jpg', 'X-Content-SHA256':digest or self.digest})

    def test_edge_receipt_and_duplicate_do_not_count_as_three(self):
        self.assertEqual(self.upload_edge(1).status_code, 200)
        self.upload_edge(2)
        duplicate = self.upload_edge(1)
        self.assertTrue(duplicate.json()['duplicate'])
        asyncio.run(self.edge.infer_image({'key':'AABB-00000001:1'}))
        asyncio.run(self.edge.infer_image({'key':'AABB-00000001:2'}))
        asyncio.run(self.edge.aggregate_once())
        self.assertEqual(len(self.edge.store.images('AABB-00000001')), 2)
        self.assertIsNone(self.edge.store.claim('forward'))
        self.assertIn('AABB-00000001', self.edge.store.pending_cycles())

    def test_edge_failures_are_not_200(self):
        self.assertEqual(self.upload_edge(digest='0'*64).status_code, 422)
        with patch.object(self.edge.store, 'accept', side_effect=OSError('disk error')):
            self.assertEqual(self.upload_edge().status_code, 500)
        with patch.object(self.edge, 'receive_file', side_effect=StorageFull('disk full')):
            self.assertEqual(self.upload_edge().status_code, 507)
        self.assertEqual(self.edge.store.images('AABB-00000001'), [])

    def test_partial_negative_audit_and_early_exit_have_distinct_states(self):
        self.edge.CYCLE_TIMEOUT = 0
        self.edge.NEGATIVE_SAMPLE_RATE = 1
        self.upload_edge()
        asyncio.run(self.edge.infer_image({'key':'AABB-00000001:1'}))
        asyncio.run(self.edge.aggregate_once())
        self.assertEqual(self.edge.store.job('forward:AABB-00000001:1')['payload']['reason'], 'negative_sample')
        self.upload_edge(2)
        self.edge.detector.detect = lambda _: (True, 'animal')
        asyncio.run(self.edge.infer_image({'key':'AABB-00000001:2'}))
        self.upload_edge(3)
        asyncio.run(self.edge.infer_image({'key':'AABB-00000001:3'}))
        self.assertEqual(self.edge.store.image('AABB-00000001:3')['result']['decision'], 'skipped')

    def test_cloud_error_body_not_accepted_as_success(self):
        self.upload_edge()
        asyncio.run(self.edge.infer_image({'key':'AABB-00000001:1'}))
        response = httpx.Response(200, json={'status':'error'}, request=httpx.Request('POST','http://cloud/upload'))
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = response
        with patch.object(self.edge.httpx, 'AsyncClient', return_value=client):
            with self.assertRaises(RuntimeError):
                asyncio.run(self.edge.forward_image({'key':'AABB-00000001:1','reason':'positive'}))
        self.assertNotIn('forwarded', self.edge.store.image('AABB-00000001:1')['result'])

    def test_spool_receipts_share_http_deduplication_on_both_servers(self):
        self.upload_edge()
        message = {'version':1, 'kind':'image', 'filename':'AABB-00000001-1n.jpg',
                   'cycle_id':'AABB-00000001', 'image_index':1, 'size':len(self.jpeg),
                   'sha256':self.digest, 'edge_decision':'negative', 'transfer_reason':'negative_sample'}
        async def exercise(role, app, api_token):
            inbox = Inbox(self.folder/role, role, 'http://local', api_token, min_free=0)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                for token in ('first_transfer', 'repeat_transfer'):
                    (inbox.incoming/(token+'.data')).write_bytes(self.jpeg)
                    (inbox.incoming/(token+'.ready')).write_text(json.dumps(message), encoding='utf-8')
                    await inbox.process_once(client)
                    receipt = json.loads((inbox.receipts/(token+'.json')).read_text())
                    self.assertEqual(receipt['receipt_id'], 'AABB-00000001:1')
                    self.assertEqual(receipt['sha256'], self.digest)
                    self.assertEqual(receipt['status'], 'ok')
                    if token == 'repeat_transfer':
                        self.assertTrue(receipt['duplicate'])
            self.assertEqual(list(inbox.incoming.iterdir()), [])
        asyncio.run(exercise('edge', self.edge.app, self.edge.API_TOKEN))
        asyncio.run(exercise('cloud', self.cloud.app, self.cloud.API_TOKEN))
        self.assertEqual(len(self.edge.store.images('AABB-00000001')), 1)
        rows = self.cloud.delivery_store.images('AABB-00000001')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['payload']['transfer_reason'], 'negative_sample')

    def test_ftp_log_spool_checks_hash_before_receipt(self):
        inbox = Inbox(self.folder/'logs', 'edge', 'http://local', self.edge.API_TOKEN, min_free=0)
        content = b'[FTP] Connection/login OK\n'
        digest = hashlib.sha256(content).hexdigest()
        message = {'version':1, 'kind':'log', 'filename':'esp_chunk.log', 'cycle_id':'AABB-00000001',
                   'size':len(content), 'sha256':digest}
        async def exercise():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.edge.app)) as client:
                for token, content_hash in [('valid_log', digest), ('invalid_log', '0'*64)]:
                    message['sha256'] = content_hash
                    (inbox.incoming/(token+'.data')).write_bytes(content)
                    (inbox.incoming/(token+'.ready')).write_text(json.dumps(message), encoding='utf-8')
                    await inbox.process_once(client)
        asyncio.run(exercise())
        receipt = json.loads((inbox.receipts/'valid_log.json').read_text())
        self.assertEqual(receipt['receipt_id'], 'log:'+digest)
        self.assertEqual(receipt['status'], 'ok')
        self.assertEqual(json.loads((inbox.receipts/'invalid_log.json').read_text())['status'], 'error')

    def test_sftp_forward_failure_retains_image_and_success_records_transport(self):
        self.upload_edge()
        asyncio.run(self.edge.infer_image({'key':'AABB-00000001:1'}))
        self.edge.CLOUD_TRANSFER_MODE = 'sftp'
        self.edge.MAIN_SERVER_URL = None
        payload = {'key':'AABB-00000001:1','reason':'negative_sample'}
        with patch.object(self.edge, 'send_sftp', side_effect=TimeoutError('receipt missing')):
            with self.assertRaises(TimeoutError):
                asyncio.run(self.edge.forward_image(payload))
        row = self.edge.store.image(payload['key'])
        self.assertTrue(Path(row['path']).exists())
        self.assertNotIn('forwarded', row['result'])
        with patch.object(self.edge, 'send_sftp', return_value={}) as sender:
            asyncio.run(self.edge.forward_image(payload))
        self.assertEqual(sender.call_args.args[1]['sha256'], self.digest)
        self.assertEqual(sender.call_args.args[1]['transfer_reason'], 'negative_sample')
        self.assertEqual(self.edge.store.image(payload['key'])['result']['transport'], 'sftp')

    def test_end_to_end_receipt_retry_and_cloud_inference_recovery(self):
        self.upload_edge()
        asyncio.run(self.edge.infer_image({'key':'AABB-00000001:1'}))
        actual_client = httpx.AsyncClient
        def client_factory(**kwargs):
            return actual_client(transport=httpx.ASGITransport(app=self.cloud.app))
        with patch.object(self.edge.httpx, 'AsyncClient', side_effect=client_factory):
            for _ in range(2):
                asyncio.run(self.edge.forward_image({'key':'AABB-00000001:1','reason':'negative_sample'}))
        rows = self.cloud.delivery_store.images('AABB-00000001')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['payload']['transfer_reason'], 'negative_sample')
        self.cloud.delivery_store = Store(self.cloud.delivery_store.path)
        self.assertIsNotNone(self.cloud.delivery_store.claim('infer'))
        self.assertTrue(self.edge.store.image('AABB-00000001:1')['result']['forwarded'])

    def test_cloud_hash_and_disk_failures(self):
        headers={'X-API-KEY':self.cloud.API_TOKEN,'X-Content-SHA256':self.digest}
        files={'file':('pi_Rcv120000_AABB-00000001-1n.jpg',self.jpeg,'image/jpeg')}
        with patch.object(self.cloud.delivery_store, 'accept', side_effect=OSError(28,'full')):
            self.assertEqual(self.cloud_client.post('/upload',files=files,headers=headers).status_code,507)
        headers['X-Content-SHA256'] = '0'*64
        self.assertEqual(self.cloud_client.post('/upload',files=files,headers=headers).status_code,422)

    def test_distinct_numbered_camera_names_do_not_share_cloud_folder(self):
        for camera in ('CAM_01', 'CAM_02'):
            response = self.cloud_client.post('/upload', headers={'X-API-KEY':self.cloud.API_TOKEN},
                files={'file':(f'pi_Rcv120000_{camera}-00000001-1n.jpg', self.jpeg, 'image/jpeg')})
            self.assertEqual(response.status_code,200)
            row = self.cloud.delivery_store.image(f'{camera}-00000001:1')
            self.assertEqual(Path(row['path']).parent.name, camera)

    def test_gallery_keeps_legacy_images_and_hides_database(self):
        legacy = Path(self.edge.UPLOAD_DIR)/'legacy.jpg'
        legacy.write_bytes(self.jpeg)
        self.addCleanup(lambda: legacy.unlink(missing_ok=True))
        self.assertIn('legacy.jpg', self.edge_client.get('/api/images').json()['images'])
        self.assertEqual(self.edge_client.get('/images/legacy.jpg').status_code,200)
        self.assertEqual(self.edge_client.get('/images/pipeline.sqlite3').status_code,404)

    def test_notification_exception_retains_job(self):
        self.cloud.delivery_store.enqueue('notify:test','notify',{'subject':'test','body':'test','origin_cycle':'test'})
        async def exercise():
            with patch.object(self.cloud,'send_email',side_effect=OSError('SMTP unavailable')):
                task = asyncio.create_task(worker(self.cloud.delivery_store,'notify',self.cloud.notify_cloud_cycle))
                for _ in range(100):
                    await asyncio.sleep(.01)
                    job = self.cloud.delivery_store.job('notify:test')
                    if job['error']:
                        break
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
        asyncio.run(exercise())
        job = self.cloud.delivery_store.job('notify:test')
        self.assertEqual(job['state'],'ready')
        self.assertIn('SMTP unavailable',job['error'])

    def test_cloud_partial_cycle_late_arrivals_update_metadata_without_renotifying(self):
        def analyze(path, filename, source):
            return {'filename':filename,'event_id':self.cloud.extract_cycle_id(filename),
                    'camera_id':'AABB','source':source,'target_count':1,'max_conf':.8,
                    'annotated_path':path,'summary_text':'animal: 1','labels':['animal'],'detections':[]}
        async def process_ready():
            while job := self.cloud.delivery_store.claim('infer'):
                await self.cloud.infer_received_image(job['payload'])
                self.cloud.delivery_store.complete(job)
            await self.cloud.schedule_cloud_cycles_once()
            while job := self.cloud.delivery_store.claim('aggregate'):
                await self.cloud.aggregate_cloud_cycle(job['payload'])
                self.cloud.delivery_store.complete(job)
        old_cwd = os.getcwd()
        os.chdir(self.folder)
        try:
            with patch.object(self.cloud,'analyze_image_for_cycle',side_effect=analyze), \
                 patch.object(self.cloud,'CYCLE_TIMEOUT_SECONDS',0), \
                 patch.object(self.cloud,'get_recipients_for_camera',return_value=['__NONE__']):
                for idx in (1,2,3):
                    response = self.cloud_client.post('/upload',headers={'X-API-KEY':self.cloud.API_TOKEN},
                        files={'file':(f'pi_Rcv120000_AABB-00000001-{idx}n.jpg',self.jpeg,'image/jpeg')})
                    self.assertEqual(response.status_code,200)
                    asyncio.run(process_ready())
                    metadata = self.cloud.load_event_metadata('AABB','AABB_0001')
                    self.assertEqual(metadata['received_indices'],list(range(1,idx+1)))
                    self.assertEqual(metadata['complete'],idx==3)
                notify = self.cloud.delivery_store.claim('notify')
                self.cloud.delivery_store.complete(notify)
                self.assertIsNone(self.cloud.delivery_store.claim('notify'))
        finally:
            os.chdir(old_cwd)

    def test_positive_arriving_after_partial_negative_reopens_forwarding(self):
        self.edge.CYCLE_TIMEOUT = 0
        self.upload_edge(1)
        asyncio.run(self.edge.infer_image({'key':'AABB-00000001:1'}))
        asyncio.run(self.edge.aggregate_once())
        self.assertTrue(self.edge.store.image('AABB-00000001:1')['terminal'])
        self.upload_edge(2)
        self.edge.detector.detect = lambda _: (True,'animal')
        asyncio.run(self.edge.infer_image({'key':'AABB-00000001:2'}))
        asyncio.run(self.edge.aggregate_once())
        self.assertFalse(self.edge.store.image('AABB-00000001:1')['terminal'])
        self.assertIsNotNone(self.edge.store.job('forward:AABB-00000001:1'))


if __name__ == '__main__':
    unittest.main()
