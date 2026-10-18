"""Per-computer connection profile; Windows passwords use current-user DPAPI."""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import shlex
import threading
from functools import lru_cache
from pathlib import Path
from typing import Literal

import paramiko
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .ssh_transport import ConnectionFailure, command, connect, fingerprint

REMOTE_FIELDS = ('remote_base', 'environment_script', 'virtuoso_bin', 'spectre_bin', 'cadence_cds_lib')
DEFAULT_SSH_HOST = '101.6.64.74'
DEFAULT_SSH_PORT = 35167


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=DEFAULT_SSH_PORT, ge=1, le=65535, strict=True)
    username: str = Field(min_length=1, max_length=64)
    auth_method: Literal['password', 'key'] = 'password'
    password: SecretStr | None = Field(default=None, max_length=4096)
    use_saved_password: bool = False
    remember_password: bool = False
    identity_file: str = Field(default='', max_length=1024)
    legacy_rsa: bool = False
    remote_base: str = Field(default='', max_length=512)
    environment_script: str = Field(default='/etc/profile', max_length=512)
    virtuoso_bin: str = Field(default='', max_length=512)
    spectre_bin: str = Field(default='', max_length=512)
    cadence_cds_lib: str = Field(default='', max_length=512)
    trusted_fingerprint: str | None = Field(default=None, max_length=100)

    @field_validator('host', 'username')
    @classmethod
    def safe_endpoint(cls, value):
        value = value.strip()
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:-]*', value):
            raise ValueError('服务器和账号只能包含字母、数字、点、下划线、冒号和连字符')
        return value

    @field_validator(*REMOTE_FIELDS)
    @classmethod
    def safe_remote_path(cls, value):
        value = value.strip()
        if value and (not re.fullmatch(r'/[A-Za-z0-9_./-]+', value) or '..' in value.split('/')):
            raise ValueError('请使用无空格的 Linux 绝对路径，或留空自动探测')
        return value


def protect_secret(value: str, decrypt=False) -> str:
    if os.name != 'nt':
        raise ConnectionFailure('PASSWORD_STORAGE_UNAVAILABLE', '此平台仅支持本次会话密码，请取消“记住密码”。')
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_uint32), ('data', ctypes.POINTER(ctypes.c_char))]
    raw = base64.b64decode(value, validate=True) if decrypt else value.encode('utf-8')
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))); target = Blob()
    crypt = ctypes.windll.crypt32
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(Blob)]
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ConnectionFailure('PASSWORD_STORAGE_FAILED', '无法读取或保存本机密码，请重新输入，或取消记住密码。')
    try:
        result = ctypes.string_at(target.data, target.size)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(target.data)


def legacy_path():
    return Path(os.getenv('VAI_CONFIG', str(Path(__file__).resolve().parents[1] / 'config.local.json')))


def connection_path():
    default = Path(os.getenv('LOCALAPPDATA', str(Path.home() / '.config'))) / 'AutoCadence' / 'connection.json'
    return Path(os.getenv('VAI_CONNECTION_FILE', str(default))).resolve()


class ConnectionStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.session_secret = None
        self.session_identity = None

    def read(self):
        if self.path.is_file():
            return json.loads(self.path.read_text(encoding='utf-8'))
        if legacy_path().is_file():
            return json.loads(legacy_path().read_text(encoding='utf-8'))
        return {}

    @staticmethod
    def identity(config):
        return tuple(config.get(k) for k in ('ssh_host', 'ssh_port', 'ssh_username', 'ssh_auth_method', 'ssh_identity_file'))

    def secret(self, config):
        if self.identity(config) == self.session_identity and self.session_secret:
            return self.session_secret
        if config.get('ssh_password_encrypted'):
            return protect_secret(config['ssh_password_encrypted'], decrypt=True)
        return None

    def public(self):
        with self.lock:
            config = self.read()
            host = config.get('ssh_host', DEFAULT_SSH_HOST)
            username = config.get('ssh_username', '')
            if '@' in host: username, host = host.rsplit('@', 1)
            has_secret = bool(config.get('ssh_password_encrypted') or
                              (self.session_secret and self.identity(config) == self.session_identity))
            auth = config.get('ssh_auth_method', 'key' if config.get('ssh_identity_file') else 'password')
            legacy = bool(config) and config.get('ssh_transport') != 'paramiko'
            ready = bool(config) and (legacy or (all(config.get(k) for k in REMOTE_FIELDS) and (auth != 'password' or has_secret)))
            return {'configured': ready, 'imported': legacy, 'host': host, 'port': config.get('ssh_port', 22) if config else DEFAULT_SSH_PORT,
                    'username': username, 'auth_method': auth, 'identity_file': config.get('ssh_identity_file', ''),
                    'legacy_rsa': config.get('ssh_legacy_rsa', False), 'has_password': has_secret,
                    'remember_password': bool(config.get('ssh_password_encrypted')),
                    **{k: config.get(k, '/etc/profile' if k == 'environment_script' else '') for k in REMOTE_FIELDS}}

    def runtime(self):
        with self.lock:
            config = self.read()
            if not config:
                raise ConnectionFailure('SSH_NOT_CONFIGURED', '请先在“仿真服务器”中填写自己的 SSH 连接信息。')
            if config.get('ssh_transport') == 'paramiko':
                config['ssh_password'] = self.secret(config)
                if config['ssh_auth_method'] == 'password' and not config['ssh_password']:
                    raise ConnectionFailure('SSH_PASSWORD_REQUIRED', '本次会话尚未登录，请在“仿真服务器”中重新输入密码。')
                if not all(config.get(k) for k in REMOTE_FIELDS):
                    raise ConnectionFailure('EDA_NOT_CONFIGURED', 'SSH 信息已保存，请在“仿真服务器”中补全 Cadence 环境路径。')
            return config

    def prepare(self, body):
        config = {'ssh_transport': 'paramiko', 'ssh_host': body.host, 'ssh_port': body.port,
                  'ssh_username': body.username, 'ssh_auth_method': body.auth_method,
                  'ssh_identity_file': body.identity_file if body.auth_method == 'key' else '',
                  'ssh_legacy_rsa': body.legacy_rsa, 'ssh_known_hosts_file': str(self.path.with_name('known_hosts')),
                  **{k: getattr(body, k) for k in REMOTE_FIELDS},
                  'protected_files': [], 'stage_timeout_s': 120, 'run_timeout_s': 600}
        if body.auth_method == 'key' and not Path(body.identity_file).is_file():
            raise ConnectionFailure('SSH_KEY_MISSING', '请选择本机存在的私钥文件。')
        with self.lock:
            old = self.read()
            if old.get('ssh_known_hosts_file') and not self.path.with_name('known_hosts').is_file():
                config['ssh_known_hosts_file'] = old['ssh_known_hosts_file']
            secret = body.password.get_secret_value() if body.password else None
            if body.use_saved_password and not secret:
                if self.identity(config) != self.identity(old):
                    raise ConnectionFailure('SSH_PASSWORD_REQUIRED', '服务器、账号或认证方式已改变，请重新输入密码。')
                secret = self.secret(old)
            if body.auth_method == 'password' and not secret:
                raise ConnectionFailure('SSH_PASSWORD_REQUIRED', '请输入 SSH 密码。')
            config['ssh_password'] = secret
        return config

    def save(self, config, key, remember):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.session_secret = config.get('ssh_password')
            self.session_identity = self.identity(config)
            clean = {k: v for k, v in config.items() if k != 'ssh_password'}
            clean['ssh_known_hosts_file'] = str(self.path.with_name('known_hosts'))
            if remember and self.session_secret:
                clean['ssh_password_encrypted'] = protect_secret(self.session_secret)
            hosts = paramiko.HostKeys()
            if Path(clean['ssh_known_hosts_file']).is_file(): hosts.load(clean['ssh_known_hosts_file'])
            hostname = config['ssh_host'] if config['ssh_port'] == 22 else '[%s]:%s' % (config['ssh_host'], config['ssh_port'])
            hosts.add(hostname, key.get_name(), key)
            hosts.save(clean['ssh_known_hosts_file'])
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(clean, indent=2), encoding='utf-8')
            os.chmod(temp, 0o600); os.replace(temp, self.path)
            return self.public()

    def forget_password(self):
        with self.lock:
            config = self.read()
            config.pop('ssh_password_encrypted', None)
            self.session_secret = self.session_identity = None
            if self.path.is_file():
                temp = self.path.with_suffix('.tmp'); temp.write_text(json.dumps(config, indent=2), encoding='utf-8')
                os.chmod(temp, 0o600); os.replace(temp, self.path)
            return self.public()


@lru_cache(maxsize=8)
def _store(path): return ConnectionStore(path)


def get_connection_store(): return _store(str(connection_path()))


def probe_environment(client, config):
    """Read-only detection; never starts Cadence or consumes a simulation license."""
    source = config['environment_script'] or '/etc/profile'
    shell = 'source ' + shlex.quote(source) + ' >/dev/null 2>&1 || exit 12; '
    shell += 'printf "AUTOCADENCE_HOME=%s\\n" "$HOME"; '
    shell += 'printf "AUTOCADENCE_VIRTUOSO=%s\\n" "$(command -v virtuoso)"; '
    shell += 'printf "AUTOCADENCE_SPECTRE=%s\\n" "$(command -v spectre)"'
    result = command(client, 'bash -lc ' + shlex.quote(shell), timeout=15, max_output=32768)
    if result.returncode:
        raise ConnectionFailure('SSH_ENVIRONMENT_FAILED', 'SSH 已登录，但无法加载环境脚本，请检查高级设置中的路径。')
    found = dict(re.findall(r'^AUTOCADENCE_(\w+)=(.*)$', result.stdout.decode(errors='replace'), re.M))
    config['environment_script'] = source
    if not config['remote_base']:
        if not found.get('HOME', '').startswith('/'):
            raise ConnectionFailure('SSH_HOME_MISSING', '无法获取服务器主目录，请手动填写远程运行目录。')
        config['remote_base'] = found['HOME'].rstrip('/') + '/.autocadence/runs'
    for field, label in (('virtuoso_bin', 'VIRTUOSO'), ('spectre_bin', 'SPECTRE')):
        if not config[field]: config[field] = found.get(label, '')
    if not config['cadence_cds_lib'] and config['virtuoso_bin']:
        parent = Path(config['virtuoso_bin']).as_posix().rsplit('/bin/', 1)[0]
        candidates = [parent + '/share/cdssetup/cds.lib', parent + '/../../share/cdssetup/cds.lib']
        query = 'for p in ' + ' '.join(shlex.quote(p) for p in candidates) + '; do if test -f "$p"; then readlink -f "$p"; break; fi; done'
        response = command(client, 'bash -lc ' + shlex.quote(query), timeout=10, max_output=4096)
        config['cadence_cds_lib'] = response.stdout.decode(errors='replace').strip()
    # Revalidate discovered paths before any later command uses them.
    for field in REMOTE_FIELDS:
        if config[field]: ConnectionInput.safe_remote_path(config[field])
    if config['remote_base'] in ('/', '/tmp', '/home', '/data/home'):
        raise ConnectionFailure('SSH_DIRECTORY_INVALID', '运行目录必须是自己的专用子目录。')
    missing = [k for k in ('virtuoso_bin', 'spectre_bin', 'cadence_cds_lib') if not config[k]]
    checks = ['test -' + ('r' if k == 'cadence_cds_lib' else 'x') + ' ' + shlex.quote(config[k]) + ' || printf "MISSING=' + k + '\\n"' for k in ('virtuoso_bin', 'spectre_bin', 'cadence_cds_lib') if config[k]]
    result = command(client, 'bash -lc ' + shlex.quote('; '.join(checks) or ':'), timeout=10, max_output=4096)
    missing.extend(re.findall(r'^MISSING=(\w+)$', result.stdout.decode(errors='replace'), re.M))
    return sorted(set(missing))


def connect_and_save(store, body, ensure_idle):
    config = store.prepare(body)
    client = connect(config, body.trusted_fingerprint)
    try:
        missing = probe_environment(client, config)
        for field in missing: config[field] = ''
        ensure_idle()
        key = client.get_transport().get_remote_server_key()
        profile = store.save(config, key, body.remember_password)
        return {'connection': profile, 'ssh_connected': True, 'ready': not missing,
                'fingerprint': fingerprint(key), 'missing_fields': missing,
                'message': '连接已保存，可以开始仿真。' if not missing else 'SSH 已连接并保存，请补全高级设置中的 Cadence 环境路径。'}
    except (paramiko.SSHException, OSError, EOFError) as exc:
        raise ConnectionFailure('SSH_ENVIRONMENT_FAILED', 'SSH 登录后检查或保存环境失败，请检查网络和本机目录权限。') from exc
    finally:
        client.close()
