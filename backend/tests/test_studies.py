"""Numerical and contract boundaries for the advanced circuit workflow."""
import copy
import json
import pytest
from vai_backend.circuit_models import CircuitTask
from vai_backend.circuit_parsing import parse_circuit
from vai_backend.circuit_examples import EXAMPLES
from vai_backend.circuit_compiler import scripts, current_terminal
from vai_backend.circuit_studies import study_jobs
from vai_backend.circuits import compile_task,render_netlist
from vai_backend.circuit_analysis import analyze
from vai_backend.study_analysis import compare_curves,extract_two_port


def test_transistors_and_current_probes_compile_with_explicit_polarity_and_pin_order():
    for key,polarity in [('bjt_transfer','npn'),('pnp_bias','pnp')]:
        task=parse_circuit(EXAMPLES[key][1]);compiled=compile_task(task)
        q=next(d for d in compiled['devices'] if d['id']=='Q1')
        assert q['symbol']==polarity and q['nodes'][-1]=='0' and len(q['nodes'])==4
        assert f'type={polarity}' in compiled['model_text']
    compiled=compile_task(parse_circuit(EXAMPLES['pmos_families'][1]))
    assert 'mos1 type=p vto=-0.7' in compiled['model_text']
    assert current_terminal('bjt','b')==('b',1)
    assert current_terminal('pmos','bulk')==('b',1)
    assert current_terminal('vccs','n')==('sink',-1)


def test_sweep_plan_has_independent_tasks_and_changed_netlists():
    task=parse_circuit(EXAMPLES['pmos_families'][1]);before=task.model_dump_json()
    jobs=study_jobs(task)
    assert len(jobs)==5 and [j['id'] for j in jobs]==['base','s000','s001','s002','s003']
    assert task.model_dump_json()==before
    assert jobs[1]['parameters']=={'VG.dc':-1}
    assert 'dc=-1 ' in render_netlist(jobs[1]['task'],compile_task(jobs[1]['task']))
    data=scripts(task)
    assert 'batch_s003/psf' in data['export.il']
    assert 's003_dc_s0.txt' in data['export.il']
    bad=task.model_dump();bad['parameter_sweeps'][0]['values']=[-1,-1]
    with pytest.raises(ValueError,match='重复'):CircuitTask.model_validate(bad)
    bad=task.model_dump();bad['parameter_sweeps'][0]['component']='VD'
    with pytest.raises(ValueError,match='内层'):CircuitTask.model_validate(bad)
    bad=task.model_dump();bad['parameter_sweeps']=[{'component':'M1','parameter':'width_m','values':[0]}]
    with pytest.raises(ValueError):CircuitTask.model_validate(bad)


def test_two_sweep_axes_use_cartesian_product_and_enforce_aggregate_limit():
    task=parse_circuit(EXAMPLES['parameter_comparison'][1]).model_dump()
    task['parameter_sweeps'] += [{'component':'R2','parameter':'resistance_ohm','values':[1000,3000,5000]}]
    assert len(study_jobs(CircuitTask.model_validate(task)))==7
    task['parameter_sweeps'][0]['values']=list(range(1,10))
    with pytest.raises(ValueError,match='20'):CircuitTask.model_validate(task)


@pytest.mark.parametrize('change',[
    {'signals':[{'id':'bad','type':'current','component':'M1','terminal':'c'}]},
    {'signals':[{'id':'bad','type':'device_parameter','component':'VG','parameter':'region'}]},
    {'models':[{'id':'generic_pmos','type':'diode'}]},
    {'parameter_sweeps':[{'component':'M1','parameter':'gain','values':[1]}]},
])
def test_invalid_device_and_parameter_references_rejected(change):
    task=parse_circuit(EXAMPLES['pmos_families'][1]).model_dump()
    with pytest.raises(ValueError):CircuitTask.model_validate({**task,**change})


def test_control_source_must_be_voltage_probe_and_pin_current_direction_is_explicit():
    task=parse_circuit(EXAMPLES['controlled_sources'][1]).model_dump()
    next(c for c in task['components'] if c['id']=='F1')['control_source']='Rin'
    with pytest.raises(ValueError,match='voltage-source'):CircuitTask.model_validate(task)
    text=EXAMPLES['controlled_sources'][1].replace('I(VS)','I(VS,n)')
    assert '-i(' in scripts(parse_circuit(text))['export.il']


def test_comparison_checks_complex_phase_zero_targets_and_all_interpolation_knots():
    assert compare_curves([[1,1,0],[2,1,0]],[[1,0,1],[2,0,1]])['status']=='FAIL'
    assert compare_curves([[0,1e-10],[1,-1e-10]],[[0,0],[1,0]],atol=1e-9)['status']=='PASS'
    assert compare_curves([[0,0],[2,2]],[[0,0],[1,3],[2,2]])['status']=='FAIL'
    assert compare_curves([[2,4],[0,0]],[[0,0],[1,1],[2,2]],scale=2)['status']=='PASS'
    with pytest.raises(ValueError,match='范围'):compare_curves([[0,0],[2,2]],[[1,1],[2,2]])


def test_two_port_sign_and_independent_excitation_recover_known_complex_matrix(tmp_path):
    import cmath,math
    task=parse_circuit(EXAMPLES['common_base_y'][1]).model_dump()
    matrix=[[.04101,-.00001],[-.04001,.00001]]
    waves={}
    for case,u in [('yp1',[1,0]),('yp2',[0,1]),('ypcheck',[1,.37*cmath.exp(1j*math.radians(37))])]:
        for i in range(2):
            current=-sum(matrix[i][j]*u[j] for j in range(2))
            waves[(case,'ac',f'TP_I{i+1}')]=[[f,current.real,current.imag] for f in [10,1000,100000]]
    result=extract_two_port(task,waves,tmp_path)
    assert result['status']=='PASS'
    assert result['reference_matrix'][1][0]['real']==pytest.approx(-.04001)
    equivalent=CircuitTask.model_validate_json((tmp_path/'equivalent_task.json').read_text(encoding='utf-8'))
    assert len(equivalent.components)==6
    assert equivalent.components[4].gain==pytest.approx(-.04001)
    # A complex matrix is extracted faithfully, but no incorrect real-source equivalent is emitted.
    (tmp_path/'equivalent_task.json').unlink()
    for r in waves[('yp1','ac','TP_I1')]:r[2]=-.01
    result=extract_two_port(task,waves,tmp_path)
    assert not result['equivalent_supported'] and result['status']=='FAIL'
    assert not (tmp_path/'equivalent_task.json').exists()


def test_analysis_compares_requested_cases_and_propagates_failure(tmp_path):
    task=parse_circuit(EXAMPLES['parameter_comparison'][1]).model_dump()
    data=scripts(CircuitTask.model_validate(task));manifest=json.loads(data['signals.json'])
    (tmp_path/'signals.json').write_text(data['signals.json'])
    for entry in manifest:
        factor={'base':.5,'s000':.5,'s001':1/3}[entry['case']]
        (tmp_path/entry['filename']).write_text('\n'.join(f'{i/10} {i/10*factor}' for i in range(101)))
    result=analyze(task,tmp_path)
    assert result['requirements_status']=='PASS' and len(result['cases'])==3
    task['comparisons'][0]['reference_case']='s001'
    assert analyze(task,tmp_path)['requirements_status']=='FAIL'
    (tmp_path/'signals.json').write_text(json.dumps(manifest[:-1]))
    with pytest.raises(Exception,match='manifest'):analyze(task,tmp_path)


def test_bjt_theory_rejects_extra_load_and_wrong_topology():
    task=parse_circuit(EXAMPLES['bjt_transfer'][1]).model_dump()
    bad=copy.deepcopy(task);bad['components'] += [{'id':'load','type':'resistor','pins':{'p':'out','n':'0'},'resistance_ohm':1000}]
    with pytest.raises(ValueError,match='五元件'):CircuitTask.model_validate(bad)
    bad=copy.deepcopy(task);bad['components'][-1]['model']='generic_pnp'
    with pytest.raises(ValueError,match='NPN'):CircuitTask.model_validate(bad)
    bad=copy.deepcopy(task);bad['parameter_sweeps']=[{'component':'VCC','parameter':'dc','values':[.1]}]
    with pytest.raises(ValueError,match='共射'):CircuitTask.model_validate(bad)
