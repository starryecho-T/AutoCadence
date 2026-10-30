"""Voltage-controlled analogLib switch, including its generated Spectre relay."""
import importlib.util
from pathlib import Path

import pytest

from vai_backend.circuit_models import CircuitTask
from vai_backend.circuit_parsing import parse_circuit
from vai_backend.circuit_examples import EXAMPLES
from vai_backend.circuits import compile_task, render_netlist
from vai_backend.circuit_compiler import scripts

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('generic_worker', ROOT/'worker/general.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def test_10mhz_switch_example_compiles_to_four_terminal_relay():
    task = parse_circuit(EXAMPLES['switch_10mhz'][1])
    compiled = compile_task(task)
    device = next(d for d in compiled['devices'] if d['id'] == 'S1')
    assert device['symbol'] == 'switch'
    assert device['terminals'] == ['N+', 'N-', 'NC+', 'NC-']
    assert device['master'] == 'relay'
    assert device['parameters'] == {'vt1':.2,'vt2':.8,'ropen':1e12,'rclosed':1e-3}
    assert device['nodes'][1] == device['nodes'][3] == '0'
    assert device['nodes'][0] != device['nodes'][2]
    assert task.components[7].waveform.period_s == pytest.approx(1e-7)
    netlist = render_netlist(task, compiled)
    assert worker.validate_netlist(netlist, compiled)['status'] == 'PASS'
    build = scripts(task)['build.il']
    assert 'dbOpenCellViewByType("analogLib" "switch" "symbol"' in build


def test_switch_defaults_and_validation():
    source = EXAMPLES['switch_10mhz'][1].replace('S1 switched 0 clock 0 0.2 0.8 1e12 1m', 'S1 switched 0 clock 0')
    switch = next(c for c in parse_circuit(source).components if c.id == 'S1')
    assert (switch.threshold_low_v, switch.threshold_high_v) == (.2, .8)
    assert (switch.open_resistance_ohm, switch.closed_resistance_ohm) == (1e12, 1e-3)
    task = parse_circuit(EXAMPLES['switch_10mhz'][1]).model_dump()
    part = next(c for c in task['components'] if c['id'] == 'S1')
    for key, value in [('threshold_low_v',.9),('open_resistance_ohm',.0001),('pins',{'p':'0','n':'0','cp':'clock','cn':'0'})]:
        bad = {**task, 'components':[dict(c) for c in task['components']]}
        target = next(c for c in bad['components'] if c['id'] == 'S1')
        target[key] = value
        with pytest.raises(ValueError):CircuitTask.model_validate(bad)
    assert part['type'] == 'switch'
