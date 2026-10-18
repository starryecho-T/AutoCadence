"""Isolated browser fixture, or explicit --live EDA with persistent evidence."""
import argparse
from contextlib import nullcontext
import json
import mimetypes
from pathlib import Path
import shutil
import socket
import sys
import threading
import uuid
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
import uvicorn
from fastapi.staticfiles import StaticFiles
from vai_backend.api import create_app
from vai_backend.config import Settings
from vai_backend.manager import RunManager, atomic_json, utc_now
from vai_backend.models import RunResult
from vai_backend.circuit_models import CircuitTask
from vai_backend.pipeline import PipelineError
from vai_backend.circuit_examples import EXAMPLES


def fixture(task, root, emit):
    raise PipelineError('TEST_FIXTURE','preflight','Deliberate browser fixture failure. No new EDA run.')


parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live',action='store_true',help='Run real remote EDA; consumes licenses and keeps evidence.')
parser.add_argument('--history-example',choices=list(EXAMPLES),default='rc_highpass')
args=parser.parse_args()
live_data=ROOT/'backend/runs'/('general_browser_'+uuid.uuid4().hex[:10])
if args.live:live_data.mkdir()
context=nullcontext(str(live_data)) if args.live else TemporaryDirectory(prefix='circuit-general-browser-')
with context as temp:
    data = Path(temp)
    candidates = [] if args.live else sorted((ROOT/'backend/runs').glob('vai_general_'+args.history_example+'_*/regression_result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    historical_id = None
    for candidate in candidates:
        result=json.loads(candidate.read_text(encoding='utf-8'))
        if result['status'] != 'PASS' or result['case'] != args.history_example:continue
        historical_id=result['run_id']
        destination=data/historical_id
        shutil.copytree(candidate.parent/'evidence',destination/'evidence')
        task=CircuitTask.model_validate_json((destination/'evidence/task.json').read_text(encoding='utf-8'))
        record=RunResult(run_id=historical_id,status='succeeded',created_at=utc_now(),updated_at=utc_now(),task=task,metrics=result['metrics'])
        atomic_json(destination/'run.json',record.model_dump())
        break
    manager=RunManager(data) if args.live else RunManager(data,fixture)
    if historical_id:
        manager._refresh_artifacts(manager.records[historical_id])
        manager._persist(manager.records[historical_id])
    mimetypes.add_type('text/javascript','.js')
    app=create_app(Settings(data_dir=data),manager)
    app.mount('/',StaticFiles(directory=ROOT/'frontend/dist',html=True),name='ui')
    listener=socket.socket();listener.bind(('127.0.0.1',0))
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    def stop():
        sys.stdin.readline();server.should_exit=True
    threading.Thread(target=stop,daemon=True).start()
    print(json.dumps({'url':f'http://127.0.0.1:{listener.getsockname()[1]}','historical_id':historical_id,'mode':'live' if args.live else 'fixture','data_dir':str(data)}),flush=True)
    server.run(sockets=[listener])
