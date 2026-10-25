"""NMOS mirror of the PMOS contract: polarity, symbols, validation, titles."""
import importlib.util
from pathlib import Path

import pytest

from vai_backend.circuit_models import CircuitTask, MOS1Model
from vai_backend.circuit_parsing import parse_circuit
from vai_backend.circuit_examples import EXAMPLES
from vai_backend.circuit_compiler import scripts, current_terminal
from vai_backend.circuit_studies import study_jobs
from vai_backend.circuits import compile_task, render_netlist

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('generic_worker', ROOT/'worker/general.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

EXAMPLE = EXAMPLES['nmos_id_vgs'][1]


def test_nmos_example_compiles_with_n_polarity_card_and_nmos4_symbol():
    task = parse_circuit(EXAMPLE)
    assert task.title == 'NMOS 电路 · 直流扫描'
    assert [m.id for m in task.measurements] == ['id_max']
    compiled = compile_task(task)
    m = next(d for d in compiled['devices'] if d['id'] == 'M1')
    assert m['symbol'] == 'nmos4' and m['terminals'] == ['D', 'G', 'S', 'B']
    assert m['nodes'][:2] != ['0', '0'] and m['nodes'][-2:] == ['0', '0']
    # n-channel polarity with a positive, physically matched threshold voltage.
    assert 'mos1 type=n vto=0.7 kp=0.0001' in compiled['model_text']
    assert 'type=p' not in compiled['model_text']
    netlist = render_netlist(task, compiled)
    assert worker.validate_netlist(netlist, compiled)['status'] == 'PASS'
    build = scripts(task)['build.il']
    assert 'dbOpenCellViewByType("analogLib" "nmos4" "symbol"' in build
    assert 'dbOpenCellViewByType("analogLib" "pmos4"' not in build
    # The 4-terminal MOS bulk keeps its own lane on the positive side (PMOS convention, M1 at i=2).
    assert 'endpoint=list(9.75 yCoord(point))' in build


def test_current_terminal_stays_in_sync_between_compiler_and_worker():
    for kind, requested, expected in [('nmos', None, ('d', 1)), ('nmos', 'd', ('d', 1)),
                                      ('nmos', 'g', ('g', 1)), ('nmos', 's', ('s', 1)),
                                      ('nmos', 'bulk', ('b', 1)), ('pmos', 'bulk', ('b', 1)),
                                      ('bjt', 'b', ('b', 1)), ('vccs', 'n', ('sink', -1))]:
        assert current_terminal(kind, requested) == expected
        assert worker.current_terminal(kind, requested) == expected


def test_text_parser_maps_nmos_model_names_and_keeps_pmos_default():
    task = parse_circuit('VDD drain 0 DC 3.3\nVG gate 0 DC 0\n'
                         'M1 drain gate 0 0 generic_nmos w=10u l=1u\n'
                         '.dc VG 0 3.3 0.05\n.save I(M1,d) P(M1,vgs)')
    m = task.components[2]
    assert (m.type, m.model, m.pins.d, m.pins.g, m.pins.s, m.pins.b) == ('nmos', 'generic_nmos', 'drain', 'gate', '0', '0')
    assert parse_circuit(EXAMPLES['pmos_families'][1]).components[2].type == 'pmos'
    bare = 'VG gate 0 DC 0\nVD drain 0 DC 0\nM1 drain gate 0 0\n.dc VD 0 -1 -0.1\n.save I(M1,d)'
    assert parse_circuit(bare).components[2].type == 'pmos'


@pytest.mark.parametrize('change', [
    {'signals': [{'id': 'bad', 'type': 'current', 'component': 'M1', 'terminal': 'c'}]},
    {'signals': [{'id': 'bad', 'type': 'current', 'component': 'M1', 'terminal': 'e'}]},
    {'signals': [{'id': 'bad', 'type': 'device_parameter', 'component': 'M1', 'parameter': 'vbe'}]},
    {'signals': [{'id': 'bad', 'type': 'device_parameter', 'component': 'VG', 'parameter': 'vgs'}]},
    {'models': [{'id': 'generic_nmos', 'type': 'diode'}]},
    {'models': [{'id': 'generic_nmos', 'type': 'mos1', 'polarity': 'p', 'threshold_voltage_v': -.7}]},
    {'parameter_sweeps': [{'component': 'M1', 'parameter': 'gain', 'values': [1]}]},
])
def test_invalid_nmos_references_rejected(change):
    task = parse_circuit(EXAMPLE).model_dump()
    with pytest.raises(ValueError):
        CircuitTask.model_validate({**task, **change})


def test_custom_nmos_model_compiles_positive_and_pmos_rejects_n_channel_model():
    task = parse_circuit(EXAMPLE).model_dump()
    task['models'] = [{'id': 'strong_n', 'type': 'mos1', 'polarity': 'n',
                       'threshold_voltage_v': .5, 'transconductance_a_v2': 2e-4}]
    task['components'][2]['model'] = 'strong_n'
    compiled = compile_task(CircuitTask.model_validate(task))
    assert 'mos1 type=n vto=0.5 kp=0.0002' in compiled['model_text']
    pmos = parse_circuit(EXAMPLES['pmos_families'][1]).model_dump()
    pmos['models'] = [{'id': 'nch', 'type': 'mos1', 'polarity': 'n', 'threshold_voltage_v': .7}]
    pmos['components'][2]['model'] = 'nch'
    with pytest.raises(ValueError, match='incompatible device model'):
        CircuitTask.model_validate(pmos)


def test_mos1_model_threshold_sign_must_match_channel_polarity():
    assert MOS1Model(id='x', type='mos1', polarity='n', threshold_voltage_v=.7).threshold_voltage_v == .7
    assert MOS1Model(id='x', type='mos1').polarity == 'p'
    with pytest.raises(ValueError):
        MOS1Model(id='x', type='mos1', polarity='n', threshold_voltage_v=-.7)
    with pytest.raises(ValueError):
        MOS1Model(id='x', type='mos1', polarity='p', threshold_voltage_v=.7)


def test_nmos_width_sweep_plans_parameter_families():
    task = parse_circuit(EXAMPLE).model_dump()
    task['parameter_sweeps'] = [{'component': 'M1', 'parameter': 'width_m', 'values': [5e-6, 10e-6]}]
    jobs = study_jobs(CircuitTask.model_validate(task))
    assert [j['id'] for j in jobs] == ['base', 's000', 's001']
    netlist = render_netlist(jobs[1]['task'], compile_task(jobs[1]['task']))
    assert 'w=5e-06' in netlist
