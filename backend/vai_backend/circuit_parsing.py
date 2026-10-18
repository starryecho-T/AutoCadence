"""Explicit connection-list input. Never infer an unspecified topology."""
import json
import re
from pydantic import ValidationError
from .circuit_models import CircuitTask


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
    components, analyses, signals = [], [], []
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
                elif command == '.save' and args:
                    for token in args:
                        m = re.fullmatch(r'([VIvi])\((\w+)(?:,(\w+))?\)', token)
                        if not m:
                            raise ValueError('测量写法为 V(node)、V(p,n) 或 I(component)')
                        sid = f's{len(signals)+1}'
                        signals.append({'id': sid, 'type': 'voltage', 'p': m[2], 'n': m[3] or '0'} if m[1].lower() == 'v' else {'id': sid, 'type': 'current', 'component': m[2]})
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
    return CircuitTask.model_validate({'components': components, 'analyses': analyses, 'signals': signals, 'question': text})
