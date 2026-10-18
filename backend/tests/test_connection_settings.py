import io
import json
import os
import socket
import tarfile
import threading
import time
from pathlib import Path

import paramiko
import pytest
from fastapi.testclient import TestClient

from vai_backend.connection_settings import ConnectionInput, ConnectionStore, connect_and_save
from vai_backend.ssh_transport import ConnectionFailure, command, connect, fingerprint
from vai_backend.pipeline import _archive
from vai_backend.api import create_app
from vai_backend.config import Settings
from vai_backend.manager import RunManager


@pytest.fixture
def ssh_server():
    host_key = paramiko.RSAKey.generate(2048)
    listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(10); listener.settimeout(.2)
    stopping = threading.Event(); clients = []; auth_attempts = []; accepted = []

    class Server(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            auth_attempts.append((username, password))
            return paramiko.AUTH_SUCCESSFUL if (username, password) == ('student', 'fixture-secret') else paramiko.AUTH_FAILED

        def get_allowed_auths(self, username): return 'password'
        def check_channel_request(self, kind, chanid): return paramiko.OPEN_SUCCEEDED
        def check_channel_exec_request(self, channel, text):
            def reply():
                time.sleep(.05)  # Return the exec-request acknowledgement before closing a fast reply.
                if text == b'echo-binary':
                    data = b''
                    while True:
                        chunk = channel.recv(65536)
                        if not chunk: break
                        data += chunk
                    channel.sendall(data)
                elif b'AUTOCADENCE_HOME' in text:
                    channel.sendall(b'AUTOCADENCE_HOME=/home/student\nAUTOCADENCE_VIRTUOSO=/opt/ic/bin/virtuoso\nAUTOCADENCE_SPECTRE=/opt/mmsim/bin/spectre\n')
                elif b'readlink' in text:
                    channel.sendall(b'/opt/ic/share/cdssetup/cds.lib\n')
                channel.send_exit_status(0); channel.close()
            threading.Thread(target=reply, daemon=True).start()
            return True

    def accept():
        while not stopping.is_set():
            try: sock, _ = listener.accept()
            except socket.timeout: continue
            except OSError: break
            transport = paramiko.Transport(sock); clients.append(transport)
            try: transport.add_server_key(host_key); transport.start_server(server=Server())
            except (paramiko.SSHException, OSError, EOFError): continue
            def channels(t):
                while t.is_active() and not stopping.is_set():
                    channel=t.accept(.2)
                    if channel: accepted.append(channel)
            threading.Thread(target=channels, args=(transport,), daemon=True).start()
    thread = threading.Thread(target=accept, daemon=True); thread.start()
    yield listener.getsockname()[1], host_key, auth_attempts
    stopping.set(); listener.close()
    for client in clients: client.close()
    thread.join(timeout=2)


def test_password_login_host_verification_and_binary_transport(ssh_server, tmp_path):
    port, key, attempts = ssh_server
    config = {'ssh_host': '127.0.0.1', 'ssh_port': port, 'ssh_username': 'student', 'ssh_auth_method': 'password', 'ssh_password': 'fixture-secret'}
    with pytest.raises(ConnectionFailure) as rejected: connect(config)
    assert rejected.value.code == 'SSH_HOST_UNTRUSTED'
    assert attempts == []  # Password is never sent before server identity is accepted.
    client = connect(config, fingerprint(key))
    try:
        payload = b'\x00\xff\x10\r\n' * 10000
        result = command(client, 'echo-binary', input_data=payload)
        assert result.returncode == 0 and result.stdout == payload
    finally: client.close()
    with pytest.raises(ConnectionFailure) as bad: connect({**config, 'ssh_password': 'wrong'}, fingerprint(key))
    assert bad.value.code == 'SSH_AUTH_FAILED'
    assert 'wrong' not in str(bad.value)


def test_save_session_password_private_public_view_and_clear(ssh_server, tmp_path, monkeypatch):
    monkeypatch.setenv('VAI_CONFIG', str(tmp_path/'absent.json'))
    port, key, _ = ssh_server
    store = ConnectionStore(tmp_path/'connection.json')
    body = ConnectionInput(host='127.0.0.1', port=port, username='student', password='fixture-secret', trusted_fingerprint=fingerprint(key))
    result = connect_and_save(store, body, lambda: None)
    assert result['ready'] and result['connection']['configured']
    assert result['connection']['remote_base'] == '/home/student/.autocadence/runs'
    assert 'fixture-secret' not in store.path.read_text()
    assert 'fixture-secret' not in json.dumps(result)
    assert store.runtime()['ssh_password'] == 'fixture-secret'
    assert not ConnectionStore(store.path).public()['configured']
    assert store.public()['has_password']
    with pytest.raises(ConnectionFailure):
        store.prepare(body.model_copy(update={'username': 'other', 'password': None, 'use_saved_password': True}))
    blob = _archive({}, 'vai_credentials_test', store.runtime())
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as archive:
        remote = archive.extractfile('input.json').read()
    assert b'fixture-secret' not in remote and b'ssh_' not in remote
    store.forget_password()
    assert not store.public()['has_password']


@pytest.mark.skipif(os.name != 'nt', reason='Windows current-user encryption')
def test_remember_password_is_encrypted_and_readable_by_same_user(ssh_server, tmp_path, monkeypatch):
    monkeypatch.setenv('VAI_CONFIG', str(tmp_path/'absent.json'))
    port, key, _ = ssh_server
    store = ConnectionStore(tmp_path/'connection.json')
    body = ConnectionInput(host='127.0.0.1', port=port, username='student', password='fixture-secret', remember_password=True, trusted_fingerprint=fingerprint(key))
    connect_and_save(store, body, lambda: None)
    assert 'fixture-secret' not in store.path.read_text()
    restored = ConnectionStore(store.path)
    assert restored.runtime()['ssh_password'] == 'fixture-secret'
    assert restored.public()['configured']
    restored.forget_password()
    assert 'ssh_password_encrypted' not in store.path.read_text()


def test_api_settings_are_local_and_errors_do_not_echo_password(tmp_path, monkeypatch):
    monkeypatch.setenv('VAI_CONFIG', str(tmp_path/'absent.json'))
    monkeypatch.setenv('VAI_CONNECTION_FILE', str(tmp_path/'connection.json'))
    app = create_app(Settings(data_dir=tmp_path/'runs'), RunManager(tmp_path/'runs'))
    with TestClient(app) as client:
        assert client.get('/api/v2/connection').json()['configured'] is False
        bad = client.post('/api/v2/connection', json={'host': '-invalid', 'username': 'student', 'password': 'fixture-secret'})
        assert bad.status_code == 422 and 'fixture-secret' not in bad.text
        denied = client.post('/api/v2/connection/forget-password', headers={'Origin': 'https://other-site.test'})
        assert denied.status_code == 403
    with TestClient(app, client=('192.0.2.10', 1000)) as remote:
        assert remote.get('/api/v2/connection').status_code == 403
