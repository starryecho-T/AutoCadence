"""Bounded RC low-pass text parser; no model calls or guessed components."""
from __future__ import annotations
import re
from .models import TaskSpec

_NUMBER = r'[+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?'
_PREFIXES = {'': 1., 'k': 1e3, 'K': 1e3, 'M': 1e6, 'm': 1e-3, 'u': 1e-6, 'μ': 1e-6, 'µ': 1e-6, 'n': 1e-9, 'p': 1e-12}


def _values(text, kind):
    label = r'(?:R(?:1)?(?![A-Za-z])|resistance|resistor|电阻(?:\s*R1?)?)' if kind == 'r' else r'(?:C(?:1)?(?![A-Za-z])|capacitance|capacitor|电容(?:\s*C1?)?)'
    unit = r'(?:Ω|Ω|ohms?|欧姆|欧)' if kind == 'r' else r'(?:F|farads?|法拉|法)'
    pattern = rf'(?<![A-Za-z]){label}\s*(?:=|:|：|为|是|取|of)?\s*({_NUMBER})\s*([kKMmunpμµ]?)\s*({unit})?'
    result = []
    for match in re.finditer(pattern, text, re.I):
        raw, prefix, base = match.groups()
        if prefix not in _PREFIXES:
            continue
        if not prefix and not base:
            result.append((None, f'{match.group(0)} 未明确单位'))
        else:
            unit_name = 'Ω' if kind == 'r' else 'F'
            result.append((float(raw)*_PREFIXES[prefix], None if base else f'{match.group(0)} 按 {unit_name} 的工程前缀解释'))
    return result


def parse_question(text: str) -> dict:
    result = {'supported': True, 'task': None, 'missing_fields': [], 'defaults_applied': [], 'warnings': [], 'requires_confirmation': True}
    if not isinstance(text, str) or not text.strip():
        result['missing_fields'] = ['question', 'r_ohm', 'c_f']
        result['warnings'].append('请输入包含电阻、电容数值及单位的 RC 低通文字题目。')
        return result
    if len(text) > 10000:
        result['supported'] = False
        result['warnings'].append('题目超过 10000 字符限制。')
        return result
    if re.search(r'高通|带通|带阻|放大器|运放|运算放大|\bhigh[ -]?pass\b|\bband[ -]?(?:pass|stop)\b|\bamplifier\b|\bop[ -]?amp\b', text, re.I):
        result['supported'] = False
        result['warnings'].append('不支持该电路类型；当前仅支持一阶 RC 低通。')
        return result
    if re.search(r'图片|图像|截图|附件|见图|如图|\bimage\b|\bphoto\b|\battachment\b|\bscreenshot\b', text, re.I):
        result['supported'] = False
        result['warnings'].append('当前只解析文字，不读取图片或附件中的电路及参数。请提供完整文字题目。')
        return result
    fields = {}
    for kind, key in [('r', 'r_ohm'), ('c', 'c_f')]:
        found = _values(text, kind)
        valid = {v for v, _ in found if v is not None}
        result['defaults_applied'].extend(note for _, note in found if note and '工程前缀' in note)
        result['warnings'].extend(note for _, note in found if note and '未明确' in note)
        if len(valid) == 1 and not any(v is None for v, _ in found):
            fields[key] = valid.pop()
        else:
            result['missing_fields'].append(key)
            if len(valid) > 1:
                result['warnings'].append(f'{key} 存在多个不同数值，请明确采用哪一个。')
    if result['missing_fields']:
        return result
    if not re.search(r'低通|low[ -]?pass', text, re.I):
        result['defaults_applied'].append('题目未明确低通拓扑，候选按受支持的一阶 RC 低通生成，需确认。')
    result['defaults_applied'].extend([
        '当前仅自动识别电阻与电容；其余要求不由解析器推断。',
        '默认激励：0→1 V；周期 2 ms；高电平宽度 1 ms；上升/下降各 1 ns；延迟 1 µs。',
        '默认 AC：10 Hz–1 MHz，每十倍频 50 点；温度由执行模板固定为 27 °C。',
        '默认瞬态：终点 4.201 ms，最大步长 1 µs；提交前可修改并重新校验。',
    ])
    if re.search(r'周期|脉宽|上升|下降|延迟|幅值|扫频|瞬态|\bpulse\b|\bperiod\b|\brise\b|\bfall\b|\bdelay\b|\bwidth\b|\bfrequency\b|\btransient\b', text, re.I):
        result['warnings'].append('题目可能指定额外激励或分析条件；这些条件尚未自动提取，请在确认页逐项设置，不能直接沿用默认值。')
    candidate = dict(fields, title='RC 低通仿真', question=text)
    try:
        result['task'] = TaskSpec.model_validate(candidate).model_dump()
    except Exception as exc:
        result['warnings'].append(f'候选参数或默认分析范围未通过校验，请调整后提交：{exc}')
    return result
