"""Real localhost FTP/SFTP plus spool failures; never contacts deployed servers."""
import asyncio
import errno
import ftplib
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import httpx
import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from file_transfer import Inbox, send_sftp, validate_manifest
from pipeline_common import InvalidUpload
from transfer_receiver import make_ftp_server


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.inbox = Inbox(self.root/'transfer','edge','http://local','test-token',min_free=0)
        self.content = b'transfer bytes (API decoding tested separately)'
        self.message = {'version':1,'kind':'image','filename':'AABB-00000001-1n.jpg',
                        'cycle_id':'AABB-00000001','image_index':1,'size':len(self.content),
                        'sha256':hashlib.sha256(self.content).hexdigest()}
        self.receipt = {'status':'ok','receipt_id':'AABB-00000001:1','sha256':self.message['sha256']}
        self.token = '0123456789abcdef0123456789abcdef'

    def publish(self, message=None):
        (self.inbox.incoming/(self.token+'.data')).write_bytes(self.content)
        (self.inbox.incoming/(self.token+'.ready')).write_text(json.dumps(message or self.message),encoding='utf-8')

    def consume(self, handler):
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await self.inbox.process_once(client)
        asyncio.run(run())

    def test_no_receipt_on_application_error_and_restart_recovers(self):
        self.publish()
        self.consume(lambda _:httpx.Response(503))
        self.assertTrue((self.inbox.incoming/(self.token+'.ready')).exists())
        self.assertFalse((self.inbox.receipts/(self.token+'.json')).exists())
        self.inbox = Inbox(self.inbox.root,'edge','http://local','test-token',min_free=0)
        self.consume(lambda _:httpx.Response(200,json=self.receipt))
        self.assertEqual(json.loads((self.inbox.receipts/(self.token+'.json')).read_text())['status'],'ok')
        self.assertFalse((self.inbox.incoming/(self.token+'.data')).exists())

    def test_200_error_json_is_not_acknowledged(self):
        self.publish()
        self.consume(lambda _:httpx.Response(200,json={'status':'error'}))
        self.assertFalse((self.inbox.receipts/(self.token+'.json')).exists())
        self.assertTrue((self.inbox.incoming/(self.token+'.data')).exists())

    def test_unsafe_manifest_and_hash_rejection(self):
        bad = dict(self.message,filename='../AABB-00000001-1n.jpg')
        with self.assertRaises(InvalidUpload):
            validate_manifest(bad,'edge')
        self.publish()
        self.consume(lambda _:httpx.Response(422))
        self.assertEqual(json.loads((self.inbox.receipts/(self.token+'.json')).read_text())['status'],'error')

    def test_partial_data_is_not_ingested_and_pending_files_not_pruned(self):
        data = self.inbox.incoming/(self.token+'.data.part')
        data.write_bytes(b'partial')
        calls = []
        self.consume(lambda request:calls.append(request))
        self.assertEqual(calls,[])
        self.publish()
        for path in self.inbox.incoming.iterdir():
            os.utime(path,(0,0))
        self.inbox.cleanup()
        self.assertTrue((self.inbox.incoming/(self.token+'.ready')).exists())
        self.assertTrue((self.inbox.incoming/(self.token+'.data')).exists())

    def ftp_server(self):
        server = make_ftp_server(self.inbox,'127.0.0.1',0,'camera','test-password',[])
        thread = threading.Thread(target=server.serve_forever,kwargs={'timeout':.05},daemon=True)
        thread.start()
        def stop():
            server.close_all()
            thread.join(timeout=2)
        self.addCleanup(stop)
        return server.socket.getsockname()[1]

    def test_actual_ftp_upload_rename_receipt_and_readonly_receipts(self):
        port = self.ftp_server()
        with ftplib.FTP() as ftp:
            ftp.connect('127.0.0.1',port,timeout=5)
            ftp.login('camera','test-password')
            base = 'incoming/'+self.token
            ftp.storbinary('STOR '+base+'.data.part',io.BytesIO(self.content))
            ftp.rename(base+'.data.part',base+'.data')
            ftp.storbinary('STOR '+base+'.json.part',io.BytesIO(json.dumps(self.message).encode()))
            ftp.rename(base+'.json.part',base+'.ready')
            with self.assertRaises(ftplib.error_perm):
                ftp.retrbinary('RETR receipts/'+self.token+'.json',lambda _:None)
            self.consume(lambda _:httpx.Response(200,json=self.receipt))
            response = io.BytesIO()
            ftp.retrbinary('RETR receipts/'+self.token+'.json',response.write)
            self.assertEqual(json.loads(response.getvalue())['sha256'],self.message['sha256'])
            with self.assertRaises(ftplib.error_perm):
                ftp.storbinary('STOR receipts/forged.json',io.BytesIO(b'{}'))
            with self.assertRaises(ftplib.error_perm):
                ftp.storbinary('STOR incoming/'+self.token+'.ready',io.BytesIO(b'{}'))

    def ssh_server(self):
        root = self.root
        client_key = paramiko.RSAKey.generate(2048)
        host_key = paramiko.RSAKey.generate(2048)
        key_path = root/'client_key'
        client_key.write_private_key_file(str(key_path))
        listener = socket.socket()
        listener.bind(('127.0.0.1',0))
        listener.listen(4)
        listener.settimeout(.2)
        port = listener.getsockname()[1]
        known = root/'known_hosts'
        known.write_text(f'[127.0.0.1]:{port} {host_key.get_name()} {host_key.get_base64()}\n')
        class Auth(paramiko.ServerInterface):
            def check_auth_publickey(self, username, key):
                return paramiko.AUTH_SUCCESSFUL if username=='edge' and key==client_key else paramiko.AUTH_FAILED
            def get_allowed_auths(self, username):
                return 'publickey'
            def check_channel_request(self, kind, channel_id):
                return paramiko.OPEN_SUCCEEDED if kind=='session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
        class Files(paramiko.SFTPServerInterface):
            def local(self,path):
                resolved = (root/path.lstrip('/')).resolve()
                if not resolved.is_relative_to(root):
                    raise PermissionError()
                return resolved
            def stat(self,path):
                try:
                    return paramiko.SFTPAttributes.from_stat(self.local(path).stat())
                except OSError as exc:
                    return paramiko.SFTPServer.convert_errno(exc.errno)
            def open(self,path,flags,attr):
                try:
                    fd = os.open(self.local(path),flags|getattr(os,'O_BINARY',0),0o600)
                    mode = 'wb' if flags & os.O_WRONLY else 'rb'
                    stream = os.fdopen(fd,mode)
                    handle = paramiko.SFTPHandle(flags)
                    if 'w' in mode: handle.writefile=stream
                    else: handle.readfile=stream
                    return handle
                except OSError as exc:
                    return paramiko.SFTPServer.convert_errno(exc.errno)
            def rename(self,old,new):
                try:
                    os.rename(self.local(old),self.local(new))
                    return paramiko.SFTP_OK
                except OSError as exc:
                    return paramiko.SFTPServer.convert_errno(exc.errno)
        stop = threading.Event()
        transports = []
        def serve():
            while not stop.is_set():
                try:
                    sock,_ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                transport = paramiko.Transport(sock)
                transports.append(transport)
                transport.add_server_key(host_key)
                transport.set_subsystem_handler('sftp',paramiko.SFTPServer,Files)
                try:
                    transport.start_server(server=Auth())
                except (EOFError,OSError,paramiko.SSHException):
                    transport.close()
        thread = threading.Thread(target=serve,daemon=True)
        thread.start()
        def close():
            stop.set()
            listener.close()
            for transport in transports: transport.close()
            thread.join(timeout=2)
        self.addCleanup(close)
        return {'host':'127.0.0.1','port':port,'username':'edge','key_filename':str(key_path),
                'known_hosts':str(known),'remote_root':'/transfer','timeout':3}

    def test_actual_sftp_requires_host_key_and_application_receipt(self):
        config = self.ssh_server()
        path = self.root/'source.jpg'
        path.write_bytes(self.content)
        self.inbox.role='cloud'
        async def exercise():
            task = asyncio.create_task(asyncio.to_thread(send_sftp,path,self.message,config))
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=self.receipt))) as client:
                deadline = time.monotonic()+10
                while not task.done() and time.monotonic()<deadline:
                    await self.inbox.process_once(client)
                    await asyncio.sleep(.02)
            return await task
        receipt = asyncio.run(exercise())
        self.assertEqual(receipt['receipt_id'],self.receipt['receipt_id'])
        Path(config['known_hosts']).write_text('')
        with self.assertRaises(paramiko.SSHException):
            send_sftp(path,self.message,config)

    def test_sftp_receipt_timeout_keeps_committed_spool(self):
        config = self.ssh_server()
        config['timeout']=1
        path = self.root/'source.jpg'
        path.write_bytes(self.content)
        with self.assertRaises(TimeoutError):
            send_sftp(path,self.message,config)
        self.assertEqual(len(list(self.inbox.incoming.glob('*.ready'))),1)
        self.assertEqual(len(list(self.inbox.incoming.glob('*.data'))),1)


if __name__ == '__main__':
    unittest.main()
