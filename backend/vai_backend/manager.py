from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import queue
import re
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .models import Artifact, RunError, RunResult, Stage, TaskSpec

LOG = logging.getLogger(__name__)

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='\n') as output:
            json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def default_executor(task: dict, run_dir: Path, emit: Callable[[dict], None]) -> dict:
    from .pipeline import execute
    return execute(task, run_dir, emit)

def artifact_kind(path: Path) -> str:
    name, suffix = path.name.lower(), path.suffix.lower()
    if suffix in ('.html', '.htm'):
        return 'report_html'
    if suffix in ('.md', '.markdown'):
        return 'report_markdown'
    if suffix in ('.png', '.jpg', '.jpeg', '.svg', '.webp'):
        return 'schematic' if any(x in name for x in ('schematic', 'circuit', 'virtuoso')) else 'waveform'
    if suffix in ('.scs', '.cir') or name == 'netlist':
        return 'netlist'
    if suffix == '.log' or name in ('spectre.out', 'stdout.txt', 'stderr.txt'):
        return 'log'
    return 'data'

class RunManager:
    """One process / one worker. Never execute this service with multiple workers."""
    def __init__(self, data_dir: Path, executor: Callable = default_executor):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.executor = executor
        self.lock = threading.RLock()
        self.jobs: queue.Queue[str | None] = queue.Queue()
        self.records: dict[str, RunResult] = {}
        self.worker: threading.Thread | None = None
        self.stopping = threading.Event()
        self.recovery_warnings: list[str] = []
        self._load()

    def _load(self) -> None:
        for folder in sorted(self.data_dir.iterdir()):
            if not folder.is_dir() or folder.is_symlink():
                continue
            record_path = folder / 'run.json'
            if not record_path.is_file():
                continue
            try:
                record = RunResult.model_validate_json(record_path.read_text(encoding='utf-8'))
                if record.run_id != folder.name or not self._valid_id(record.run_id):
                    raise ValueError('run_id does not match directory')
                self.records[record.run_id] = record
                if record.status in ('queued', 'running'):
                    record.status = 'failed'
                    record.updated_at = utc_now()
                    record.error = RunError(code='INTERRUPTED', stage='recovery', message='Backend restarted before this run completed. Submit a new run to retry.')
                    for stage in record.stages:
                        if stage.status in ('running', 'pending'):
                            stage.status = 'failed'
                            stage.finished_at = record.updated_at
                            stage.message = 'Interrupted by backend restart'
                    self._log(record.run_id, 'RECOVERY: interrupted run marked failed')
                    self._refresh_artifacts(record)
                    self._persist(record)
            except (OSError, ValueError) as exc:
                self.recovery_warnings.append(f'Unreadable run record: {folder.name}')
                LOG.warning('Skipping invalid run record %s: %s', folder.name, exc)

    @staticmethod
    def _valid_id(value: str) -> bool:
        return bool(re.fullmatch(r'[a-z][a-z0-9_]{5,80}', value))

    def start(self) -> None:
        with self.lock:
            if self.worker and self.worker.is_alive():
                return
            self.stopping.clear()
            self.worker = threading.Thread(target=self._loop, name='vai-single-worker', daemon=True)
            self.worker.start()

    def close(self) -> None:
        self.stopping.set()
        self.jobs.put(None)
        if self.worker:
            self.worker.join(timeout=2)

    def stats(self) -> dict:
        with self.lock:
            return {
                'queued': sum(r.status == 'queued' for r in self.records.values()),
                'running': sum(r.status == 'running' for r in self.records.values()),
                'worker_alive': bool(self.worker and self.worker.is_alive()),
                'recovery_warnings': list(self.recovery_warnings),
            }

    def submit(self, task: TaskSpec) -> RunResult:
        run_id = 'vai_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:12]
        now = utc_now()
        record = RunResult(run_id=run_id, status='queued', created_at=now, updated_at=now, task=task)
        with self.lock:
            if self.stopping.is_set():
                raise RuntimeError('Backend is shutting down')
            (self.data_dir / run_id / 'evidence').mkdir(parents=True, exist_ok=False)
            self.records[run_id] = record
            self._log(run_id, 'QUEUED: task accepted')
            self._refresh_artifacts(record)
            self._persist(record)
            snapshot = record.model_copy(deep=True)
            self.jobs.put(run_id)
            return snapshot

    def get(self, run_id: str) -> RunResult | None:
        with self.lock:
            record = self.records.get(run_id)
            if record is None:
                return None
            if record.status in ('queued', 'running'):
                self._refresh_artifacts(record)
            return record.model_copy(deep=True)

    def list(self, limit: int = 50) -> list[RunResult]:
        with self.lock:
            return [x.model_copy(deep=True) for x in sorted(self.records.values(), key=lambda r: r.created_at, reverse=True)[:limit]]

    def artifact_path(self, run_id: str, artifact_id: str) -> tuple[Path, Artifact] | None:
        with self.lock:
            record = self.records.get(run_id)
            if record is None:
                return None
            if record.status in ('queued', 'running'):
                self._refresh_artifacts(record)
            artifact = next((x for x in record.artifacts if x.id == artifact_id), None)
            if artifact is None:
                return None
            root = (self.data_dir / run_id / 'evidence').resolve()
            index_path = self.data_dir / run_id / 'artifact_index.json'
            try:
                relative = json.loads(index_path.read_text(encoding='utf-8')).get(artifact_id)
                if not isinstance(relative, str):
                    return None
                candidate = root / relative
                resolved = candidate.resolve()
                if not resolved.is_relative_to(root) or not candidate.is_file() or candidate.is_symlink():
                    return None
                return resolved, artifact.model_copy(deep=True)
            except (OSError, ValueError):
                return None

    def _persist(self, record: RunResult) -> None:
        atomic_json(self.data_dir / record.run_id / 'run.json', record.model_dump(mode='json'))

    def _log(self, run_id: str, message: str) -> None:
        path = self.data_dir / run_id / 'evidence' / 'api-worker.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8', newline='\n') as handle:
            handle.write(f'{utc_now()} {message}\n')

    def _refresh_artifacts(self, record: RunResult) -> None:
        root = (self.data_dir / record.run_id / 'evidence').resolve()
        artifacts, index = [], {}
        for path in sorted(root.rglob('*')):
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                continue
            try:
                relative = path.relative_to(root).as_posix()
                artifact_id = hashlib.sha256(relative.encode('utf-8')).hexdigest()[:20]
                digest = hashlib.sha256()
                size = 0
                with path.open('rb') as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                        digest.update(chunk)
                        size += len(chunk)
                artifacts.append(Artifact(
                    id=artifact_id, kind=artifact_kind(path), filename=relative,
                    media_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream',
                    bytes=size, sha256=digest.hexdigest(),
                    url=f'/api/v1/runs/{record.run_id}/artifacts/{artifact_id}',
                ))
                index[artifact_id] = relative
            except OSError:
                LOG.warning('Could not index changing artifact %s', path.name)
        record.artifacts = artifacts
        atomic_json(self.data_dir / record.run_id / 'artifact_index.json', index)

    def _emit(self, run_id: str, payload: dict) -> None:
        stage = Stage.model_validate(payload)
        with self.lock:
            record = self.records[run_id]
            now = utc_now()
            if stage.status == 'running' and stage.started_at is None:
                stage.started_at = now
            old = next((item for item in record.stages if item.name == stage.name), None)
            if old:
                data = old.model_dump()
                data.update(stage.model_dump(exclude_unset=True))
                stage = Stage.model_validate(data)
                record.stages[record.stages.index(old)] = stage
            else:
                record.stages.append(stage)
            if stage.status in ('succeeded', 'failed') and stage.finished_at is None:
                stage.finished_at = now
            record.updated_at = now
            self._log(run_id, f'STAGE {stage.name}: {stage.status}' + (f' - {stage.message}' if stage.message else ''))
            self._refresh_artifacts(record)
            self._persist(record)

    def _loop(self) -> None:
        while not self.stopping.is_set():
            run_id = self.jobs.get()
            if run_id is None:
                self.jobs.task_done()
                break
            try:
                self._execute(run_id)
            except Exception:
                LOG.exception('Failed to persist worker result for %s', run_id)
            finally:
                self.jobs.task_done()

    def _execute(self, run_id: str) -> None:
        with self.lock:
            record = self.records[run_id]
            record.status = 'running'
            record.updated_at = utc_now()
            self._log(run_id, 'RUNNING: pipeline started')
            self._persist(record)
            task = record.task.model_dump(mode='json')
        try:
            output = self.executor(task, self.data_dir / run_id, lambda item: self._emit(run_id, item))
            if not isinstance(output, dict):
                raise TypeError('Pipeline must return a dict containing metrics and warnings')
            with self.lock:
                record.metrics = output.get('metrics', {})
                record.warnings = output.get('warnings', [])
                if any(s.status in ('failed', 'running', 'pending') for s in record.stages):
                    raise ValueError('Pipeline returned with unfinished or failed stages')
                record.status = 'succeeded'
                record.updated_at = utc_now()
                self._log(run_id, 'SUCCEEDED: pipeline completed')
                self._refresh_artifacts(record)
                self._persist(record)
        except Exception as exc:
            with self.lock:
                record.status = 'failed'
                record.updated_at = utc_now()
                stage_name = str(getattr(exc, 'stage', 'pipeline'))
                code = str(getattr(exc, 'code', 'PIPELINE_ERROR'))
                record.error = RunError(code=code, stage=stage_name, message=str(exc)[:2000] or type(exc).__name__)
                for stage in record.stages:
                    if stage.status == 'running':
                        stage.status = 'failed'
                        stage.finished_at = record.updated_at
                        stage.message = record.error.message
                self._log(run_id, f'FAILED {code}: {record.error.message}\n{traceback.format_exc()}')
                self._refresh_artifacts(record)
                self._persist(record)
