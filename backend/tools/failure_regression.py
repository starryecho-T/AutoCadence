"""Exercise real remote preflight failure using the active connection settings.

Inject only a nonexistent Virtuoso path into a temporary config. The user's
configuration and existing evidence are not overwritten.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from vai_backend.api import create_app
from vai_backend.config import Settings, load_worker_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = load_worker_config()
    config['virtuoso_bin'] += '_intentional_m5_missing'
    original = os.environ.get('VAI_CONFIG')
    try:
        with TemporaryDirectory(prefix='circuit-failure-config-') as temporary:
            config_path = Path(temporary) / 'config.json'
            config_path.write_text(json.dumps(config), encoding='utf-8')
            os.environ['VAI_CONFIG'] = str(config_path)
            with TestClient(create_app(Settings(data_dir=ROOT / 'runs'))) as client:
                spec = json.loads((ROOT / 'examples/rc_m2_a.json').read_text())
                response = client.post('/api/v1/runs', json=spec)
                response.raise_for_status()
                run_id = response.json()['run_id']
                deadline = time.monotonic() + 150
                while True:
                    run = client.get('/api/v1/runs/' + run_id).json()
                    if run['status'] in ('failed', 'succeeded'):
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError('Failure injection did not reach a terminal state')
                    time.sleep(1)
                problems = []
                error = run.get('error') or {}
                if run['status'] != 'failed' or error.get('code') != 'ENVIRONMENT_MISSING' or error.get('stage') != 'preflight':
                    problems.append('Expected ENVIRONMENT_MISSING at preflight')
                if not any(s['name'] == 'download' and s['status'] == 'succeeded' for s in run['stages']):
                    problems.append('Failure evidence was not downloaded')
                for artifact in run['artifacts']:
                    downloaded = client.get(artifact['url'])
                    if downloaded.status_code != 200 or hashlib.sha256(downloaded.content).hexdigest() != artifact['sha256']:
                        problems.append('Artifact verification failed: ' + artifact['filename'])
                protection = ROOT / 'runs' / run_id / 'evidence/protection.json'
                if not protection.exists() or not json.loads(protection.read_text())['unchanged']:
                    problems.append('Protected-file check failed')
                result = {'verdict': 'PASS' if not problems else 'FAIL', 'run_id': run_id,
                          'mode': 'real_remote_failure_injection', 'checked_at': datetime.now(timezone.utc).isoformat(),
                          'status': run['status'], 'error': run['error'], 'artifacts_verified': len(run['artifacts']),
                          'problems': problems}
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(result, ensure_ascii=True))
                return 0 if not problems else 1
    finally:
        if original is None:
            os.environ.pop('VAI_CONFIG', None)
        else:
            os.environ['VAI_CONFIG'] = original


if __name__ == '__main__':
    raise SystemExit(main())
