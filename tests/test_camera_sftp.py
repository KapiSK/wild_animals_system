"""Run the camera's C++ wire protocol against a localhost SSH/SFTP server.

Set CAMERA_SFTP_TEST_LIB to a native shared build of sftp_protocol_bridge.cpp.
Model inference, real servers and camera hardware are not involved.
"""
import asyncio
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

import httpx
import paramiko
import test_transfer_protocol as helpers
from file_transfer import Inbox


class NativeClient:
    def __init__(self, lib, send, receive):
        self.lib = lib
        callback = c.CFUNCTYPE(c.c_int, c.c_void_p, c.POINTER(c.c_uint8), c.c_size_t)
        self.errors = []
        def tx(_, data, size):
            try:
                send(c.string_at(data, size))
                return 1
            except Exception as exc:
                self.errors.append(exc)
                return 0
        def rx(_, data, size):
            try:
                result = bytearray()
                while len(result) < size:
                    chunk = receive(min(7, size-len(result))) # deliberately fragment every packet
                    if not chunk:
                        return 0
                    result.extend(chunk)
                c.memmove(data, bytes(result), size)
                return 1
            except Exception as exc:
                self.errors.append(exc)
                return 0
        self.tx, self.rx = callback(tx), callback(rx)
        lib.client_new.argtypes = [callback, callback, c.c_void_p]
        lib.client_new.restype = c.c_void_p
        for name, args in {
            'free':[], 'begin':[], 'open':[c.c_char_p,c.c_int],
            'write':[c.c_char_p,c.c_size_t], 'read':[c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)],
            'close':[], 'rename':[c.c_char_p,c.c_char_p], 'valid':[], 'status':[]
        }.items():
            getattr(lib, 'client_'+name).argtypes = [c.c_void_p]+args
        self.ptr = lib.client_new(self.tx, self.rx, None)
    def call(self, name, *args):
        return getattr(self.lib, 'client_'+name)(self.ptr, *args)
    def free(self):
        self.call('free')


@unittest.skipUnless(os.getenv('CAMERA_SFTP_TEST_LIB'), 'Set CAMERA_SFTP_TEST_LIB to the compiled C++ bridge')
class CameraSftpTests(unittest.TestCase):
    ssh_server = helpers.ProtocolTests.ssh_server

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.lib = c.CDLL(os.environ['CAMERA_SFTP_TEST_LIB'])

    def scripted(self, responses):
        pending = bytearray(responses)
        writes = []
        def receive(size):
            data = bytes(pending[:size]); del pending[:size]; return data
        client = NativeClient(self.lib, writes.append, receive)
        self.addCleanup(client.free)
        return client, writes

    @staticmethod
    def packet(kind, body):
        return struct.pack('>IB',len(body)+1,kind)+body

    def test_reject_wrong_version_oversized_and_truncated_frames(self):
        for response in [self.packet(2,struct.pack('>I',4)), struct.pack('>I',4097),
                         self.packet(2,struct.pack('>I',3))[:-1]]:
            client,_ = self.scripted(response)
            self.assertFalse(client.call('begin'))
            self.assertFalse(client.call('valid'))

    def test_reject_mismatched_request_id_and_oversized_handle(self):
        version = self.packet(2,struct.pack('>I',3))
        for response in [self.packet(102,struct.pack('>II',99,1)+b'a'),
                         self.packet(102,struct.pack('>II',1,257)+b'a'*257)]:
            client,_ = self.scripted(version+response)
            self.assertTrue(client.call('begin'))
            self.assertFalse(client.call('open',b'/transfer/image',1))
            self.assertFalse(client.call('valid'))

    def test_permission_error_does_not_count_as_eof(self):
        version = self.packet(2,struct.pack('>I',3))
        handle = self.packet(102,struct.pack('>II',1,1)+b'a')
        denied = self.packet(101,struct.pack('>IIII',2,3,0,0))
        client,_ = self.scripted(version+handle+denied)
        self.assertTrue(client.call('begin'))
        self.assertTrue(client.call('open',b'/transfer/receipt',0))
        count, buffer = c.c_size_t(), c.create_string_buffer(512)
        self.assertFalse(client.call('read',buffer,512,c.byref(count)))
        self.assertEqual(client.call('status'),3)

    def test_actual_camera_protocol_upload_and_durable_log_receipt(self):
        inbox = Inbox(self.root/'transfer','edge','http://local','token',min_free=0)
        config = self.ssh_server()
        ssh = paramiko.SSHClient()
        self.addCleanup(ssh.close)
        ssh.load_host_keys(config['known_hosts'])
        ssh.connect(config['host'],port=config['port'],username=config['username'],
                    key_filename=config['key_filename'],allow_agent=False,look_for_keys=False)
        channel = ssh.get_transport().open_session()
        channel.settimeout(5)
        channel.invoke_subsystem('sftp')
        client = NativeClient(self.lib,channel.sendall,channel.recv)
        self.addCleanup(client.free)
        self.assertTrue(client.call('begin'))
        content = b'[SFTP] camera log\n'*600
        digest = hashlib.sha256(content).hexdigest()
        token = 'camera_wire_test'
        base = '/transfer/incoming/'+token
        manifest = {'version':1,'kind':'log','cycle_id':'AABB-00000001','filename':'esp_chunk.log',
                    'size':len(content),'sha256':digest}
        def upload(path,data):
            self.assertTrue(client.call('open',path.encode(),1))
            for start in range(0,len(data),2048):
                part = data[start:start+2048]
                self.assertTrue(client.call('write',part,len(part)))
            self.assertTrue(client.call('close'))
        upload(base+'.data.part',content)
        # Exclusive creation cannot overwrite another transfer's bytes.
        self.assertFalse(client.call('open',(base+'.data.part').encode(),1))
        self.assertTrue(client.call('rename',(base+'.data.part').encode(),(base+'.data').encode()))
        upload(base+'.json.part',json.dumps(manifest).encode())
        self.assertTrue(client.call('rename',(base+'.json.part').encode(),(base+'.ready').encode()))
        receipt_path = f'/transfer/receipts/{token}.json'.encode()
        self.assertFalse(client.call('open',receipt_path,0))
        self.assertEqual(client.call('status'),2) # missing receipt is safe to poll again
        async def consume():
            def api(request):
                self.assertEqual(request.url.path,'/esp_log')
                self.assertEqual(request.content,content)
                return httpx.Response(200,json={'status':'ok','sha256':digest})
            async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as http:
                await inbox.process_once(http)
        asyncio.run(consume())
        self.assertTrue(client.call('open',receipt_path,0))
        result = bytearray()
        while True:
            count, buffer = c.c_size_t(), c.create_string_buffer(512)
            self.assertTrue(client.call('read',buffer,512,c.byref(count)))
            if not count.value: break
            result.extend(buffer.raw[:count.value])
        self.assertTrue(client.call('close'))
        self.assertEqual(json.loads(result)['receipt_id'],'log:'+digest)
        self.assertEqual(list(inbox.incoming.iterdir()),[])
        self.assertEqual(client.errors,[])


if __name__ == '__main__':
    unittest.main()
