"""Topology normalization and deterministic Spectre/Cadence compilation."""
from __future__ import annotations

import json
import math
import re


def number(value):
    return format(value, '.15g')


def normalize(task):
    data = task.model_dump() if hasattr(task, 'model_dump') else task
    parent = {'0': '0'}

    def find(n):
        parent.setdefault(n, n)
        if parent[n] != n:
            parent[n] = find(parent[n])
        return parent[n]

    for c in data['components']:
        for n in c['pins'].values():
            find(n)
    if not any('0' in c['pins'].values() for c in data['components']):
        raise ValueError('电路缺少参考地节点 0')
    for c in data['components']:
        if c['type'] == 'wire':
            a, b = find(c['pins']['p']), find(c['pins']['n'])
            if a != b:
                a, b = sorted((a, b))
                parent[b] = a
    aliases = {n: find(n) for n in sorted(parent)}
    nodes = sorted(set(aliases.values()) - {'0'})
    # Simulator names are generated; user node names never become code.
    mapping = {'0': '0', **{n: f'n{i+1}' for i, n in enumerate(nodes)}}
    parts, warnings = [], []
    for c in data['components']:
        if c['type'] == 'wire':
            continue
        c = {**c, 'pins': {p: aliases[n] for p, n in c['pins'].items()}}
        if c['type'] == 'switch' and (c['pins']['p'] == c['pins']['n'] or c['pins']['cp'] == c['pins']['cn']):
            raise ValueError(f"{c['id']}: 开关通路或控制端被短接")
        if len(set(c['pins'].values())) == 1:
            if c['type'] == 'voltage_source' and (c['dc'] != 0 or c['waveform'] is not None or c['ac_magnitude'] > 0):
                raise ValueError(f"{c['id']}: 非零电压源被导线短接")
            raise ValueError(f"{c['id']}: 所有引脚被短接到同一节点")
        if c['type'] == 'ideal_opamp' and c['pins']['plus'] == c['pins']['minus']:
            raise ValueError(f"{c['id']}: 运放输入端直接短接导致输出缺少约束")
        parts.append(c)
    if not parts or not nodes:
        raise ValueError('电路必须包含非导线元件和非地节点')
    # Connectivity is a necessary condition, not a claim of a DC solution.
    graph = {n: set() for n in set(aliases.values())}
    for c in parts:
        pins = list(c['pins'].values())
        for n in pins:
            graph[n].update(pins)
    seen, pending = set(), ['0']
    while pending:
        n = pending.pop()
        if n not in seen:
            seen.add(n); pending.extend(graph[n] - seen)
    if set(graph) - seen:
        raise ValueError('存在与参考地完全隔离的网络: ' + ', '.join(sorted(set(graph)-seen)))
    # Exact constraint cycles from fixed ideal voltage sources (also parallel sources).
    constraints = {n: [] for n in graph}
    for c in parts:
        if c['type'] == 'voltage_source' and c['waveform'] is None:
            p, n = c['pins']['p'], c['pins']['n']
            constraints[p].append((n, -c['dc']))
            constraints[n].append((p, c['dc']))
    potentials = {}
    for start in constraints:
        if start in potentials:
            continue
        potentials[start] = 0; pending = [start]
        while pending:
            n = pending.pop()
            for other, delta in constraints[n]:
                expected = potentials[n] + delta
                if other in potentials and not math.isclose(potentials[other], expected, rel_tol=1e-10, abs_tol=1e-12):
                    raise ValueError('理想直流电压源约束互相矛盾')
                if other not in potentials:
                    potentials[other] = expected; pending.append(other)
    if any(c['type'] in ('diode','bjt','pmos','nmos') for c in parts) and any(a['type'] == 'ac' for a in data['analyses']):
        warnings.append('非线性器件的 AC 结果是直流工作点附近的小信号响应；不代表大信号瞬态等效。')
    if any(c['type'] in ('bjt','pmos','nmos') for c in parts):
        warnings.append('NMOS/PMOS 默认使用 CMN018 工艺模型（nch/pch），需在仿真服务器高级设置配置模型文件；如需教学近似可显式指定 generic_nmos/generic_pmos。实际工艺适用性请核对。')
    if any(c['type'] == 'ideal_opamp' for c in parts):
        warnings.append('理想运放无供电限幅、带宽和压摆率；需要外围反馈或初始条件使方程有确定解。')
        dc_graph = {n: set() for n in graph}
        for c in parts:
            if c['type'] in ('resistor', 'inductor'):
                p, n = c['pins']['p'], c['pins']['n']
                if p != '0' and n != '0':
                    dc_graph[p].add(n); dc_graph[n].add(p)
        for c in parts:
            if c['type'] != 'ideal_opamp':
                continue
            seen, pending = set(), [c['pins']['out']]
            while pending:
                n = pending.pop()
                if n not in seen:
                    seen.add(n); pending.extend(dc_graph[n] - seen)
            if c['pins']['minus'] not in seen:
                warnings.append(f"{c['id']}：未发现输出到反相端的直接或电阻/电感直流反馈路径。电容在直流开路，AC/DC 求解可能出现奇异矩阵；请核对反馈或专用初始条件。复杂有源反馈需另行确认。")
    for a in data['analyses']:
        if a['type'] == 'tran' and a['use_initial_conditions']:
            warnings.append('瞬态先求解电容/电感初始条件，再积分；初始条件通过有限 rforce 施加，请核对 t=0 实际值。')
        elif a['type'] == 'tran' and any(c.get('initial_voltage_v') is not None or c.get('initial_current_a') is not None for c in parts):
            warnings.append('瞬态未启用 use_initial_conditions，电容/电感初始值将忽略；连接列表可在 .tran 末尾添加 ic。')
    return {'components': parts, 'aliases': aliases, 'node_map': mapping, 'warnings': warnings}


def component_spec(c, normalized):
    """Return (symbol, terminal order, symbol parameters, Spectre master, parameters)."""
    kind = c['type']
    if kind == 'resistor':
        return 'res', ['PLUS', 'MINUS'], {'r': number(c['resistance_ohm'])}, 'resistor', {'r': c['resistance_ohm']}
    if kind in ('capacitor', 'inductor'):
        cap = kind == 'capacitor'
        key, value = ('c', c['capacitance_f']) if cap else ('l', c['inductance_h'])
        params = {key: value}
        initial = c['initial_voltage_v'] if cap else c['initial_current_a']
        if initial is not None:
            params['ic'] = initial
        return ('cap' if cap else 'ind'), ['PLUS', 'MINUS'], {k: number(v) for k, v in params.items()}, kind, params
    if kind == 'switch':
        values = {'vt1': c['threshold_low_v'], 'vt2': c['threshold_high_v'],
                  'ropen': c['open_resistance_ohm'], 'rclosed': c['closed_resistance_ohm']}
        properties = {key: number(value) for key, value in values.items()}
        properties['ro'] = properties.pop('ropen')
        properties['rc'] = properties.pop('rclosed')
        return 'switch', ['N+', 'N-', 'NC+', 'NC-'], properties, 'relay', values
    if kind in ('diode', 'bjt', 'pmos', 'nmos'):
        selected = normalized['models'][c['model']]
        model = selected['name'] if selected.get('type') == 'cmn018' else 'dm' + str(normalized['model_ids'].index(c['model']))
        if kind == 'diode':
            return 'diode', ['PLUS', 'MINUS'], {'model': model}, model, {}
        if kind == 'bjt':
            polarity = ('pnp' if selected['name'].startswith('pnp') else 'npn') if selected.get('type') == 'cmn018' else selected['polarity']
            return polarity, ['C','B','E'], {'model':model, 'area':number(c['area'])}, model, {'area':c['area']}
        params = {'w':c['width_m'], 'l':c['length_m'], 'm':c['multiplicity']}
        return kind+'4', ['D','G','S','B'], {'model':model, **{k:number(v) for k,v in params.items()}}, model, params
    if kind in ('vccs','vcvs','cccs','ccvs'):
        prop, param = {'vccs':('ggain','gm'),'vcvs':('egain','gain'),'cccs':('fgain','gain'),'ccvs':('hgain','rm')}[kind]
        props, params = {prop:number(c['gain'])}, {param:c['gain']}
        terminals = ['PLUS','MINUS','NC+','NC-'] if kind in ('vccs','vcvs') else ['PLUS','MINUS']
        if kind in ('cccs','ccvs'):
            props['vref'] = params['probe'] = normalized['instance_map'][c['control_source']]
        return kind, terminals, props, kind, params
    if kind == 'ideal_opamp':
        return 'ideal_opamp', ['plus', 'minus', 'out'], {}, 'ideal_opamp', {}
    params = {'dc': c['dc'], 'mag': c['ac_magnitude'], 'phase': c['ac_phase_deg'], 'type': 'dc'}
    symbol = {('vdc' if kind == 'voltage_source' else 'idc'): number(c['dc']), 'acm': number(c['ac_magnitude']), 'acp': number(c['ac_phase_deg']), 'srcType': 'dc'}
    w = c['waveform']
    if w:
        params['type'] = symbol['srcType'] = w['type']
        if w['type'] == 'sine':
            params.update(sinedc=w['offset'], ampl=w['amplitude'], freq=w['frequency_hz'], sinephase=w['phase_deg'], delay=w['delay_s'])
        elif w['type'] == 'pulse':
            params.update(val0=w['low'], val1=w['high'], period=w['period_s'], width=w['width_s'], rise=w['rise_s'], fall=w['fall_s'], delay=w['delay_s'])
        else:
            params['wave'] = [x for pair in w['points'] for x in pair]
        # vsource/isource CDF names are resolved from tested analogLib parameters.
        rename = {'sinedc': 'sinedc', 'ampl': ('va' if kind == 'voltage_source' else 'ia'), 'freq': 'freq', 'sinephase': 'sinephase', 'delay': 'td', 'val0': 'val0', 'val1': 'val1', 'period': 'per', 'width': 'pw', 'rise': 'tr', 'fall': 'tf'}
        for k, v in params.items():
            if k in rename:
                symbol[rename[k]] = number(v)
        if 'wave' in params:
            symbol['pwlEntryMethod'] = 'Time-Value Pairs'
            symbol['tvpairs'] = len(w['points'])
            for i, (t, v) in enumerate(w['points'], 1):
                symbol[f't{i}'] = number(t)
                symbol[f"{'v' if kind == 'voltage_source' else 'i'}{i}"] = number(v)
    return ('vsource' if kind == 'voltage_source' else 'isource'), ['PLUS', 'MINUS'], symbol, ('vsource' if kind == 'voltage_source' else 'isource'), params


def device_models(data):
    from .circuit_models import CMN018Model, DiodeModel, BJTModel, MOS1Model
    return {'generic_diode':DiodeModel(id='generic_diode').model_dump(),
            'generic_npn':BJTModel(id='generic_npn',type='bjt').model_dump(),
            'generic_pnp':BJTModel(id='generic_pnp',type='bjt',polarity='pnp').model_dump(),
            'generic_pmos':MOS1Model(id='generic_pmos',type='mos1').model_dump(),
            'generic_nmos':MOS1Model(id='generic_nmos',type='mos1',polarity='n',threshold_voltage_v=.7).model_dump(),
            'nch':CMN018Model(id='nch',type='cmn018',name='nch').model_dump(),
            'pch':CMN018Model(id='pch',type='cmn018',name='pch').model_dump(),
            **{m['id']:m for m in data['models']}}


def compile_task(task):
    data = task.model_dump() if hasattr(task, 'model_dump') else task
    n = normalize(data)
    n['models'] = device_models(data)
    n['model_ids'] = sorted({'generic_diode'} | {c['model'] for c in n['components'] if c['type'] in ('diode','bjt','pmos','nmos')})
    n['instance_map'] = {c['id']: f'x{i+1}' for i, c in enumerate(n['components'])}
    devices = []
    for c in n['components']:
        symbol, terminals, props, master, params = component_spec(c, n)
        pin_order = {'diode':['a','k'], 'bjt':['c','b','e'], 'pmos':['d','g','s','b'], 'nmos':['d','g','s','b'],
                     'ideal_opamp':['plus','minus','out'], 'vccs':['p','n','cp','cn'], 'vcvs':['p','n','cp','cn'],
                     'switch':['p','n','cp','cn']}.get(c['type'], ['p','n'])
        device_nodes = [n['node_map'][c['pins'][p]] for p in pin_order]
        if c['type'] == 'bjt':
            device_nodes.append('0')  # analogLib explicitly grounds the optional substrate.
        devices.append({'id': c['id'], 'instance': n['instance_map'][c['id']], 'symbol': symbol,
                        'terminals': terminals, 'nodes': device_nodes,
                        'properties': props, 'master': master, 'parameters': params, 'type': c['type']})
    models = []
    by_id = n['models']
    from .cmn018 import CMN018_MODELS, MISMATCH_FLAGS, MODEL_PLACEHOLDER, section
    pdk_sections = sorted({section(data['pdk_corner'], by_id[name]['name']) for name in n['model_ids']
                           if by_id[name].get('type') == 'cmn018'})
    if pdk_sections:
        models.append('parOpt options redefinedparams=ignore')
    models.extend(f'include "{MODEL_PLACEHOLDER}" section={name}' for name in pdk_sections)
    flags = {MISMATCH_FLAGS.get(CMN018_MODELS[by_id[name]['name']][1]) for name in n['model_ids']
             if by_id[name].get('type') == 'cmn018'}
    models.extend(f'parameters {flag}=0' for flag in sorted(flags - {None}))
    for i, name in enumerate(n['model_ids']):
        m = by_id[name]
        kind = m.get('type','diode')
        if kind == 'cmn018':
            continue
        if kind == 'diode':
            values = {'is': m['saturation_current_a'], 'n': m['emission_coefficient'], 'rs': m['series_resistance_ohm'], 'cj': m['junction_capacitance_f'], 'tt': m['transit_time_s']}
            if m['breakdown_voltage_v'] is not None:
                values['bv'] = m['breakdown_voltage_v']
        elif kind == 'bjt':
            values = {'type':m['polarity'], **{short:m[long] for short,long in {
                'is':'saturation_current_a','bf':'forward_beta','br':'reverse_beta','va':'forward_early_voltage_v',
                'nf':'forward_emission_coefficient','nr':'reverse_emission_coefficient','rb':'base_resistance_ohm',
                'rc':'collector_resistance_ohm','re':'emitter_resistance_ohm','cje':'be_capacitance_f',
                'cjc':'bc_capacitance_f','tf':'forward_transit_time_s'}.items()}}
        else:
            values = {'type':m['polarity'], **{short:m[long] for short,long in {'vto':'threshold_voltage_v','kp':'transconductance_a_v2',
                'lambda':'channel_length_modulation_per_v','gamma':'body_effect_sqrt_v','phi':'surface_potential_v',
                'cgso':'gate_source_overlap_f_m','cgdo':'gate_drain_overlap_f_m'}.items()}}
        models.append(f"model dm{i} {kind} " + ' '.join(f'{k}={v if isinstance(v,str) else number(v)}' for k, v in values.items()))
    return {**n, 'devices': devices, 'model_text': '\n'.join(models), 'pdk_sections':pdk_sections}


def render_netlist(task, compiled):
    """Independent expected netlist, also useful for model verification."""
    lines = ['simulator lang=spectre', compiled['model_text']]
    if any(c['type'] == 'ideal_opamp' for c in compiled['devices']):
        lines.append('ahdl_include "ideal_opamp.va"')
    for d in compiled['devices']:
        params = []
        for k, v in d['parameters'].items():
            value = '[' + ' '.join(number(x) for x in v) + ']' if isinstance(v, list) else v if isinstance(v, str) else number(v)
            params.append(f'{k}={value}')
        lines.append(f"{d['instance']} ({' '.join(d['nodes'])}) {d['master']} " + ' '.join(params))
    lines += analysis_lines(task, compiled)
    return '\n'.join(lines) + '\n'


def analysis_lines(task, compiled):
    data = task.model_dump() if hasattr(task, 'model_dump') else task
    lines = [f"simulatorOptions options temp={number(data['temperature_c'])} reltol=1e-5 vabstol=1e-8 iabstol=1e-12", 'saveOptions options save=allpub currents=all']
    for s in data['signals']:
        if s['type'] == 'device_parameter':
            lines.append(f"save {compiled['instance_map'][s['component']]}:{s['parameter']}")
    transient = next((a for a in data['analyses'] if a['type'] == 'tran'), None)
    if transient and transient['use_initial_conditions']:
        lines[0] += ' rforce=' + number(transient['initial_condition_resistance_ohm'])
    for a in data['analyses']:
        kind = a['type']
        if kind == 'op':
            lines.append('dcOp dc')
        elif kind == 'dc':
            lines.append(f"dc dc dev={compiled['instance_map'][a['source']]} param=dc start={number(a['start'])} stop={number(a['stop'])} step={number(a['step'])}")
        elif kind == 'ac':
            lines.append(f"ac ac start={number(a['start_hz'])} stop={number(a['stop_hz'])} dec={a['points_per_decade']}")
        else:
            # skipdc=yes ignores device IC parameters in Spectre. Keep the
            # consistent initialization solve, including floating capacitors.
            lines.append(f"tran tran stop={number(a['stop_s'])} maxstep={number(a['max_step_s'])} errpreset=conservative ic={'dev' if a['use_initial_conditions'] else 'dc'}")
    return lines


IDEAL_OPAMP = '''`include "disciplines.vams"
module ideal_opamp(plus, minus, out);
inout plus, minus, out;
electrical plus, minus, out;
analog V(out): V(plus, minus) == 0;
endmodule
'''


def preview(task):
    compiled = compile_task(task)
    return {'task': task.model_dump(), 'normalized': {k: compiled[k] for k in ('components', 'aliases', 'node_map')},
            'warnings': compiled['warnings'], 'netlist': render_netlist(task, compiled),
            'requires_confirmation': True}
