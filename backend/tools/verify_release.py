"""Read-only M5 audit of frozen contracts and existing run evidence.

This verifies saved files, not a new remote Cadence execution.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FROZEN_CONTRACTS = {
    'task.schema.json': 'a172955671d9665ff171e1184eba3a4b4851a5ec2457e37d3197cc68ad717c0f',
    'result.schema.json': '2465f6a7a0f24270496fe67acf6f697479922928ebbc15cc158a87a4fa94230a',
    'openapi.json': '17cfb4060c80eaf37233c0bf67a8c16cb97e1fa0ed8b0725979bc0a42b3509d0',
}
REQUIRED = {'schematic_window.png', 'waveform_window.png', 'report.html',
            'report.md', 'metrics.json', 'input.scs', 'image_validation.json'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(run_id):
    checks = []

    def check(name, ok, detail):
        checks.append({'name': name, 'status': 'PASS' if ok else 'FAIL', 'detail': detail})

    for filename, expected in FROZEN_CONTRACTS.items():
        path = ROOT / 'contracts' / filename
        actual = digest(path) if path.is_file() else None
        check('contract:' + filename, actual == expected, {'expected_sha256': expected, 'actual_sha256': actual})
    if not re.fullmatch(r'[a-z][a-z0-9_]{5,80}', run_id):
        raise ValueError('Invalid run_id')
    folder = ROOT / 'runs' / run_id
    record_path = folder / 'run.json'
    if not record_path.is_file():
        check('historical_run', False, 'Historical run is not bundled')
    else:
        run = json.loads(record_path.read_text(encoding='utf-8'))
        check('historical_run', run['run_id'] == run_id and run['status'] == 'succeeded', run['status'])
        evidence = (folder / 'evidence').resolve()
        index = json.loads((folder / 'artifact_index.json').read_text(encoding='utf-8'))
        names = {artifact['filename'] for artifact in run['artifacts']}
        check('required_artifacts', REQUIRED <= names, {'missing': sorted(REQUIRED - names)})
        for artifact in run['artifacts']:
            relative = index.get(artifact['id'], '')
            path = (evidence / relative).resolve()
            valid = bool(relative) and path.is_relative_to(evidence) and path.is_file() and not path.is_symlink()
            valid = valid and relative == artifact['filename']
            actual = digest(path) if valid else None
            check('artifact:' + artifact['filename'], valid and actual == artifact['sha256'] and path.stat().st_size == artifact['bytes'], {'actual_sha256': actual})
        metrics = json.loads((evidence / 'metrics.json').read_text(encoding='utf-8'))
        check('metrics_match_run', metrics == run['metrics'], 'Stored metrics must equal RunResult metrics')
        check('numerical_validation', metrics.get('validation_status') == 'PASS' and len(metrics.get('checks', [])) == 18 and all(c['status'] == 'PASS' for c in metrics.get('checks', [])), {'checks': len(metrics.get('checks', []))})
        images = json.loads((evidence / 'image_validation.json').read_text(encoding='utf-8'))
        check('image_validation', images.get('ok') is True, images.get('ok'))
        protection = json.loads((evidence / 'protection.json').read_text(encoding='utf-8'))
        check('protected_files', protection.get('unchanged') is True, protection.get('unchanged'))
    return {'status': 'PASS' if all(c['status'] == 'PASS' for c in checks) else 'FAIL',
            'checked_at': datetime.now(timezone.utc).isoformat(), 'mode': 'historical_evidence_audit',
            'remote_simulation_executed': False, 'run_id': run_id, 'checks': checks}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', default='vai_20261018_073200_c20608d57c75')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.run_id)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'status': result['status'], 'mode': result['mode'], 'checks': len(result['checks']),
                      'failures': [check for check in result['checks'] if check['status'] == 'FAIL']}, ensure_ascii=False))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
