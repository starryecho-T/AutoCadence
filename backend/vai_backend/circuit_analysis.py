"""Validate real exported waveforms and calculate explicitly requested metrics."""
from __future__ import annotations
import base64
import cmath
import html
import json
import math
from pathlib import Path
from .circuit_models import CircuitTask
from .circuits import compile_task
from .analysis import AnalysisError


def fail(message):
    raise AnalysisError('CIRCUIT_DATA_INVALID', message)


def read_wave(path, complex_data):
    rows = []
    with path.open(encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                values = [float(x) for x in line.split()]
            except ValueError:
                fail(f'{path.name}: invalid numeric data')
            if len(values) != (3 if complex_data else 2) or not all(math.isfinite(x) for x in values):
                fail(f'{path.name}: incomplete or non-finite data')
            if rows and (values[0] == rows[-1][0] or len(rows) > 1 and (values[0]-rows[-1][0])*(rows[-1][0]-rows[-2][0]) <= 0):
                fail(f'{path.name}: sample axis is not strictly monotonic')
            rows.append(values)
            if len(rows) > 400000:
                fail('Actual sample count exceeds resource limit')
    if not rows:
        fail(f'{path.name}: empty waveform')
    return rows


def at_value(rows, x):
    if rows[0][0] > rows[-1][0]:
        rows = rows[::-1]
    if x < rows[0][0] or x > rows[-1][0]:
        fail('Measurement coordinate lies outside simulated range')
    for a, b in zip(rows, rows[1:]):
        if a[0] <= x <= b[0]:
            ratio = (x-a[0])/(b[0]-a[0])
            return a[1] + ratio*(b[1]-a[1])
    return rows[-1][1]


def evaluate(rows, m):
    representation = m['representation']
    values = []
    for row in rows:
        z = complex(row[1], row[2] if len(row) == 3 else 0)
        y = {'real': z.real, 'imag': z.imag, 'magnitude': abs(z), 'phase_deg': math.degrees(cmath.phase(z))}[representation]
        values.append((row[0], y))
    ys = [v[1] for v in values]
    operation = m['operation']
    if operation == 'at':
        if m['analysis'] == 'ac':
            z = complex(at_value([(r[0],r[1]) for r in rows],m['at']),at_value([(r[0],r[2]) for r in rows],m['at']))
            return {'real':z.real,'imag':z.imag,'magnitude':abs(z),'phase_deg':math.degrees(cmath.phase(z))}[representation]
        return at_value(values, m['at'])
    if operation == 'final':
        return ys[-1]
    if operation == 'min':
        return min(ys)
    if operation == 'max':
        return max(ys)
    if operation == 'peak_to_peak':
        return max(ys)-min(ys)
    if m['analysis'] == 'tran' and len(values) > 1:
        # Integrate linearly interpolated samples; exact integral for each segment.
        if operation == 'rms':
            area = sum((b[0]-a[0])*(a[1]**2+a[1]*b[1]+b[1]**2)/3 for a, b in zip(values, values[1:]))
        else:
            area = sum((b[0]-a[0])*(a[1]+b[1])/2 for a, b in zip(values, values[1:]))
        mean = area/(values[-1][0]-values[0][0])
    else:
        mean = sum(y*y if operation == 'rms' else y for y in ys)/len(ys)
    return math.sqrt(max(0, mean)) if operation == 'rms' else mean


def downsample(rows, limit=1000):
    if len(rows) <= limit:
        return rows
    selected = {0, len(rows)-1}
    width = max(1, math.ceil(len(rows)/(limit//2)))
    for start in range(0, len(rows), width):
        indexes = range(start, min(start+width, len(rows)))
        def y(i):
            r = rows[i]
            return abs(complex(r[1], r[2])) if len(r) == 3 else r[1]
        selected.add(min(indexes, key=y)); selected.add(max(indexes, key=y))
    return [rows[i] for i in sorted(selected)]


def analyze(task, evidence_dir):
    spec = CircuitTask.model_validate(task).model_dump()
    root = Path(evidence_dir)
    manifest = json.loads((root/'signals.json').read_text(encoding='utf-8'))
    expected = {(a['type'], s['id']) for a in spec['analyses'] for s in spec['signals']}
    if {(x['analysis'], x['signal']) for x in manifest} != expected or len(manifest) != len(expected):
        fail('Signal manifest does not match requested circuit')
    waves, summaries, plot, checks = {}, {}, [], []
    axes = {}
    for entry in manifest:
        filename = entry['filename']
        if Path(filename).name != filename or not filename.endswith('.txt'):
            fail('Invalid waveform artifact path')
        kind, sid = entry['analysis'], entry['signal']
        rows = read_wave(root/filename, kind == 'ac')
        a = next(a for a in spec['analyses'] if a['type'] == kind)
        if kind == 'op':
            if len(rows) != 1:
                fail('Operating point must have one value')
        else:
            start = 0 if kind == 'tran' else a['start_hz'] if kind == 'ac' else a['start']
            stop = a['stop_s'] if kind == 'tran' else a['stop_hz'] if kind == 'ac' else a['stop']
            if len(rows) < 2 or not math.isclose(rows[0][0], start, rel_tol=1e-6, abs_tol=1e-15) or not math.isclose(rows[-1][0], stop, rel_tol=1e-6, abs_tol=1e-15):
                fail(f'{kind}/{sid}: exported range is incomplete')
        axis = [r[0] for r in rows]
        if kind in axes and axes[kind] != axis:
            fail(f'{kind}: signal sample axes differ')
        axes[kind] = axis
        waves[(kind, sid)] = rows
        summaries[f'{kind}.{sid}'] = {'samples': len(rows), 'unit': entry['unit'], 'final_real': rows[-1][1], 'artifact': filename}
        plot.append({**entry, 'rows': downsample(rows), 'original_samples': len(rows)})
        checks.append({'name': f'{kind}.{sid}', 'status': 'PASS', 'actual': len(rows), 'expected': 'finite, aligned data covering requested range'})
    measurements = []
    for m in spec['measurements']:
        result = evaluate(waves[(m['analysis'], m['signal'])], m)
        bounded = m['minimum'] is not None or m['maximum'] is not None
        passed = (m['minimum'] is None or result >= m['minimum']) and (m['maximum'] is None or result <= m['maximum'])
        measurements.append({**m, 'value': result, 'status': ('PASS' if passed else 'FAIL') if bounded else 'MEASURED'})
    requested = [m for m in measurements if m['status'] != 'MEASURED']
    status = 'NOT_SPECIFIED' if not requested else 'PASS' if all(m['status'] == 'PASS' for m in requested) else 'FAIL'
    (root/'waveforms.json').write_text(json.dumps({'source': 'Spectre numeric exports from this run', 'series': plot}, allow_nan=False), encoding='utf-8')
    return {'execution_status': 'succeeded', 'validation_status': 'PASS', 'requirements_status': status,
            'component_count': len(compile_task(task)['devices']), 'checks': checks,
            'signals': summaries, 'measurements': measurements,
            'waveform_source': 'Spectre exports; plot data is downsampled, measurements use all samples.',
            'limitations': compile_task(task)['warnings'] + ['通用校验确认执行与数据完整性；未指定的题目指标不会自动判定达标。']}


def generate_report(task, metrics, evidence_dir, run_id, warnings):
    root = Path(evidence_dir)
    esc = lambda x: html.escape(str(x), quote=True)
    title = task['title']
    content = [f'<h1>{esc(title)}</h1>', f'<p>运行编号：{esc(run_id)}<br>执行：succeeded；数据校验：{metrics["validation_status"]}；目标指标：{metrics["requirements_status"]}</p>']
    md = [f'# {title}', '', f'运行编号：{run_id}', f'执行：succeeded；数据校验：{metrics["validation_status"]}；目标指标：{metrics["requirements_status"]}', '']
    content.append('<table><tr><th>测量</th><th>结果</th><th>判定</th></tr>')
    for m in metrics['measurements']:
        content.append(f'<tr><td>{esc(m["id"])}</td><td>{esc(m["value"])}</td><td>{m["status"]}</td></tr>')
        md.append(f'- {m["id"]}: {m["value"]} ({m["status"]})')
    content.append('</table>')
    for name in ('schematic_window.png', 'waveform_window.png'):
        data = (root/name).read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            fail('Missing real screenshot: ' + name)
        content.append(f'<figure><img alt="{name}" src="data:image/png;base64,{base64.b64encode(data).decode()}"><figcaption>{name}</figcaption></figure>')
        md.append(f'![{name}]({name})')
    for label, value in [('输入电路', task), ('数值结果', metrics)]:
        raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        content.append(f'<h2>{label}</h2><pre>{esc(raw)}</pre>')
        md += ['', label, '', '```json', raw.replace('```', '\\u0060\\u0060\\u0060'), '```']
    notes = warnings + metrics['limitations']
    content += ['<ul>' + ''.join(f'<li>{esc(n)}</li>' for n in notes) + '</ul>']
    (root/'report.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font:15px/1.6 system-ui;max-width:1100px;margin:30px auto;padding:20px}img{max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}td,th{border:1px solid #ddd;padding:8px}table{border-collapse:collapse}</style>'+''.join(content), encoding='utf-8')
    (root/'report.md').write_text('\n'.join(md+['']+['- '+n for n in notes]), encoding='utf-8')
