"""SSH password/key transport. Credentials never enter command lines or evidence."""
from __future__ import annotations

import base64
import hashlib
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import paramiko


class ConnectionFailure(Exception):
    def __init__(self, code, message, details=None):
        self.code, self.message, self.details = code, message, details
        super().__init__(message)


def fingerprint(key):
    return 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')


class ConfirmHostKey(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected=None):
        self.expected = expected

    def missing_host_key(self, client, hostname, key):
        actual = fingerprint(key)
        if self.expected != actual:
            raise ConnectionFailure('SSH_HOST_UNTRUSTED', '首次连接此服务器，请核对主机指纹后继续。',
                                    {'fingerprint': actual, 'host': hostname, 'key_type': key.get_name()})
        client.get_host_keys().add(hostname, key.get_name(), key)


def connect(config, expected_fingerprint=None):
    client = paramiko.SSHClient()
    for name in (str(Path.home() / '.ssh/known_hosts'), config.get('ssh_known_hosts_file')):
        if name and Path(name).is_file():
            client.load_system_host_keys(name)
    client.set_missing_host_key_policy(ConfirmHostKey(expected_fingerprint))
    password = config.get('ssh_password') or None
    key_auth = config.get('ssh_auth_method') == 'key'
    try:
        client.connect(config['ssh_host'], port=config.get('ssh_port', 22), username=config['ssh_username'],
                       password=None if key_auth else password,
                       key_filename=config.get('ssh_identity_file') if key_auth else None,
                       passphrase=password if key_auth else None,
                       allow_agent=False, look_for_keys=False, timeout=10, banner_timeout=10,
                       auth_timeout=12, channel_timeout=10,
                       disabled_algorithms={'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']} if config.get('ssh_legacy_rsa') else None)
        client.get_transport().set_keepalive(20)
        return client
    except ConnectionFailure:
        client.close(); raise
    except paramiko.BadHostKeyException as exc:
        client.close()
        raise ConnectionFailure('SSH_HOST_CHANGED', '服务器主机密钥已变化，已停止连接。请先向管理员核对，再更新本机 known_hosts。') from exc
    except (paramiko.AuthenticationException, paramiko.PasswordRequiredException) as exc:
        client.close()
        raise ConnectionFailure('SSH_AUTH_FAILED', 'SSH 认证失败，请检查账号、密码或私钥口令。') from exc
    except (OSError, paramiko.SSHException) as exc:
        client.close()
        raise ConnectionFailure('SSH_CONNECT_FAILED', '无法建立 SSH 连接，请检查服务器地址、端口、网络及认证方式。') from exc


def command(client, text, *, input_data=None, timeout=30, max_output=40 * 1024 * 1024, on_chunk=None, merge_stderr=False):
    """Drain both streams while writing stdin, with a wall-clock/output bound."""
    channel = client.get_transport().open_session(timeout=10)
    channel.set_combine_stderr(merge_stderr)
    channel.settimeout(1)
    channel.exec_command(text)
    writing_error = []

    def send():
        try:
            if input_data:
                channel.sendall(input_data)
            channel.shutdown_write()
        except Exception as exc:
            writing_error.append(exc)

    writer = threading.Thread(target=send, daemon=True); writer.start()
    output, errors = bytearray(), bytearray()
    started = time.monotonic()
    try:
        while True:
            if time.monotonic() - started > timeout:
                raise ConnectionFailure('SSH_TIMEOUT', 'SSH 命令等待超时。')
            progress = False
            if channel.recv_ready():
                chunk = channel.recv(65536); output.extend(chunk); progress = True
                if on_chunk: on_chunk(chunk)
            if channel.recv_stderr_ready():
                errors.extend(channel.recv_stderr(65536)); progress = True
            if len(output) + len(errors) > max_output:
                raise ConnectionFailure('SSH_OUTPUT_LIMIT', 'SSH 返回数据超过本次读取上限。')
            if (channel.exit_status_ready() and (channel.eof_received or channel.closed)
                    and not channel.recv_ready() and not channel.recv_stderr_ready()):
                break
            if not progress: time.sleep(.02)
        writer.join(timeout=1)
        status = channel.recv_exit_status()
        if writing_error and status == 0:
            raise ConnectionFailure('SSH_UPLOAD_FAILED', 'SSH 输入传输未完成。')
        return SimpleNamespace(returncode=status, stdout=bytes(output), stderr=bytes(errors))
    finally:
        channel.close()


def run(config, text, **kwargs):
    client = connect(config)
    try:
        return command(client, text, **kwargs)
    except (paramiko.SSHException, OSError, EOFError) as exc:
        raise ConnectionFailure('SSH_TRANSFER_FAILED', 'SSH 连接中断，命令或数据传输未完成。') from exc
    finally:
        client.close()
