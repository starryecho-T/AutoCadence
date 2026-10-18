"""Bounded, deterministic study plans. Study data never contains executable code."""
from __future__ import annotations
import copy
import itertools
import math


SWEEP_FIELDS = {
    'voltage_source': {'dc'}, 'current_source': {'dc'},
    'resistor': {'resistance_ohm'}, 'capacitor': {'capacitance_f'},
    'inductor': {'inductance_h'}, 'bjt': {'area'}, 'pmos': {'width_m', 'length_m'},
    **{k: {'gain'} for k in ('vccs', 'vcvs', 'cccs', 'ccvs')},
}


def plain_task(task):
    data = task.model_dump() if hasattr(task, 'model_dump') else copy.deepcopy(task)
    return {**data, 'parameter_sweeps': [], 'two_port': None, 'comparisons': [], 'bjt_transfer': None}


def sweep_variants(task):
    data = task.model_dump() if hasattr(task, 'model_dump') else task
    axes = data.get('parameter_sweeps', [])
    if not axes:
        return []
    output = []
    for i, values in enumerate(itertools.product(*(a['values'] for a in axes))):
        variant, parameters = plain_task(data), {}
        for axis, value in zip(axes, values):
            part = next(c for c in variant['components'] if c['id'] == axis['component'])
            part[axis['parameter']] = value
            parameters[axis['component'] + '.' + axis['parameter']] = value
        output.append((f's{i:03}', parameters, variant))
    return output


def validate_studies(task):
    parts = {c.id: c for c in task.components}
    keys = set()
    for axis in task.parameter_sweeps:
        part = parts.get(axis.component)
        key = (axis.component, axis.parameter)
        if part is None or axis.parameter not in SWEEP_FIELDS.get(part.type, set()):
            raise ValueError('扫描参数与元件不兼容')
        if key in keys or len(set(axis.values)) != len(axis.values):
            raise ValueError('扫描轴或扫描值重复')
        keys.add(key)
        if axis.parameter == 'dc' and part.waveform is not None:
            raise ValueError('DC 参数扫描要求使用固定直流源')
        if axis.parameter == 'dc' and any(a.type == 'dc' and a.source == axis.component for a in task.analyses):
            raise ValueError('外层参数扫描不能覆盖内层 DC 扫描的同一电源')
    if math.prod(len(a.values) for a in task.parameter_sweeps) > 20:
        raise ValueError('参数组合最多 20 组')
    from .circuit_models import CircuitTask
    for _, _, variant in sweep_variants(task):
        if task.bjt_transfer:
            variant['bjt_transfer'] = task.bjt_transfer.model_dump()
        CircuitTask.model_validate(variant)  # Recheck bounds and voltage constraints at every point.
    ids = {'base'} | {x[0] for x in sweep_variants(task)}
    signal_ids = {s.id for s in task.signals}
    comparison_ids = [c.id.lower() for c in task.comparisons]
    if len(set(comparison_ids)) != len(comparison_ids):
        raise ValueError('比较编号重复')
    for c in task.comparisons:
        if c.case not in ids or c.reference_case not in ids or c.signal not in signal_ids or c.reference_signal not in signal_ids or c.analysis not in {a.type for a in task.analyses}:
            raise ValueError('比较引用了不存在的扫描组、信号或分析')
        first = next(s for s in task.signals if s.id == c.signal)
        second = next(s for s in task.signals if s.id == c.reference_signal)
        from .circuit_compiler import signal_unit
        if signal_unit(first.model_dump()) != signal_unit(second.model_dump()):
            raise ValueError('比较信号的单位必须一致')
    if task.two_port:
        tp = task.two_port
        if task.parameter_sweeps:
            raise ValueError('二端口提取请单独运行；不与外层参数扫描组合')
        ac = next((a for a in task.analyses if a.type == 'ac'), None)
        if ac is None or not ac.start_hz <= tp.reference_hz <= ac.stop_hz:
            raise ValueError('二端口提取需要 AC 分析及范围内的参考频率')
        from .circuits import normalize
        normalized = {c['id']: c for c in normalize(task)['components']}
        ports = [parts.get(tp.port1_source), parts.get(tp.port2_source)]
        if tp.port1_source == tp.port2_source or any(p is None or p.type != 'voltage_source' or p.waveform is not None for p in ports):
            raise ValueError('两个端口必须引用不同的固定直流电压源（可保留偏置）')
        terminals = [normalized[p.id]['pins'] for p in ports]
        if any(p['p'] == p['n'] for p in terminals) or set(terminals[0].values()) == set(terminals[1].values()):
            raise ValueError('二端口测试源短接或端口重合')
    if task.bjt_transfer:
        if len(task.signals)>14:
            raise ValueError('BJT 自动转移分析需为两个内部观测量预留空间，用户信号最多 14 个')
        validate_transfer(task)
    # Bound aggregate exports as well as individual analysis point counts.
    count = 1 + len(sweep_variants(task)) + (3 if task.two_port else 0)
    points = sum(1 if a.type == 'op' else abs((a.stop-a.start)/a.step)+1 if a.type == 'dc' else math.log10(a.stop_hz/a.start_hz)*a.points_per_decade+2 if a.type == 'ac' else a.stop_s/a.max_step_s*2+100 for a in task.analyses)
    if count * points * (len(task.signals)+3) > 8_000_000:
        raise ValueError('研究任务总采样预算超限，请减少扫描组或采样点')


def validate_transfer(task):
    if any(a.type == 'ac' for a in task.analyses):
        raise ValueError('自动 BJT 转移分析请使用独立的 DC 任务；AC 小信号分析另行提交')
    from .circuits import normalize, device_models
    data = task.model_dump()
    cfg = data['bjt_transfer']
    parts = {c['id']: c for c in normalize(task)['components']}
    try:
        q, vin, vcc, rb, rc = [parts[cfg[k]] for k in ('transistor', 'input_source', 'supply_source', 'base_resistor', 'collector_resistor')]
        ok = (q['type'] == 'bjt' and device_models(data)[q['model']]['polarity'] == 'npn'
              and vin['type'] == vcc['type'] == 'voltage_source' and vin['waveform'] is None and vcc['waveform'] is None
              and rb['type'] == rc['type'] == 'resistor' and q['pins']['e'] == vin['pins']['n'] == vcc['pins']['n'] == '0'
              and set(rb['pins'].values()) == {vin['pins']['p'], q['pins']['b']}
              and set(rc['pins'].values()) == {vcc['pins']['p'], q['pins']['c']}
              and vcc['dc'] > cfg['ce_saturation_v']
              and any(a['type'] == 'dc' and a['source'] == vin['id'] for a in data['analyses']))
        # The piecewise theory only applies to the stated unloaded CE topology.
        used = {q['id'], vin['id'], vcc['id'], rb['id'], rc['id']}
        ok = ok and set(parts) == used
    except (KeyError, TypeError):
        ok = False
    if not ok:
        raise ValueError('BJT 分段理论比较要求接地发射极的五元件 NPN 共射电路、RB/RC 和输入源 DC 扫描')
    if any(s.id.startswith('BT_') for s in task.signals):
        raise ValueError('BT_ 信号前缀为自动 BJT 分析保留')


def study_jobs(task):
    """The first job is the confirmed circuit; further jobs are explicit test benches."""
    from .circuit_models import CircuitTask
    data = task.model_dump() if hasattr(task, 'model_dump') else copy.deepcopy(task)
    base = plain_task(data)
    if data.get('bjt_transfer'):
        cfg = data['bjt_transfer']
        q = next(c for c in data['components'] if c['id'] == cfg['transistor'])
        base['signals'] += [
            {'id': 'BT_output', 'type': 'voltage', 'p': q['pins']['c'], 'n': q['pins']['e']},
            {'id': 'BT_region', 'type': 'device_parameter', 'component': q['id'], 'parameter': 'region'},
        ]
    jobs = [{'id': 'base', 'role': 'baseline', 'parameters': {}, 'task': base}]
    for cid, parameters, variant in sweep_variants(data):
        if data.get('bjt_transfer'):
            variant['signals'] = copy.deepcopy(base['signals'])
        jobs.append({'id': cid, 'role': 'parameter_sweep', 'parameters': parameters, 'task': variant})
    if data.get('two_port'):
        tp = data['two_port']
        for cid, amplitudes in [('yp1', (1, 0)), ('yp2', (0, 1)), ('ypcheck', (1, .37))]:
            variant = plain_task(data)
            variant['analyses'] = [a for a in data['analyses'] if a['type'] == 'ac']
            variant['measurements'] = []
            variant['signals'] = [{'id': f'TP_I{i+1}', 'type': 'current', 'component': tp[f'port{i+1}_source'], 'terminal': 'p'} for i in range(2)]
            for c in variant['components']:
                if c['type'] in ('voltage_source', 'current_source'):
                    c['ac_magnitude'] = 0
                    c['ac_phase_deg'] = 0
                    for i in range(2):
                        if c['id'] == tp[f'port{i+1}_source']:
                            c['ac_magnitude'] = amplitudes[i]
                            c['ac_phase_deg'] = 37 if cid == 'ypcheck' and i == 1 else 0
            jobs.append({'id': cid, 'role': 'two_port_test', 'parameters': {}, 'task': variant})
    for job in jobs:
        job['task'] = CircuitTask.model_validate(job['task']).model_dump()
    return jobs


def equivalent_task(task, matrix):
    """Real, memoryless small-signal Y equivalent at the requested reference frequency."""
    from .circuit_models import CircuitTask
    sources = [{'id': f'VP{i+1}', 'type': 'voltage_source', 'pins': {'p': f'p{i+1}', 'n': '0'},
                'dc': 0, 'ac_magnitude': 1 if i == 0 else .37, 'ac_phase_deg': 0 if i == 0 else 37} for i in range(2)]
    parts = sources + [{'id': f'G{i+1}{j+1}', 'type': 'vccs', 'pins': {'p': f'p{i+1}', 'n': '0', 'cp': f'p{j+1}', 'cn': '0'}, 'gain': matrix[i][j].real} for i in range(2) for j in range(2)]
    return CircuitTask.model_validate({'title': task['title'][:100] + ' — Y 参数小信号等效', 'components': parts,
        'analyses': [a for a in task['analyses'] if a['type'] == 'ac'],
        'signals': [{'id': f'TP_I{i+1}', 'type': 'current', 'component': f'VP{i+1}'} for i in range(2)]}).model_dump()
