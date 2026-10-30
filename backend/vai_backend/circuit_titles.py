"""Deterministic task names; do not guess a topology from component names."""
def circuit_title(task):
    title = str(task.get('title') or '').strip()
    if title and title != '通用电路仿真':
        return title
    kinds = {c['type'] for c in task['components']}
    if 'bjt' in kinds:
        family = 'BJT 晶体管电路'
    elif 'nmos' in kinds:
        family = 'NMOS 电路'
    elif 'pmos' in kinds:
        family = 'PMOS 电路'
    elif 'nmos' in kinds:
        family = 'NMOS 电路'
    elif 'switch' in kinds:
        family = '开关电路'
    elif 'ideal_opamp' in kinds:
        family = '运放电路'
    elif 'diode' in kinds:
        family = '二极管电路'
    else:
        parts = ''.join(label for kind, label in [('resistor', 'R'), ('inductor', 'L'), ('capacitor', 'C')] if kind in kinds)
        family = (parts + ' 电路') if parts else '电源与受控源电路'
    analyses = {'op': '直流工作点', 'dc': '直流扫描', 'ac': '交流频响', 'tran': '瞬态响应'}
    study = '二端口分析' if task.get('two_port') else '转移特性' if task.get('bjt_transfer') else '参数扫描' if task.get('parameter_sweeps') else ' / '.join(analyses.get(a['type'], a['type']) for a in task['analyses'])
    return f'{family} · {study}'[:120]
