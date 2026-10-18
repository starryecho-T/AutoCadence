"""Windows desktop entry point with a bundled local simulation backend."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
from pathlib import Path
import sys
import threading
import time

from server import DesktopServer
from local_backend import start_local_backend

TITLE = 'AutoCadence'


def data_directory():
    override = os.environ.get('AUTOCADENCE_DATA_DIR') or os.environ.get('AUTOCAD_DATA_DIR') or os.environ.get('CIRCUIT_SIM_DATA_DIR')
    if override:
        return Path(override)
    directory = Path(os.environ['LOCALAPPDATA']) / 'AutoCadence'
    for previous_name in ('AutoCAD', 'CircuitSim'):
        legacy = Path(os.environ['LOCALAPPDATA']) / previous_name
        if not directory.exists() and legacy.exists():
            shutil.copytree(legacy, directory)
            break
    return directory


def acquire_instance(directory):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    suffix = hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:16]
    handle = kernel.CreateMutexW(None, False, 'Local\\AutoCadence-' + suffix)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = ctypes.c_void_p
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        window = user32.FindWindowW(None, TITLE)
        if window:
            user32.ShowWindow(window, 9)
            user32.SetForegroundWindow(window)
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(handle)
        return None
    return handle


def smoke_test(window, output):
    """Exercise the packaged WebView without opening a visible test window."""
    def wait_for(script, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if window.evaluate_js(script):
                return
            time.sleep(0.15)
        raise AssertionError('Desktop smoke test timed out: ' + script)

    def click(text):
        window.evaluate_js(f"[...document.querySelectorAll('button')].find(b => b.textContent.trim() === {json.dumps(text)} || b.getAttribute('aria-label') === {json.dumps(text)}).click()")
        time.sleep(0.1)

    try:
        wait_for("!!document.querySelector('.general-input')")
        assert window.evaluate_js("![...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'RC 低通题目')")
        click('电路截图')
        wait_for("!!document.querySelector('[aria-label=通用电路截图]')")
        click('连接描述')
        wait_for("!!document.querySelector('#connection-description')")
        click('文字描述')
        wait_for("!!document.querySelector('#general-question')")
        previous = window.evaluate_js("localStorage.getItem('desktop-smoke-marker')")
        window.evaluate_js("localStorage.setItem('desktop-smoke-marker', 'saved')")
        result = {'ok': True, 'title': TITLE, 'unified_input': True, 'previous_storage': previous}
    except Exception as error:
        logging.exception('Desktop smoke test failed')
        result = {'ok': False, 'error': str(error)}
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    window.destroy()


def main():
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument('--smoke-test', metavar='OUTPUT_JSON', help=argparse.SUPPRESS)
    args = parser.parse_args()
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(directory / 'desktop.log', maxBytes=1_000_000, backupCount=1, encoding='utf-8')])
    mutex = None
    server = None
    local_backend = None
    try:
        mutex = acquire_instance(directory)
        if mutex is None:
            return
        config_path = directory / 'config.json'
        config = {'backend_url': 'http://127.0.0.1:8766', 'desktop_port': 18765}
        if config_path.exists():
            config.update(json.loads(config_path.read_text(encoding='utf-8')))
        else:
            config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
        backend_url = os.environ.get('AUTOCADENCE_BACKEND_URL') or os.environ.get('AUTOCAD_BACKEND_URL') or os.environ.get('CIRCUIT_SIM_BACKEND_URL', config['backend_url'])
        local_backend = start_local_backend(backend_url, directory)
        assets = Path(sys._MEIPASS) / 'frontend' if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
        if not (assets / 'index.html').is_file():
            raise RuntimeError('未找到界面文件，请先运行桌面构建脚本。')
        server = DesktopServer(assets, backend_url, int(config['desktop_port']))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        import webview
        webview.settings['ALLOW_DOWNLOADS'] = True
        webview.settings['ALLOW_FILE_URLS'] = False
        window = webview.create_window(TITLE, server.origin + '/?desktop=1', width=1120, height=820, min_size=(760, 560), background_color='#f5f7fa', text_select=True, hidden=bool(args.smoke_test))
        callback = (lambda: smoke_test(window, args.smoke_test)) if args.smoke_test else None
        webview.start(callback, gui='edgechromium', private_mode=False, storage_path=str(directory / 'WebView2'))
    except Exception as error:
        logging.exception('Desktop startup failed')
        if args.smoke_test:
            Path(args.smoke_test).write_text(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), encoding='utf-8')
        else:
            ctypes.windll.user32.MessageBoxW(None, f'启动失败：{error}\n\n请确认已安装 Microsoft Edge WebView2 Runtime。\n详细日志：{directory / "desktop.log"}', TITLE, 0x10)
        return 1
    finally:
        if local_backend:
            local_backend.should_exit = True
        if server:
            server.shutdown()
            server.server_close()
        if mutex:
            ctypes.windll.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            ctypes.windll.kernel32.CloseHandle(mutex)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
