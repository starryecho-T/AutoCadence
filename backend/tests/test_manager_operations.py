import hashlib
import json
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

import vai_backend.manager as manager_module
from vai_backend.api import create_app
from vai_backend.circuit_examples import EXAMPLES
from vai_backend.config import Settings
from vai_backend.manager import RunManager, QueueFull
from vai_backend.models import TaskSpec
from vai_backend.pipeline import PipelineError

V1_TASK = {'r_ohm': 1000, 'c_f': 1e-7}


def wait_terminal(manager, run_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = manager.get(run_id)
        if record.status in ('succeeded', 'failed'):
            return record
        time.sleep(.02)
    raise AssertionError('run did not reach a terminal state')


def wait(client, run_id):
    for _ in range(100):
        data = client.get('/api/v1/runs/' + run_id).json()
        if data['status'] in ('succeeded', 'failed'):
            return data
        time.sleep(.02)
    raise AssertionError('test job timeout')


def test_refresh_artifacts_reuses_cached_digests(tmp_path, monkeypatch):
    counts = {'hashed': 0}
    real = manager_module.hash_file
    def counting(path):
        counts['hashed'] += 1
        return real(path)
    monkeypatch.setattr(manager_module, 'hash_file', counting)
    manager = RunManager(tmp_path)  # no worker: records stay queued and are refreshed by get()
    record = manager.submit(TaskSpec(**V1_TASK))
    evidence = tmp_path / record.run_id / 'evidence'
    (evidence / 'a.txt').write_text('alpha')
    (evidence / 'logs').mkdir()
    (evidence / 'logs' / 'b.log').write_text('beta')
    first = manager.get(record.run_id)
    assert counts['hashed'] >= 2  # every evidence file was hashed exactly once
    first_pass = counts['hashed']
    by_name = {a.filename: a.sha256 for a in first.artifacts}
    assert by_name['a.txt'] == hashlib.sha256(b'alpha').hexdigest()
    index = json.loads((tmp_path / record.run_id / 'artifact_index.json').read_text(encoding='utf-8'))
    assert index == {a.id: a.filename for a in first.artifacts}
    second = manager.get(record.run_id)
    assert counts['hashed'] == first_pass  # unchanged files: zero hash computations
    assert {a.filename: a.sha256 for a in second.artifacts} == by_name
    (evidence / 'a.txt').write_text('gamma')  # same size, different content
    stat = (evidence / 'a.txt').stat()
    os.utime(evidence / 'a.txt', ns=(stat.st_mtime_ns + 1_000_000,) * 2)
    third = manager.get(record.run_id)
    assert counts['hashed'] == first_pass + 1  # exactly one file re-hashed
    assert {a.filename: a.sha256 for a in third.artifacts}['a.txt'] == hashlib.sha256(b'gamma').hexdigest()
    (evidence / 'logs' / 'b.log').unlink()
    fourth = manager.get(record.run_id)
    assert counts['hashed'] == first_pass + 1  # deletion clears cache without re-hashing survivors
    assert [a.filename for a in fourth.artifacts] == ['a.txt', 'api-worker.log']


def test_failed_persist_still_leaves_record_failed(tmp_path, monkeypatch):
    def executor(task, root, emit):
        raise PipelineError('SIMULATION_FAILED', 'spectre', 'boom')
    manager = RunManager(tmp_path, executor)
    submitted = manager.submit(TaskSpec(**V1_TASK))
    real_persist = manager._persist
    def exploding_persist(record):
        if record.status == 'failed':
            raise OSError('injected disk full')
        real_persist(record)
    monkeypatch.setattr(manager, '_persist', exploding_persist)
    manager.start()
    record = wait_terminal(manager, submitted.run_id)
    assert record.status == 'failed' and record.error.code == 'SIMULATION_FAILED'
    assert manager.stats()['running'] == 0


def test_base_exception_still_finalizes_record_and_keeps_worker_alive(tmp_path):
    calls = {'n': 0}
    def executor(task, root, emit):
        calls['n'] += 1
        if calls['n'] == 1:
            raise KeyboardInterrupt('injected BaseException')
        (root / 'evidence/ok.txt').write_text('recovered')
        return {'metrics': {'ok': True}, 'warnings': []}
    manager = RunManager(tmp_path, executor)
    first = manager.submit(TaskSpec(**V1_TASK))
    manager.start()
    record = wait_terminal(manager, first.run_id)
    assert record.status == 'failed' and record.error is not None
    assert manager.stats()['worker_alive']
    second = manager.submit(TaskSpec(r_ohm=2000, c_f=1e-7))
    assert wait_terminal(manager, second.run_id).status == 'succeeded'


def test_delete_cancels_only_queued_runs(tmp_path):
    release = threading.Event()
    def executor(task, root, emit):
        release.wait(5)
        (root / 'evidence/result.txt').write_text('done')
        return {'metrics': {}, 'warnings': []}
    manager = RunManager(tmp_path, executor)
    with TestClient(create_app(Settings(data_dir=tmp_path), manager)) as client:
        assert client.get('/api/v1/capabilities').json()['limits']['supports_cancellation'] is True
        first = client.post('/api/v1/runs', json=V1_TASK).json()['run_id']
        deadline = time.time() + 5
        while time.time() < deadline and client.get('/api/v1/runs/' + first).json()['status'] != 'running':
            time.sleep(.01)
        second = client.post('/api/v1/runs', json=V1_TASK).json()['run_id']
        cancelled = client.delete('/api/v1/runs/' + second)
        assert cancelled.status_code == 200
        assert cancelled.json()['status'] == 'failed'
        assert cancelled.json()['error']['code'] == 'CANCELLED'
        assert client.delete('/api/v2/runs/' + second).status_code == 409  # already terminal
        assert client.delete('/api/v2/runs/' + first).status_code == 409  # running
        assert client.delete('/api/v1/runs/vai_missing_run').status_code == 404
        release.set()
        assert wait(client, first)['status'] == 'succeeded'  # worker executed the first job only
        assert client.get('/api/v1/runs/' + second).json()['error']['code'] == 'CANCELLED'


def test_queue_capacity_is_enforced_inside_submit(tmp_path):
    manager = RunManager(tmp_path, max_queued=1)
    manager.submit(TaskSpec(**V1_TASK))
    with pytest.raises(QueueFull):
        manager.submit(TaskSpec(**V1_TASK))


def test_concurrent_submissions_never_exceed_capacity(tmp_path):
    manager = RunManager(tmp_path / 'two', max_queued=2)
    barrier = threading.Barrier(8)
    outcome = []
    def submitter():
        barrier.wait()
        try:
            outcome.append(manager.submit(TaskSpec(**V1_TASK)).run_id)
        except QueueFull:
            outcome.append(None)
    threads = [threading.Thread(target=submitter) for _ in range(8)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(10)
    assert len(outcome) == 8
    assert sum(x is not None for x in outcome) == 2
    assert sum(r.status == 'queued' for r in manager.records.values()) == 2


def test_queue_full_api_response_shape_unchanged(tmp_path):
    release = threading.Event()
    def executor(task, root, emit):
        release.wait(5)
        return {'metrics': {}, 'warnings': []}
    manager = RunManager(tmp_path, executor, max_queued=1)
    with TestClient(create_app(Settings(data_dir=tmp_path), manager)) as client:
        first = client.post('/api/v1/runs', json=V1_TASK).json()['run_id']
        deadline = time.time() + 5
        while time.time() < deadline and client.get('/api/v1/runs/' + first).json()['status'] != 'running':
            time.sleep(.01)
        assert client.post('/api/v1/runs', json=V1_TASK).status_code == 202  # the one queued slot
        full = client.post('/api/v1/runs', json=V1_TASK)
        assert full.status_code == 429 and full.json()['error']['code'] == 'QUEUE_FULL'
        assert full.json()['error']['message'] == 'Queue is full; retry after a current run completes'
        parsed = client.post('/api/v2/parse', json={'text': EXAMPLES['divider'][1]})
        v2full = client.post('/api/v2/runs', json=parsed.json()['task'])
        assert v2full.status_code == 429 and v2full.json()['error']['code'] == 'QUEUE_FULL'
        release.set()
        assert wait(client, first)['status'] == 'succeeded'
