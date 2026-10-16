"""Authenticated desktop child process, binding a socket before its handshake."""
import argparse
import json
import os
from pathlib import Path
import socket

import uvicorn
from app.config import AppSettings
from .application import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', choices=['127.0.0.1'], default='127.0.0.1')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--provider-mode', choices=['fake', 'real'], default='real')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('invalid port')
    settings = AppSettings(args.data_root, os.environ.get('WORKBENCH_API_TOKEN', ''), args.provider_mode, True)
    if args.provider_mode == 'fake':
        from app.runtime.demo_backend import build_demo_backend
        app = create_app(settings, backend_factory=build_demo_backend)
    else:
        app = create_app(settings)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Do not reuse a socket belonging to an unrelated service on Windows.
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        sock.bind((args.host, args.port))
        sock.listen(128)
        actual_port = sock.getsockname()[1]
        print(json.dumps(dict(kind='backend.ready', port=actual_port, pid=os.getpid(),
                              instance_id=app.state.instance_id, protocol_version='1.0')), flush=True)
        uvicorn.Server(uvicorn.Config(app, host=args.host, port=actual_port, access_log=False,
                                    log_level='error')).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == '__main__':
    main()
