# -*- coding: utf-8 -*-
"""M2 one-shot API regression driver (foreground, single process).

Boots the real FastAPI service (uvicorn) in a background *thread* of this
foreground process, then drives three real remote Cadence runs through the
public HTTP API exactly the way the frontend will:

    1. m2_a         examples/rc_m2_a.json   (R=1k, C=100n, 0..3.3V, 1 ms period)
    2. m2_b         examples/rc_m2_b.json   (R=10k, C=100n, 0..2.5V, 8 ms period)
    3. m2_a_repeat  examples/rc_m2_a.json   (identical repeat of run 1)

Acceptance criteria checked per run (M2: parameterization + full periods):
  * status == succeeded, error is None, all 13 stages succeeded
  * metrics.validation_status == PASS (deterministic numeric checks)
  * cutoff frequency within 1% of 1/(2*pi*R*C) for both parameter sets
  * complete pulse coverage: >= 2 rising and >= 2 falling edges
  * every required artifact downloadable over HTTP with matching SHA-256
  * image_validation.ok == true (real Cadence screenshots verified)

Stability: m2_a vs m2_a_repeat key metrics must match within 1e-6 relative.

Writes docs/m2_regression_summary.json. Exit code 0 == M2 regression PASS.
This script doubles as the M5 regression tool.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        pass
sys.path.insert(0, str(ROOT))

import httpx
import uvicorn

from vai_backend.api import create_app
from vai_backend.config import Settings

HOST = '127.0.0.1'
PORT = 8765
BASE_URL = f'http://{HOST}:{PORT}'
SUMMARY_PATH = ROOT / 'docs' / 'm2_regression_summary.json'
POLL_INTERVAL_S = 2.0
PER_RUN_TIMEOUT_S = 300.0
OVERALL_DEADLINE_S = 540.0
STABILITY_TOLERANCE = 1e-6
FC_TOLERANCE = 0.01

REQUIRED_STAGES = ('upload', 'preflight', 'build', 'probe', 'netlist',
                   'netlist_validation', 'spectre', 'export', 'capture',
                   'download', 'image_validation', 'validation', 'report')
REQUIRED_ARTIFACTS = ('schematic_window.png', 'waveform_window.png',
                      'report.html', 'report.md', 'metrics.json',
                      'input.scs', 'image_validation.json')
STABILITY_METRICS = ('fc_hz', 'vout_at_tau', 'vout_at_100us', 'tran_end_s',
                     'transient_max_relative_error')

TASKS = (
    ('m2_a', ROOT / 'examples' / 'rc_m2_a.json'),
    ('m2_b', ROOT / 'examples' / 'rc_m2_b.json'),
    ('m2_a_repeat', ROOT / 'examples' / 'rc_m2_a.json'),
)


def log(message: str) -> None:
    stamp = datetime.now().strftime('%H:%M:%S')
    print(f'[{stamp}] {message}', flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def start_server() -> tuple[uvicorn.Server, dict]:
    settings = Settings(data_dir=ROOT / 'runs', host=HOST, port=PORT)
    server = uvicorn.Server(uvicorn.Config(
        create_app(settings), host=HOST, port=PORT, log_level='warning', access_log=False))
    thread = threading.Thread(target=server.run, name='vai-uvicorn', daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    last_error = 'unknown'
    while time.monotonic() < deadline:
        try:
            response = httpx.get(BASE_URL + '/health', timeout=2)
            if response.status_code == 200:
                return server, response.json()
            last_error = f'/health -> {response.status_code}'
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.3)
    raise RuntimeError(f'API server did not become healthy within 30 s: {last_error}')


def wait_terminal(client: httpx.Client, run_id: str, seen: set, deadline: float) -> tuple[dict, float]:
    started = time.monotonic()
    last_status = None
    while True:
        remaining = min(PER_RUN_TIMEOUT_S, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError(f'{run_id}: no terminal state before deadline')
        response = client.get(f'/api/v1/runs/{run_id}', timeout=15)
        response.raise_for_status()
        body = response.json()
        if body['status'] != last_status:
            last_status = body['status']
            log(f'  {run_id}: status -> {last_status}')
        for stage in body.get('stages', []):
            if stage['status'] == 'succeeded' and (run_id, stage['name']) not in seen:
                seen.add((run_id, stage['name']))
                log(f'  {run_id}: stage ok -> {stage["name"]}')
        if body['status'] in ('succeeded', 'failed'):
            return body, time.monotonic() - started
        time.sleep(min(POLL_INTERVAL_S, max(remaining, 0.2)))


def verify_run(client: httpx.Client, label: str, spec: dict, body: dict, elapsed: float) -> dict:
    problems: list[str] = []

    def require(condition: bool, message: str) -> bool:
        if not condition:
            problems.append(message)
        return condition

    require(body.get('status') == 'succeeded', f'{label}: status={body.get("status")!r}')
    require(body.get('error') is None, f'{label}: error={body.get("error")!r}')
    metrics = body.get('metrics') or {}
    require(metrics.get('validation_status') == 'PASS',
            f'{label}: validation_status={metrics.get("validation_status")!r}')
    stages = {s['name']: s for s in body.get('stages', [])}
    for name in REQUIRED_STAGES:
        status = stages.get(name, {}).get('status', 'MISSING')
        require(status == 'succeeded', f'{label}: stage {name} -> {status}')
    fc_theory = 1 / (2 * math.pi * spec['r_ohm'] * spec['c_f'])
    fc = metrics.get('fc_hz')
    require(isinstance(fc, (int, float)), f'{label}: fc_hz missing from metrics')
    fc_rel = abs(fc / fc_theory - 1) if isinstance(fc, (int, float)) else None
    require(fc_rel is not None and fc_rel <= FC_TOLERANCE,
            f'{label}: fc={fc} theory={fc_theory:.4f} rel_error={fc_rel}')
    checks = {c['name']: c for c in metrics.get('checks', [])}
    edges = (checks.get('pulse_edges') or {}).get('actual') or {}
    rising = min(edges.get('rising') or [0])
    falling = min(edges.get('falling') or [0])
    require(rising >= 2 and falling >= 2,
            f'{label}: pulse edges rising={edges.get("rising")} falling={edges.get("falling")}')
    require('complete_pulse_cycles' in checks, f'{label}: complete_pulse_cycles check missing')

    by_name = {a['filename']: a for a in body.get('artifacts', [])}
    fetched: dict[str, bytes] = {}
    for name in REQUIRED_ARTIFACTS:
        meta = by_name.get(name)
        if meta is None:
            problems.append(f'{label}: artifact missing from index: {name}')
            continue
        response = client.get(meta['url'], timeout=120)
        content = response.content
        ok = (response.status_code == 200 and len(content) == meta['bytes']
              and hashlib.sha256(content).hexdigest() == meta['sha256'])
        if name.endswith('.png'):
            ok = ok and content[:8] == b'\x89PNG\r\n\x1a\n'
        require(ok, f'{label}: artifact {name} failed HTTP integrity check '
                    f'(status={response.status_code}, len={len(content)}, expected={meta["bytes"]})')
        fetched[name] = content
    image_ok = None
    if 'image_validation.json' in fetched:
        try:
            image_ok = json.loads(fetched['image_validation.json']).get('ok')
        except ValueError:
            image_ok = None
        require(image_ok is True, f'{label}: image_validation.ok={image_ok!r}')
    return {
        'label': label,
        'run_id': body.get('run_id'),
        'status': body.get('status'),
        'elapsed_s': round(elapsed, 1),
        'warnings': body.get('warnings', []),
        'fc_hz': fc,
        'fc_theory_hz': fc_theory,
        'fc_relative_error_pct': metrics.get('fc_relative_error_pct'),
        'vout_at_tau': metrics.get('vout_at_tau'),
        'vout_at_100us': metrics.get('vout_at_100us'),
        'tran_end_s': metrics.get('tran_end_s'),
        'ac_points': metrics.get('ac_points'),
        'tran_points': metrics.get('tran_points'),
        'pulse_edges': {'rising': edges.get('rising'), 'falling': edges.get('falling')},
        'transient_max_relative_error': metrics.get('transient_max_relative_error'),
        'stages_ok': sum(1 for n in REQUIRED_STAGES if stages.get(n, {}).get('status') == 'succeeded'),
        'image_validation_ok': image_ok,
        'artifacts': {name: {'bytes': by_name[name]['bytes'], 'sha256': by_name[name]['sha256']}
                      for name in REQUIRED_ARTIFACTS if name in by_name},
        'metrics_raw': {key: metrics.get(key) for key in STABILITY_METRICS},
        'problems': problems,
    }


def verify_stability(a: dict, b: dict) -> dict:
    comparisons = []
    ok = True
    for key in STABILITY_METRICS:
        x = a['metrics_raw'].get(key)
        y = b['metrics_raw'].get(key)
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            ok = False
            comparisons.append({'metric': key, 'm2_a': x, 'm2_a_repeat': y, 'relative_diff': None})
            continue
        rel = abs(x - y) / max(abs(x), abs(y))
        if rel > STABILITY_TOLERANCE:
            ok = False
        comparisons.append({'metric': key, 'm2_a': x, 'm2_a_repeat': y, 'relative_diff': rel})
    return {'status': 'PASS' if ok else 'FAIL',
            'tolerance_relative': STABILITY_TOLERANCE,
            'comparisons': comparisons}


def _fmt(value, pattern: str) -> str:
    return pattern.format(value) if isinstance(value, (int, float)) else str(value)


def main() -> int:
    overall_start = time.monotonic()
    deadline = overall_start + OVERALL_DEADLINE_S
    started_at = utc_now()
    log('M2 regression driver starting (foreground single process, three real remote runs)')
    failures: list[str] = []
    runs_summary: dict[str, dict] = {}
    stability = None
    health = {}
    server = None
    try:
        server, health = start_server()
        log(f'API healthy on {BASE_URL}; queue: {health.get("queue")}')
        seen: set = set()
        with httpx.Client(base_url=BASE_URL) as client:
            submissions = []
            for label, path in TASKS:
                spec = json.loads(path.read_text(encoding='utf-8'))
                response = client.post('/api/v1/runs', json=spec, timeout=30)
                if response.status_code != 202:
                    failures.append(f'{label}: POST /api/v1/runs -> {response.status_code} {response.text[:200]}')
                    continue
                snapshot = response.json()
                if snapshot.get('status') != 'queued':
                    failures.append(f'{label}: expected queued snapshot, got {snapshot.get("status")!r}')
                submissions.append((label, spec, snapshot['run_id']))
                log(f'  submitted {label} -> {snapshot["run_id"]}')
            results = {}
            for label, spec, run_id in submissions:
                log(f'waiting for {label} ({run_id})')
                try:
                    body, elapsed = wait_terminal(client, run_id, seen, deadline)
                    summary = verify_run(client, label, spec, body, elapsed)
                except Exception as exc:
                    failures.append(f'{label}: {type(exc).__name__}: {exc}')
                    continue
                results[label] = summary
                runs_summary[label] = {k: v for k, v in summary.items()
                                       if k not in ('metrics_raw', 'problems')}
                if summary['problems']:
                    failures.extend(summary['problems'])
                    log(f'  {label}: finished with {len(summary["problems"])} problem(s)')
                else:
                    log(f'  {label}: OK in {summary["elapsed_s"]}s, '
                        f'fc={_fmt(summary["fc_hz"], "{:.3f}")} Hz '
                        f'(err {_fmt(summary["fc_relative_error_pct"], "{:.4f}")}%), '
                        f'edges r/f={summary["pulse_edges"]["rising"]}/{summary["pulse_edges"]["falling"]}')
            if 'm2_a' in results and 'm2_a_repeat' in results:
                stability = verify_stability(results['m2_a'], results['m2_a_repeat'])
                if stability['status'] != 'PASS':
                    failures.append('stability m2_a vs m2_a_repeat: '
                                    + json.dumps(stability['comparisons']))
            try:
                listed = client.get('/api/v1/runs?limit=50', timeout=15).json()['runs']
                listed_ids = {r['run_id'] for r in listed}
                for _, _, run_id in submissions:
                    if run_id not in listed_ids:
                        failures.append(f'run list endpoint missing {run_id}')
            except Exception as exc:
                failures.append(f'run list endpoint failed: {exc}')
    except Exception as exc:
        failures.append(f'driver: {type(exc).__name__}: {exc}')
    finally:
        if server is not None:
            server.should_exit = True

    summary = {
        'milestone': 'M2',
        'verdict': 'PASS' if not failures else 'FAIL',
        'driver': 'tools/m2_regression.py',
        'api_base': BASE_URL,
        'health': health,
        'started_at': started_at,
        'finished_at': utc_now(),
        'total_elapsed_s': round(time.monotonic() - overall_start, 1),
        'tasks': [{'label': label, 'file': str(path.relative_to(ROOT))} for label, path in TASKS],
        'runs': runs_summary,
        'stability': stability,
        'failures': failures,
    }
    try:
        SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as exc:
        print(f'ERROR: could not write summary: {exc}', file=sys.stderr, flush=True)

    log('--- M2 regression results ---')
    for label in ('m2_a', 'm2_b', 'm2_a_repeat'):
        item = runs_summary.get(label)
        if item is None:
            print(f'  {label:12s} MISSING', flush=True)
            continue
        print(f'  {label:12s} {str(item["status"]):9s} {_fmt(item["elapsed_s"], "{:7.1f}")}s '
              f'fc={_fmt(item["fc_hz"], "{:.2f}")}Hz '
              f'err={_fmt(item["fc_relative_error_pct"], "{:.4f}")}% '
              f'edges={item["pulse_edges"]["rising"]}/{item["pulse_edges"]["falling"]} '
              f'stages={item["stages_ok"]}/13 images_ok={item["image_validation_ok"]}', flush=True)
    if stability:
        worst = max((c['relative_diff'] if c['relative_diff'] is not None else float('inf'))
                    for c in stability['comparisons'])
        print(f'  stability     {stability["status"]}  worst relative diff={worst:.3g} '
              f'(tolerance {STABILITY_TOLERANCE:g})', flush=True)
    for problem in failures:
        print(f'  FAILURE: {problem}', flush=True)
    log(f'verdict: {summary["verdict"]}; summary -> {SUMMARY_PATH}')
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(main())
