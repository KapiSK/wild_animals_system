"""Run a Pi FTP inbox, or consume an OpenSSH SFTP inbox on Pi or cloud."""
import argparse
import asyncio
import logging
import os
from pathlib import Path
import re
import shutil
import threading

from dotenv import load_dotenv
from file_transfer import Inbox, MAX_IMAGE_BYTES


def make_ftp_server(inbox, host, port, username, password, passive_ports):
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    from pyftpdlib.ioloop import IOLoop
    if not username or not password or password == 'CHANGE_ME':
        raise ValueError('Set a nonempty FTP_USER and FTP_PASSWORD before starting FTP')
    authorizer = DummyAuthorizer()
    authorizer.add_user(username, password, str(inbox.root), perm='elr')
    authorizer.override_perm(username, str(inbox.incoming), perm='elrwf', recursive=False)

    class Handler(FTPHandler):
        timeout = 60
        banner = 'Edge camera FTP ready'

        def ftp_STOR(self, file, mode='w'):
            # Only temporary flat uploads, no overwriting ready data/receipts.
            path = Path(file)
            if (path.parent.resolve() != inbox.incoming or
                    not re.fullmatch(r'[A-Za-z0-9_-]{8,96}\.(data|json)\.part', path.name) or
                    path.exists() or path.is_symlink()):
                self.respond('550 Upload a new .data.part or .json.part in incoming.')
                return
            if shutil.disk_usage(inbox.root).free < inbox.min_free+MAX_IMAGE_BYTES:
                self.respond('452 Insufficient storage.')
                return
            return super().ftp_STOR(file, mode)

        def ftp_RNTO(self, path):
            source = getattr(self, '_rnfr', None)
            target = Path(path)
            valid = False
            if source:
                original = Path(source)
                if original.name.endswith('.data.part'):
                    valid = target.name == original.name[:-5]
                elif original.name.endswith('.json.part'):
                    valid = target.name == original.name[:-10]+'.ready'
                valid = valid and original.parent.resolve() == inbox.incoming
            if not valid or target.parent.resolve() != inbox.incoming or target.exists():
                self._rnfr = None
                self.respond('550 Invalid commit rename.')
                return
            return super().ftp_RNTO(path)

    Handler.authorizer = authorizer
    # None asks the OS for an ephemeral port; an empty list leaves it unbound.
    Handler.passive_ports = list(passive_ports) or None
    server = FTPServer((host, port), Handler, ioloop=IOLoop())
    server.max_cons = 16
    server.max_cons_per_ip = 4
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--transport', choices=['ftp','sftp'], required=True)
    parser.add_argument('--role', choices=['edge','cloud'], required=True)
    args = parser.parse_args()
    load_dotenv(args.env_file)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    token = os.environ.get('API_TOKEN', '')
    root = os.environ.get('TRANSFER_ROOT', '')
    if not token or not root:
        parser.error('Set API_TOKEN and TRANSFER_ROOT in the env file')
    inbox = Inbox(root,args.role,os.getenv('INGEST_API_URL','http://127.0.0.1:8000'),token,
                  min_free=int(os.getenv('MIN_FREE_MB','64'))*1024*1024)
    server = None
    thread = None
    try:
        if args.transport == 'ftp':
            if args.role != 'edge':
                parser.error('FTP listener is intended for the edge LAN')
            first, last = int(os.getenv('FTP_PASSIVE_FIRST','30000')), int(os.getenv('FTP_PASSIVE_LAST','30009'))
            if not 1024 <= first <= last <= 65535:
                parser.error('Invalid passive port range')
            server = make_ftp_server(inbox,os.getenv('FTP_BIND','0.0.0.0'),int(os.getenv('FTP_PORT','2121')),
                                     os.getenv('FTP_USER','camera'),os.getenv('FTP_PASSWORD',''),range(first,last+1))
            thread = threading.Thread(target=server.serve_forever, kwargs={'timeout':.1}, daemon=True)
            thread.start()
        asyncio.run(inbox.run())
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.close_all()
        if thread:
            thread.join(timeout=2)


if __name__ == '__main__':
    main()
