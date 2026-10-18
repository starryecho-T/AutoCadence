"""Read-only, bounded AI evidence assembled from this run's registered artifacts."""
from __future__ import annotations

import json
import math
import re

from .circuit_analysis import read_wave, evaluate
from .analysis import AnalysisError

MAX_CONTEXT = 80000


def summarize_wave(rows, entry):
    result = {**entry, 'samples': len(rows), 'x_range': [rows[0][0], rows[-1][0]],
              'columns': ['x', 'real', 'imag'] if len(rows[0]) == 3 else ['x', 'value']}
    modes = ['real', 'imag', 'magnitude', 'phase_deg'] if len(rows[0]) == 3 else ['real']
    for mode in modes:
        def value(row):
            z = complex(row[1], row[2] if len(row) == 3 else 0)
            return {'real': z.real, 'imag': z.imag, 'magnitude': abs(z),
                    'phase_deg': math.degrees(math.atan2(z.imag, z.real))}[mode]
        low, high = min(rows, key=value), max(rows, key=value)
        result[mode] = {'min': value(low), 'min_at': low[0], 'max': value(high), 'max_at': high[0]}
    if entry['analysis'] == 'tran':
        for operation in ('mean', 'rms'):
            result[operation] = evaluate(rows, {'analysis': 'tran', 'representation': 'real', 'operation': operation})
    indexes = sorted({round(i * (len(rows) - 1) / 23) for i in range(24)})
    result['sample_rows'] = [rows[i] for i in indexes]
    result['rows_sampled'] = len(indexes) < len(rows)
    return result


def build_result_context(record, artifact_path):
    """Never opens arbitrary paths, invokes a model, or modifies run evidence."""
    data = record.model_dump(mode='json')
    artifacts = {a.filename: a for a in record.artifacts}
    read, omitted, sources = [], [], []
    byte_budget = 64 * 1024 * 1024

    def registered(name):
        nonlocal byte_budget
        meta = artifacts.get(name)
        item = artifact_path(record.run_id, meta.id) if meta else None
        if not item:
            raise ValueError('文件缺失或未登记')
        path, _ = item
        size = path.stat().st_size
        if size > min(byte_budget, 20 * 1024 * 1024):
            raise ValueError('文件超出本次读取上限')
        byte_budget -= size
        read.append(name)
        return path

    def text_file(name, limit=8000):
        path = registered(name)
        with path.open('rb') as stream:
            if path.stat().st_size > limit:
                stream.seek(-limit, 2)
            content = stream.read(limit).decode('utf-8', errors='replace')
        if path.stat().st_size > limit:
            content = '[仅保留文件末尾]\n' + content
        # Credentials do not belong in model context, even if pasted in a log.
        return re.sub(r'(?i)(bearer\s+|(?:api[_-]?key|token|password)\s*[=:]\s*)[^\s,;"\']+', r'\1[已隐藏]', content)

    core = {k: data.get(k) for k in ('run_id', 'status', 'created_at', 'task', 'metrics', 'error', 'warnings', 'stages')}
    core['evidence_rules'] = ('仅依据本次任务的数据。样本极值、均值和RMS由原始导出数据计算；sample_rows是显示用抽样，'
                              '不能用抽样推断精确截止频率或漏掉的瞬态尖峰。AC列为频率Hz、实部、虚部；phase_deg单位为度；'
                              'tran横轴秒，dc横轴单位依扫描源。执行成功不等于所有设计目标达标。未读取项不得声称已读取。')
    entries = []
    if 'signals.json' in artifacts:
        try:
            entries = json.loads(registered('signals.json').read_text(encoding='utf-8'))
            if not isinstance(entries, list):
                raise ValueError('信号清单无效')
        except (OSError, ValueError) as exc:
            entries = []
            omitted.append('signals.json: ' + str(exc))
    else:
        # Legacy RC exports use dB directly rather than complex AC values.
        entries = [{'filename': n, 'analysis': 'tran' if n.startswith('tran') else 'ac',
                    'signal': n.removesuffix('.txt'), 'unit': 'V' if n.startswith('tran') else 'dB'}
                   for n in ('tran_in.txt', 'tran_out.txt', 'ac_vdb_in.txt', 'ac_vdb_out.txt') if n in artifacts]
    for entry in entries:
        try:
            name = entry['filename']
            if not re.fullmatch(r'(?:s\d{3}_|yp1_|yp2_|ypcheck_|equivalent_)?(?:ac|dc|tran|op)_[\w]+\.txt', name):
                raise ValueError('不支持的信号文件名')
            path = registered(name)
            rows = read_wave(path, entry['analysis'] == 'ac' and entry.get('unit') != 'dB')
            sources.append(summarize_wave(rows, entry))
        except (OSError, ValueError, KeyError, TypeError, AnalysisError) as exc:
            omitted.append(str(entry.get('filename', 'signal')) + ': ' + str(exc))
    files = {}
    failure_stage = data.get('error', {}).get('stage', '') if data.get('error') else ''
    diagnostic_logs = ['logs/spectre.log']
    if re.fullmatch(r'(?:spectre|export|capture|probe|netlist|build)(?:_[a-z0-9]+)?', failure_stage):
        diagnostic_logs.append('logs/' + failure_stage + '.log')
    for name in dict.fromkeys(['input.scs', 'models.scs', 'netlist_checks.json', 'image_validation.json',
                              'capture.json', 'worker_result.json', *diagnostic_logs]):
        if name in artifacts:
            try:
                files[name] = text_file(name)
            except (OSError, ValueError) as exc:
                omitted.append(name + ': ' + str(exc))
    # Prefer complete numerical summaries; drop display samples before omitting curves.
    core['files'] = files
    core['curves'] = sources
    encode = lambda: json.dumps(core, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if len(encode()) > MAX_CONTEXT:
        for series in sources:
            series.pop('sample_rows', None)
        omitted.append('为控制模型上下文长度，已省略曲线抽样点；保留原始数据统计。')
    while sources and len(encode()) > MAX_CONTEXT:
        removed = sources.pop()
        omitted.append('上下文长度限制: ' + removed['filename'])
    if len(encode()) > MAX_CONTEXT:
        # Very large user descriptions or metrics must not silently exhaust provider limits.
        for key in ('task', 'metrics', 'files', 'stages'):
            value = json.dumps(core[key], ensure_ascii=False)
            if len(value) > 12000:
                core[key] = {'excerpt': value[:12000], 'truncated': True}
                omitted.append(key + ': 超长内容仅保留前12000字')
    core['omitted'] = omitted[:100]
    return {'run_id': record.run_id, 'context': encode(), 'files_read': list(dict.fromkeys(read)),
            'series_count': len(sources), 'omitted': omitted, 'sampled': any(s.get('rows_sampled') for s in sources)}
