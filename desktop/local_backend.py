"""Start the bundled per-user backend when no external local backend is running."""
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


def start_local_backend(backend_url, directory):
    target = urlsplit(backend_url)
    if target.hostname not in ('127.0.0.1', 'localhost') or target.scheme != 'http':
        return None
    try:
        with urlopen(backend_url.rstrip('/') + '/health', timeout=1) as response:
            info = json.load(response)
        if info.get('name') == 'AutoCadence' and info.get('build') == '0.7.0':
            return None
        raise RuntimeError('当前后端版本较旧，请关闭空闲的旧后端后重新打开 AutoCadence。')
    except URLError:
        pass
    if not getattr(sys, 'frozen', False):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
    os.environ.setdefault('VAI_CONNECTION_FILE', str(directory / 'connection.json'))
    from vai_backend.api import create_app
    from vai_backend.config import Settings
    import uvicorn
    settings = Settings(data_dir=directory / 'runs', host='127.0.0.1', port=target.port or 8766)
    listener = socket.socket()
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    listener.bind(('127.0.0.1', settings.port))
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host='127.0.0.1', port=settings.port,
                                          log_config=None, access_log=False, loop='asyncio', http='h11'))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(.05)
    if not server.started:
        server.should_exit = True; listener.close()
        raise RuntimeError('内置仿真服务启动失败，请查看 desktop.log。')
    return server
