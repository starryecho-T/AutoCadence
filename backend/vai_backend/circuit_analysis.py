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
    from .circuit_studies import study_jobs
    from .study_analysis import compare_curves, extract_two_port, bjt_transfer_analysis, update_requirements
    jobs = study_jobs(spec)
    by_case = {j['id']:j for j in jobs}
    from .circuit_compiler import export_program
    expected_entries = {}
    for job in jobs:
        _, entries = export_program(job['task'],compile_task(job['task']),job['id'])
        expected_entries.update({(job['id'],e['analysis'],e['signal']):e for e in entries})
    manifest = json.loads((root/'signals.json').read_text(encoding='utf-8'))
    expected = {(j['id'],a['type'], s['id']) for j in jobs for a in j['task']['analyses'] for s in j['task']['signals']}
    if {(x.get('case','base'),x['analysis'], x['signal']) for x in manifest} != expected or len(manifest) != len(expected):
        fail('Signal manifest does not match requested circuit')
    waves, summaries, plot, checks = {}, {}, [], []
    axes = {}
    for entry in manifest:
        filename = entry['filename']
        if Path(filename).name != filename or not filename.endswith('.txt'):
            fail('Invalid waveform artifact path')
        kind, sid, cid = entry['analysis'], entry['signal'], entry.get('case','base')
        expected_entry = expected_entries[(cid,kind,sid)]
        if entry.get('unit') != expected_entry['unit'] or filename != expected_entry['filename']:
            fail('Signal manifest filename or unit differs from the study plan')
        rows = read_wave(root/filename, kind == 'ac')
        a = next(a for a in by_case[cid]['task']['analyses'] if a['type'] == kind)
        if kind == 'op':
            if len(rows) != 1:
                fail('Operating point must have one value')
        else:
            start = 0 if kind == 'tran' else a['start_hz'] if kind == 'ac' else a['start']
            stop = a['stop_s'] if kind == 'tran' else a['stop_hz'] if kind == 'ac' else a['stop']
            if len(rows) < 2 or not math.isclose(rows[0][0], start, rel_tol=1e-6, abs_tol=1e-15) or not math.isclose(rows[-1][0], stop, rel_tol=1e-6, abs_tol=1e-15):
                fail(f'{kind}/{sid}: exported range is incomplete')
        axis = [r[0] for r in rows]
        if (cid,kind) in axes and axes[(cid,kind)] != axis:
            fail(f'{kind}: signal sample axes differ')
        axes[(cid,kind)] = axis
        waves[(cid,kind, sid)] = rows
        key = ('' if cid == 'base' else cid+'.')+f'{kind}.{sid}'
        summaries[key] = {'samples': len(rows), 'unit': entry['unit'], 'final_real': rows[-1][1], 'artifact': filename}
        plot.append({**entry, 'case':cid, 'parameters':by_case[cid]['parameters'], 'role':by_case[cid]['role'], 'rows': downsample(rows), 'original_samples': len(rows)})
        checks.append({'name': key, 'status': 'PASS', 'actual': len(rows), 'expected': 'finite, aligned data covering requested range'})
    measurements = []
    for j in jobs:
        if j['role'] not in ('baseline','parameter_sweep'):
            continue
        for m in spec['measurements']:
            result = evaluate(waves[(j['id'],m['analysis'], m['signal'])], m)
            bounded = m['minimum'] is not None or m['maximum'] is not None
            passed = (m['minimum'] is None or result >= m['minimum']) and (m['maximum'] is None or result <= m['maximum'])
            measurements.append({**m, 'case':j['id'], 'value': result, 'status': ('PASS' if passed else 'FAIL') if bounded else 'MEASURED'})
    comparisons = [{**c, **compare_curves(waves[(c['case'],c['analysis'],c['signal'])],waves[(c['reference_case'],c['analysis'],c['reference_signal'])],c['relative_tolerance'],c['absolute_tolerance'],c['scale'])} for c in spec['comparisons']]
    extra = {}
    if spec['two_port']:
        extra['two_port'] = extract_two_port(spec,waves,root)
    if spec['bjt_transfer']:
        extra['bjt_transfer'] = bjt_transfer_analysis(spec,jobs,waves,plot)
    if comparisons:
        (root/'comparison.json').write_text(json.dumps(comparisons,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'waveforms.json').write_text(json.dumps({'source': 'Spectre numeric exports from this run', 'series': plot}, allow_nan=False), encoding='utf-8')
    result = {'execution_status': 'succeeded', 'validation_status': 'PASS',
            'component_count': len(compile_task(task)['devices']), 'checks': checks,
            'signals': summaries, 'measurements': measurements, 'comparisons':comparisons,
            'cases':[{k:j[k] for k in ('id','role','parameters')} for j in jobs], **extra,
            'waveform_source': 'Spectre exports; plot data is downsampled, measurements use all samples.',
            'limitations': compile_task(task)['warnings'] + ['通用校验确认执行与数据完整性；未指定的题目指标不会自动判定达标。']}
    update_requirements(result)
    return result


def generate_report(task, metrics, evidence_dir, run_id, warnings):
    root = Path(evidence_dir)
    esc = lambda x: html.escape(str(x), quote=True)
    from .circuit_titles import circuit_title
    title = circuit_title(task)
    content = [f'<h1>{esc(title)}</h1>', f'<p>运行编号：{esc(run_id)}<br>执行：succeeded；数据校验：{metrics["validation_status"]}；目标指标：{metrics["requirements_status"]}</p>']
    md = [f'# {title}', '', f'运行编号：{run_id}', f'执行：succeeded；数据校验：{metrics["validation_status"]}；目标指标：{metrics["requirements_status"]}', '']
    content.append('<table><tr><th>测量</th><th>结果</th><th>判定</th></tr>')
    for m in metrics['measurements']:
        content.append(f'<tr><td>{esc(m["id"])}</td><td>{esc(m["value"])}</td><td>{m["status"]}</td></tr>')
        md.append(f'- {m["id"]}: {m["value"]} ({m["status"]})')
    content.append('</table>')
    tp = metrics.get('two_port')
    if tp:
        content.append(f'<h2>二端口 Y 参数</h2><p>参考频率 {esc(tp["reference_hz"])} Hz；单位 S；电流正方向为流入被测网络。保持原 DC 偏置的 AC 小信号结果。</p><table><tr><th></th><th>V1</th><th>V2</th></tr>')
        md += ['', '## 二端口 Y 参数', '', f'参考频率 {tp["reference_hz"]} Hz；单位 S；I = YV，电流流入网络。', '', '| | V1 | V2 |', '|---|---|---|']
        for i,row in enumerate(tp['reference_matrix']):
            values = [f'{z["real"]:.9g} {z["imag"]:+.9g}j' for z in row]
            content.append(f'<tr><th>I{i+1}</th>'+''.join(f'<td>{esc(v)}</td>' for v in values)+'</tr>')
            md.append(f'| I{i+1} | '+ ' | '.join(values)+' |')
        content.append('</table>')
        eq = tp.get('equivalence')
        if eq:
            content.append(f'<p>独立等效电路验证：{esc(eq["status"])}。{esc(eq.get("reason",eq.get("scope","")))}</p>')
            md += ['', f'独立等效电路验证：{eq["status"]}。{eq.get("reason",eq.get("scope",""))}']
    for item in metrics.get('bjt_transfer',[]):
        text = f'{item["case"]}：分段理论与仿真最大误差 {item["max_absolute_error_v"]:.7g} V，RMSE {item["rmse_v"]:.7g} V；理论饱和边界 {item["theory_saturation_boundary_v"]:.7g} V。'
        content.append('<h2>NPN 共射转移分析</h2><p>'+esc(text)+'</p><p>'+esc(item['scope'])+'</p>')
        md += ['', '## NPN 共射转移分析', '', text, item['scope']]
        for interval in item['regions']:
            label = f'{interval["region"]}: Vin {interval["start_v"]:.7g} ～ {interval["stop_v"]:.7g} V'
            content.append('<p>'+esc(label)+'</p>');md.append('- '+label)
    comparisons = metrics.get('comparisons',[]) + (tp.get('equivalence',{}).get('checks',[]) if tp else [])
    if comparisons:
        content.append('<h2>曲线比较</h2><table><tr><th>比较项</th><th>最大绝对误差</th><th>RMSE</th><th>容差比</th><th>判定</th></tr>')
        for c in comparisons:
            values = [c.get('id',c.get('signal','')),c['max_absolute_error'],c['rmse'],c['max_tolerance_ratio'],c['status']]
            content.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>')
            md.append('- '+': '.join(str(v) for v in values))
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
    (root/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>'+esc(title)+'</title><style>body{font:15px/1.6 system-ui;max-width:1100px;margin:30px auto;padding:20px}img{max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}td,th{border:1px solid #ddd;padding:8px}table{border-collapse:collapse}</style>'+''.join(content), encoding='utf-8')
    (root/'report.md').write_text('\n'.join(md+['']+['- '+n for n in notes]), encoding='utf-8')
