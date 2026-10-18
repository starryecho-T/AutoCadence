"""Isolated browser-test server. New jobs deliberately fail; never runs Cadence.

An existing M4 run, if present, is copied with its original ID to test historical
evidence rendering. It is never relabeled as the result of a new submission.
"""
import json
from pathlib import Path
import shutil
import socket
import sys
from tempfile import TemporaryDirectory
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

import uvicorn
from fastapi.staticfiles import StaticFiles
from vai_backend.api import create_app
from vai_backend.config import Settings
from vai_backend.manager import RunManager
from vai_backend.pipeline import PipelineError

HISTORICAL_ID = 'vai_20261018_073200_c20608d57c75'


def fixture_executor(task, root, emit):
    emit({'name': 'preflight', 'status': 'running'})
    raise PipelineError('ENVIRONMENT_MISSING', 'preflight',
                        'Browser test fixture: deliberate failure; no remote simulation was attempted.')


with TemporaryDirectory(prefix='circuit-browser-test-') as temporary:
    data_dir = Path(temporary)
    historical = ROOT / 'backend' / 'runs' / HISTORICAL_ID
    if historical.is_dir():
        shutil.copytree(historical, data_dir / HISTORICAL_ID)
    manager = RunManager(data_dir, fixture_executor)
    app = create_app(Settings(data_dir=data_dir), manager)
    app.mount('/', StaticFiles(directory=ROOT / 'frontend/dist', html=True), name='ui')
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))

    def stop_when_parent_closes():
        sys.stdin.readline()
        server.should_exit = True

    threading.Thread(target=stop_when_parent_closes, daemon=True).start()
    print(json.dumps({'url': f'http://127.0.0.1:{listener.getsockname()[1]}',
                      'historical_id': HISTORICAL_ID if historical.is_dir() else None}), flush=True)
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
