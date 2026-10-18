"""Complex waveform comparisons, two-port extraction and bounded CE theory."""
from __future__ import annotations
import bisect
import cmath
import json
import math
from pathlib import Path


def interpolator(rows):
    if rows[0][0] > rows[-1][0]:
        rows = rows[::-1]
    xs = [r[0] for r in rows]
    z = lambda r: complex(r[1],r[2] if len(r)==3 else 0)
    def at(coordinate):
        if coordinate < xs[0] or coordinate > xs[-1]:
            raise ValueError('比较波形的坐标范围不匹配；不允许外推')
        i = bisect.bisect_left(xs, coordinate)
        if i == 0 or xs[i] == coordinate:
            return z(rows[i])
        a,b = rows[i-1],rows[i]
        return z(a)+(z(b)-z(a))*(coordinate-a[0])/(b[0]-a[0])
    return at


def complex_at(rows, coordinate):
    return interpolator(rows)(coordinate)


def compare_curves(actual, reference, rtol=1e-3, atol=1e-9, scale=1):
    if len(actual[0]) != len(reference[0]):
        raise ValueError('比较波形的实数/复数表示不同')
    endpoints = sorted([actual[0][0],actual[-1][0]])
    refend = sorted([reference[0][0],reference[-1][0]])
    if any(not math.isclose(x,y,rel_tol=1e-10,abs_tol=1e-15) for x,y in zip(endpoints,refend)):
        raise ValueError('比较波形必须覆盖相同范围')
    # Include both sets of knots so a narrow feature in either trace is tested.
    axis = sorted({r[0] for r in actual} | {r[0] for r in reference})
    errors, ratios = [], []
    value_at, target_at = interpolator(actual),interpolator(reference)
    for x in axis:
        value, target = value_at(x), scale*target_at(x)
        error = abs(value-target)
        errors.append(error)
        ratios.append(error/(atol+rtol*abs(target)))
    return {'status':'PASS' if max(ratios)<=1 else 'FAIL', 'samples_compared':len(axis),
            'max_absolute_error':max(errors), 'rmse':math.sqrt(sum(e*e for e in errors)/len(errors)),
            'max_tolerance_ratio':max(ratios), 'worst_coordinate':axis[ratios.index(max(ratios))],
            'relative_tolerance':rtol, 'absolute_tolerance':atol,
            'method':'Complex values, linear interpolation on union of sample coordinates; |error| <= atol + rtol*|reference|.'}


def packed(z):
    return {'real':z.real,'imag':z.imag}


def extract_two_port(task,waves,root):
    cfg = task['two_port']
    first = waves[('yp1','ac','TP_I1')]
    matrix_rows = []
    for row in first:
        x = row[0]
        y = [[-complex_at(waves[(f'yp{j+1}','ac',f'TP_I{i+1}')],x) for j in range(2)] for i in range(2)]
        matrix_rows.append({'frequency_hz':x,'matrix':[[packed(z) for z in r] for r in y]})
    reference = [[-complex_at(waves[(f'yp{j+1}','ac',f'TP_I{i+1}')],cfg['reference_hz']) for j in range(2)] for i in range(2)]
    # Third excitation is independent of the two identification experiments.
    u = [1, .37*cmath.exp(1j*math.radians(37))]
    checks = []
    for i in range(2):
        prediction = []
        for row in matrix_rows:
            z = 0j
            for j in range(2):
                entry = row['matrix'][i][j]
                z += complex(entry['real'],entry['imag'])*u[j]
            prediction.append([row['frequency_hz'],-z.real,-z.imag])
        checks.append({'port':i+1, **compare_curves(waves[('ypcheck','ac',f'TP_I{i+1}')],prediction,cfg['relative_tolerance'],cfg['absolute_tolerance_a'])})
    imaginary = max(abs(z.imag) for r in reference for z in r)
    result = {'definition':'[I1,I2]^T = Y [V1,V2]^T; current positive into DUT, Iport = -I(test voltage source p).',
              'scope':'AC small-signal at the original DC bias; other independent AC excitations set to zero.',
              'unit':'S','reference_hz':cfg['reference_hz'], 'reference_matrix':[[packed(z) for z in r] for r in reference],
              'frequency_points':len(matrix_rows),'sweep':matrix_rows,'linearity_checks':checks,
              'status':'PASS' if all(c['status']=='PASS' for c in checks) else 'FAIL',
              'equivalent_requested':cfg['generate_equivalent'],
              'equivalent_supported':imaginary <= cfg['max_imaginary_admittance_s'],
              'max_reference_imaginary_s':imaginary,
              'equivalent_scope':'Four real VCCS, coefficients taken at reference_hz; full-band equivalence is separately tested.'}
    if cfg['generate_equivalent']:
        if not result['equivalent_supported']:
            result.update(status='FAIL',equivalence={'status':'FAIL','reason':'参考频率的 Y 含显著虚部，不能用四个实数 VCCS 构造；需频率相关的动态等效模型。'})
        else:
            from .circuit_studies import equivalent_task
            equivalent = equivalent_task(task,reference)
            (Path(root)/'equivalent_task.json').write_text(json.dumps(equivalent,ensure_ascii=False,indent=2),encoding='utf-8')
    (Path(root)/'two_port.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def bjt_transfer_analysis(task,jobs,waves,plot):
    from .circuits import device_models
    cfg, output = task['bjt_transfer'], []
    names = {0:'cutoff',1:'forward_active',2:'reverse_active',3:'saturation',4:'breakdown'}
    for job in jobs:
        if job['role'] not in ('baseline','parameter_sweep'):
            continue
        cid, spec = job['id'],job['task']
        parts = {p['id']:p for p in spec['components']}
        q, rb, rc, supply = [parts[cfg[k]] for k in ('transistor','base_resistor','collector_resistor','supply_source')]
        beta = device_models(spec)[q['model']]['forward_beta']
        vcc = supply['dc']; base_r, collector_r = rb['resistance_ohm'],rc['resistance_ohm']
        rows = waves[(cid,'dc','BT_output')]
        theory = [[r[0],vcc-min(max(beta*(r[0]-cfg['be_on_v'])/base_r,0),(vcc-cfg['ce_saturation_v'])/collector_r)*collector_r] for r in rows]
        errors = [abs(a[1]-b[1]) for a,b in zip(rows,theory)]
        intervals = []
        for r in waves[(cid,'dc','BT_region')]:
            code = int(round(r[1]))
            name = names.get(code,'unknown')
            if not intervals or intervals[-1]['region'] != name:
                intervals.append({'region':name,'code':code,'start_v':r[0],'stop_v':r[0],'samples':1})
            else:
                intervals[-1]['stop_v']=r[0];intervals[-1]['samples']+=1
        output.append({'case':cid,'parameters':job['parameters'],'regions':intervals,
                       'max_absolute_error_v':max(errors),'rmse_v':math.sqrt(sum(e*e for e in errors)/len(errors)),
                       'theory_cutoff_boundary_v':cfg['be_on_v'],
                       'theory_saturation_boundary_v':cfg['be_on_v']+(vcc-cfg['ce_saturation_v'])*base_r/(beta*collector_r),
                       'theory':'Ic=clamp(beta*(Vin-VBEon)/RB, 0, (VCC-VCEsat)/RC); Vout=VCC-Ic*RC',
                       'scope':'分段近似与连续 BJT 模型的误差为测量值，不按精确相等判定；工作区代码来自 Spectre。',
                       'base_resistor_role':'限制基极电流；移除后输入电压源直接驱动 BE 结，模型不再适用。'})
        plot.append({'case':cid,'analysis':'dc','signal':'BT_theory','unit':'V','rows':theory,'original_samples':len(theory),'source':'piecewise_theory'})
    return output


def finish_equivalence(task, metrics, evidence, child_result, child_evidence):
    from .circuit_analysis import read_wave, downsample
    root = Path(evidence)
    manifest = json.loads((root/'signals.json').read_text(encoding='utf-8'))
    childroot = Path(child_evidence)
    other = json.loads((childroot/'signals.json').read_text(encoding='utf-8'))
    cfg = task['two_port']; checks=[]
    plots = json.loads((root/'waveforms.json').read_text(encoding='utf-8'))
    for sid in ('TP_I1','TP_I2'):
        source = next(e for e in manifest if e.get('case')=='ypcheck' and e['signal']==sid)
        equivalent = next(e for e in other if e['signal']==sid and e['analysis']=='ac')
        a,b = read_wave(root/source['filename'],True),read_wave(childroot/equivalent['filename'],True)
        checks.append({'signal':sid,**compare_curves(b,a,cfg['relative_tolerance'],cfg['absolute_tolerance_a'])})
        plots['series'].append({**equivalent,'case':'equivalent','rows':downsample(b),'original_samples':len(b),'role':'equivalent'})
    status = 'PASS' if all(c['status']=='PASS' for c in checks) and child_result['metrics']['validation_status']=='PASS' else 'FAIL'
    metrics['two_port']['equivalence'] = {'status':status,'checks':checks,'run_id':childroot.parent.name,
        'scope':'Independent Cadence/Spectre equivalent circuit, both ports excited at once (1∠0°, 0.37∠37° V), full requested AC band.'}
    if status != 'PASS':
        metrics['two_port']['status']='FAIL'
    update_requirements(metrics)
    (root/'waveforms.json').write_text(json.dumps(plots,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    (root/'two_port.json').write_text(json.dumps(metrics['two_port'],ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'comparison.json').write_text(json.dumps(metrics['two_port']['equivalence'],ensure_ascii=False,indent=2),encoding='utf-8')


def update_requirements(metrics):
    requested = [m['status'] for m in metrics['measurements'] if m['status'] != 'MEASURED']
    requested += [m['status'] for m in metrics.get('comparisons',[])]
    if metrics.get('two_port'):
        requested.append(metrics['two_port']['status'])
    metrics['requirements_status'] = 'NOT_SPECIFIED' if not requested else 'PASS' if all(s=='PASS' for s in requested) else 'FAIL'
