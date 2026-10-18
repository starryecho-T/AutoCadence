import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import DesktopServer, MAX_BODY


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        body = b'\x89PNG\r\n\x00\xff' if self.path.startswith('/api/image') else b'{"status":"active"}'
        self.send_response(200)
        self.send_header('Content-Type', 'image/png' if self.path.startswith('/api/image') else 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.send_response(422)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.assets = Path(self.temp.name) / 'assets'
        self.assets.mkdir()
        (self.assets / 'index.html').write_text('<h1>AutoCadence</h1>', encoding='utf-8')
        (self.assets / 'app.js').write_text('console.log(1)', encoding='utf-8')
        (Path(self.temp.name) / 'private.txt').write_text('private', encoding='utf-8')
        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        threading.Thread(target=self.backend.serve_forever, daemon=True).start()
        self.server = DesktopServer(self.assets, f'http://127.0.0.1:{self.backend.server_port}', 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        for server in (self.server, self.backend):
            server.shutdown()
            server.server_close()
        self.temp.cleanup()

    def request(self, path, method='GET', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        status, content_type, content = response.status, response.getheader('Content-Type'), response.read()
        connection.close()
        return status, content_type, content

    def test_assets_and_mime(self):
        self.assertEqual(self.request('/?desktop=1')[2], b'<h1>AutoCadence</h1>')
        self.assertEqual(self.request('/app.js')[1], 'text/javascript')
        self.assertEqual(self.request('/app.js', 'HEAD')[2], b'')
        self.assertEqual(self.request('/missing.js')[0], 404)

    def test_backend_binary_and_error_status(self):
        self.assertEqual(json.loads(self.request('/health')[2]), {'status': 'active'})
        self.assertEqual(self.request('/api/image?x=1')[2], b'\x89PNG\r\n\x00\xff')
        status, _, body = self.request('/api/v1/runs', 'POST', b'{"detail":"invalid"}', {'Origin': self.server.origin})
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body), {'detail': 'invalid'})

    def test_boundaries(self):
        for path in ('/../private.txt', '/%2e%2e/private.txt', '/..%5cprivate.txt'):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request('/health', headers={'Host': 'example.com'})[0], 403)
        self.assertEqual(self.request('/api/v1/runs', 'POST', '{}', {'Origin': 'https://example.com'})[0], 403)
        self.assertEqual(self.request('/api/v1/parse', 'POST', None, {'Content-Length': str(MAX_BODY + 1)})[0], 413)
        self.assertEqual(self.request('/index.html', 'POST')[0], 405)

    def test_unavailable_backend(self):
        with socket.socket() as unused:
            unused.bind(('127.0.0.1', 0))
            port = unused.getsockname()[1]
        from urllib.parse import urlsplit
        self.server.backend = urlsplit(f'http://127.0.0.1:{port}')
        status, _, content = self.request('/health')
        self.assertEqual(status, 502)
        self.assertIn('尚未连接', json.loads(content)['detail'])

    def test_desktop_info_and_config(self):
        self.assertEqual(json.loads(self.request('/desktop-info')[2])['name'], 'autocadence-desktop')
        for address in ('file:///tmp', 'http://user:secret@localhost', 'http://localhost?q=1'):
            with self.assertRaises(ValueError):
                DesktopServer(self.assets, address, 0)


if __name__ == '__main__':
    unittest.main()
