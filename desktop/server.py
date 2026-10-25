"""Serve bundled assets and forward the existing API contract to the backend."""
from __future__ import annotations

import http.client
import json
import mimetypes
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_BODY = 12 * 1024 * 1024


class DesktopServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, assets: Path, backend_url: str, port: int = 18765):
        self.assets = assets.resolve()
        self.backend = urlsplit(backend_url)
        if self.backend.scheme not in ('http', 'https') or not self.backend.hostname:
            raise ValueError('backend_url 必须是 HTTP 或 HTTPS 地址')
        if self.backend.username or self.backend.password or self.backend.query or self.backend.fragment:
            raise ValueError('backend_url 不支持内嵌账号、查询参数或片段')
        super().__init__(('127.0.0.1', port), DesktopHandler)
        self.origin = f'http://127.0.0.1:{self.server_port}'

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class DesktopHandler(BaseHTTPRequestHandler):
    server: DesktopServer

    def log_message(self, *_args):
        pass  # Do not log task contents or API credentials.

    def _send(self, status, body, content_type='application/json; charset=utf-8', extra_headers=None):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != 'HEAD':
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _handle(self):
        expected_host = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != expected_host:
            self._send(403, {'detail': 'Invalid host'})
            return
        origin = self.headers.get('Origin')
        if origin and origin != self.server.origin:
            self._send(403, {'detail': 'Cross-origin requests are not allowed'})
            return
        path = urlsplit(self.path).path
        if path == '/desktop-info' and self.command == 'GET':
            self._send(200, {'name': 'autocadence-desktop', 'version': '0.7.2'})
        elif path in ('/health', '/openapi.json') or path.startswith('/api/'):
            self._proxy()
        elif self.command not in ('GET', 'HEAD'):
            self._send(405, {'detail': 'Method not allowed'})
        else:
            self._asset(path)

    def _asset(self, path):
        try:
            relative = unquote(path).lstrip('/') or 'index.html'
            file = (self.server.assets / relative).resolve()
            file.relative_to(self.server.assets)
            if not file.is_file():
                raise FileNotFoundError
            mime = {'.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html'}.get(file.suffix)
            self._send(200, file.read_bytes(), mime or mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
        except (ValueError, OSError):
            self._send(404, {'detail': 'File not found'})

    def _proxy(self):
        if self.headers.get('Transfer-Encoding'):
            self._send(400, {'detail': 'Unsupported transfer encoding'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0:
                raise ValueError
        except ValueError:
            self._send(400, {'detail': 'Invalid content length'})
            return
        if length > MAX_BODY:
            self._send(413, {'detail': '上传内容超过 12 MB'})
            return
        self.connection.settimeout(20)
        target = self.server.backend
        connection_type = http.client.HTTPSConnection if target.scheme == 'https' else http.client.HTTPConnection
        connection = connection_type(target.hostname, target.port, timeout=90 if self.path == '/api/v2/connection' else 20)
        try:
            body = self.rfile.read(length) if length else None
            headers = {'Content-Type': self.headers.get('Content-Type', 'application/json')}
            connection.request(self.command, target.path.rstrip('/') + self.path, body=body, headers=headers)
            response = connection.getresponse()
            content = response.read()
            forwarded = {name: value for name, value in response.getheaders() if name.lower() in ('content-disposition', 'content-encoding')}
            self._send(response.status, content, response.getheader('Content-Type', 'application/octet-stream'), forwarded)
        except (OSError, http.client.HTTPException):
            self._send(502, {'detail': '尚未连接仿真后端，请启动后端后重新连接'})
        finally:
            connection.close()

    do_GET = _handle
    do_HEAD = _handle
    do_POST = _handle
    do_PUT = _handle
    do_DELETE = _handle
    do_OPTIONS = _handle
