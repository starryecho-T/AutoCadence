"""Explicit connection-list input. Never infer an unspecified topology."""
import json
import re
from pydantic import ValidationError
from .circuit_models import CircuitTask
from .cmn018 import CMN018_MODELS


def value(raw):
    m = re.fullmatch(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(meg|[kKMmunpµμ]?)', raw)
    if not m:
        raise ValueError(f'无法识别数值 {raw}；请用 SI 数值或 k/u/n/p 等工程前缀')
    scales = {'': 1, 'k': 1e3, 'K': 1e3, 'M': 1e6, 'meg': 1e6, 'm': 1e-3, 'u': 1e-6, 'µ': 1e-6, 'μ': 1e-6, 'n': 1e-9, 'p': 1e-12}
    return float(m[1])*scales[m[2]]


def parse_circuit(text):
    text = text.strip()
    if text.startswith('{'):
        return CircuitTask.model_validate(json.loads(text))
    components, analyses, signals, sweeps, comparisons, models = [], [], [], [], [], []
    pdk_corner = 'tt'
    studies = {}
    for index, line in enumerate(text.splitlines(), 1):
        line = line.split(';', 1)[0].strip()
        if not line or line.startswith('*'):
            continue
        words = line.split()
        try:
            name, args = words[0], words[1:]
            if name.startswith('.'):
                command = name.lower()
                if command == '.op' and not args:
                    analyses.append({'type': 'op'})
                elif command == '.ac' and len(args) == 3:
                    analyses.append({'type': 'ac', 'start_hz': value(args[0]), 'stop_hz': value(args[1]), 'points_per_decade': int(args[2])})
                elif command == '.tran' and len(args) in (2, 3):
                    if len(args) == 3 and args[2].lower() != 'ic':
                        raise ValueError('瞬态的第三个参数只能是 ic（求解元件初始条件；不支持跳过初始化的 uic）')
                    analyses.append({'type': 'tran', 'stop_s': value(args[0]), 'max_step_s': value(args[1]), 'use_initial_conditions': len(args) == 3})
                elif command == '.dc' and len(args) == 4:
                    analyses.append({'type': 'dc', 'source': args[0], 'start': value(args[1]), 'stop': value(args[2]), 'step': value(args[3])})
                elif command == '.step' and len(args) >= 3:
                    sweeps.append({'component':args[0], 'parameter':args[1], 'values':[value(x) for x in args[2:]]})
                elif command == '.model' and len(args) == 3 and args[1].lower() == 'cmn018':
                    models.append({'id':args[0], 'type':'cmn018', 'name':args[2]})
                elif command == '.corner' and len(args) == 1:
                    pdk_corner = args[0].lower()
                elif command == '.twoport' and len(args) in (3,4):
                    if 'two_port' in studies or len(args) == 4 and args[3].lower() != 'extract_only':
                        raise ValueError('二端口指令只允许一次；可选末尾 extract_only 仅提取')
                    studies['two_port'] = {'port1_source':args[0], 'port2_source':args[1], 'reference_hz':value(args[2]), 'generate_equivalent':len(args)==3}
                elif command == '.transfer' and len(args) == 5:
                    if 'bjt_transfer' in studies:
                        raise ValueError('只允许一个 BJT 转移分析')
                    studies['bjt_transfer'] = dict(zip(('transistor','input_source','supply_source','base_resistor','collector_resistor'),args))
                elif command == '.compare' and len(args) == 8:
                    comparisons.append(dict(zip(('id','analysis','signal','reference_signal','case','reference_case'),args[:6]),relative_tolerance=value(args[6]),absolute_tolerance=value(args[7])))
                elif command == '.save' and args:
                    for token in args:
                        m = re.fullmatch(r'([VIPvip])\((\w+)(?:,(\w+))?\)', token)
                        if not m:
                            raise ValueError('测量写法为 V(node)、V(p,n)、I(component[,terminal]) 或 P(component,parameter)')
                        sid = f's{len(signals)+1}'
                        if m[1].lower() == 'p' and not m[3]:
                            raise ValueError('P 要求指定 region/gm 等参数')
                        signals.append({'id': sid, 'type': 'voltage', 'p': m[2], 'n': m[3] or '0'} if m[1].lower() == 'v' else
                            {'id':sid, 'type':'device_parameter','component':m[2],'parameter':m[3]} if m[1].lower() == 'p' else
                            {'id': sid, 'type': 'current', 'component': m[2], 'terminal':m[3]})
                else:
                    raise ValueError('未知指令或参数数量错误')
                continue
            kind = name[0].upper()
            if kind in 'RCL' and len(args) in (3, 4):
                part_type, parameter = {'R': ('resistor', 'resistance_ohm'), 'C': ('capacitor', 'capacitance_f'), 'L': ('inductor', 'inductance_h')}[kind]
                c = {'id': name, 'type': part_type, 'pins': {'p': args[0], 'n': args[1]}, parameter: value(args[2])}
                if len(args) == 4:
                    if kind == 'R' or not args[3].lower().startswith('ic='):
                        raise ValueError('只有电容/电感支持 ic=初始值')
                    c['initial_voltage_v' if kind == 'C' else 'initial_current_a'] = value(args[3][3:])
            elif kind == 'D' and len(args) in (2, 3):
                c = {'id': name, 'type': 'diode', 'pins': {'a': args[0], 'k': args[1]}, 'model': args[2] if len(args) == 3 else 'generic_diode'}
            elif kind == 'Q' and len(args) in (3,4):
                c = {'id':name,'type':'bjt','pins':dict(zip(('c','b','e'),args[:3])), 'model':args[3] if len(args)==4 else 'generic_npn'}
            elif kind == 'M' and len(args) >= 4:
                c = {'id':name,'pins':dict(zip(('d','g','s','b'),args[:4]))}
                tail = args[4:]
                model = 'pch'
                if tail and '=' not in tail[0]:
                    model = tail[0]; tail = tail[1:]
                if model in CMN018_MODELS:
                    c['type'] = CMN018_MODELS[model][0]
                elif model == 'generic_nmos' or 'nmos' in model.lower():
                    c['type'] = 'nmos'
                else:
                    c['type'] = 'pmos'
                c['model'] = model
                for arg in tail:
                    k, v = arg.split('=',1)
                    k = {'w':'width_m','l':'length_m','m':'multiplicity'}.get(k.lower())
                    if k is None or k in c:
                        raise ValueError('MOS 仅支持唯一的 w/l/m 参数')
                    c[k] = value(v)
            elif kind in 'GE' and len(args) == 5:
                c = {'id':name,'type':'vccs' if kind=='G' else 'vcvs','pins':dict(zip(('p','n','cp','cn'),args[:4])),'gain':value(args[4])}
            elif kind in 'FH' and len(args) == 4:
                c = {'id':name,'type':'cccs' if kind=='F' else 'ccvs','pins':dict(zip(('p','n'),args[:2])),'control_source':args[2],'gain':value(args[3])}
            elif kind in 'OU' and len(args) == 3:
                c = {'id': name, 'type': 'ideal_opamp', 'pins': dict(zip(('plus', 'minus', 'out'), args))}
            elif kind == 'W' and len(args) == 2:
                c = {'id': name, 'type': 'wire', 'pins': {'p': args[0], 'n': args[1]}}
            elif kind in 'VI' and len(args) >= 3:
                c = {'id': name, 'type': 'voltage_source' if kind == 'V' else 'current_source', 'pins': {'p': args[0], 'n': args[1]}}
                tail = args[2:]
                mode = tail.pop(0).lower()
                count = {'dc': 1, 'sine': 3, 'pulse': 7}.get(mode)
                if count is None or len(tail) < count:
                    raise ValueError('电源使用 DC 值、SINE 偏置 幅度 频率、PULSE 低 高 延迟 上升 下降 脉宽 周期')
                nums = [value(x) for x in tail[:count]]
                if mode == 'dc':
                    c['dc'] = nums[0]
                elif mode == 'sine':
                    c['waveform'] = dict(type='sine', **dict(zip(('offset', 'amplitude', 'frequency_hz'), nums)))
                    c['dc'] = nums[0]
                else:
                    c['waveform'] = dict(type='pulse', **dict(zip(('low', 'high', 'delay_s', 'rise_s', 'fall_s', 'width_s', 'period_s'), nums)))
                    c['dc'] = nums[0]
                rest = tail[count:]
                if rest:
                    if rest[0].lower() != 'ac' or len(rest) not in (2, 3):
                        raise ValueError('电源末尾可附加 AC 幅度 [相位]')
                    c['ac_magnitude'] = value(rest[1]); c['ac_phase_deg'] = value(rest[2]) if len(rest) == 3 else 0
            else:
                raise ValueError('未知元件或引脚/参数数量错误')
            components.append(c)
        except (ValueError, IndexError) as exc:
            raise ValueError(f'第 {index} 行：{exc}') from exc
    if not analyses or not signals:
        raise ValueError('请显式提供分析指令和 .save 测量节点/支路；不会自动猜测')
    declared = {m['id']:m for m in models}
    for c in components:
        if c['type'] != 'pmos':
            continue
        model = c.get('model', 'pch')
        if model == 'generic_nmos' or (model in declared and CMN018_MODELS.get(declared[model]['name'], (None,))[0] == 'nmos'):
            c['type'] = 'nmos'
    return CircuitTask.model_validate({'components': components, 'analyses': analyses, 'signals': signals, 'question': text,
                                      'parameter_sweeps':sweeps,'comparisons':comparisons, 'models':models,
                                      'pdk_corner':pdk_corner, **studies})
