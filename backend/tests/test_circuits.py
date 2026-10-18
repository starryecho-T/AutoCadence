import copy
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vai_backend.api import create_app
from vai_backend.config import Settings
from vai_backend.manager import RunManager
from vai_backend.circuit_models import CircuitTask
from vai_backend.circuit_parsing import parse_circuit
from vai_backend.circuit_examples import EXAMPLES
from vai_backend.circuits import compile_task, normalize, render_netlist
from vai_backend.circuit_compiler import scripts
from vai_backend.circuit_analysis import analyze, evaluate
from vai_backend.pipeline import _archive
from vai_backend.images import ImageError, _general_canvas_stats
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('generic_worker', ROOT/'worker/general.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


@pytest.mark.parametrize('key', EXAMPLES)
def test_examples_compile_and_compare_actual_topology(key):
    t = parse_circuit(EXAMPLES[key][1])
    c = compile_task(t)
    netlist = render_netlist(t, c)
    assert worker.validate_netlist(netlist, c)['status'] == 'PASS'
    programs = scripts(t)
    assert 'BUILD_PASSED' in programs['build.il']
    assert 'signals.json' in programs
    assert CircuitTask.model_validate_json(t.model_dump_json()) == t
    # A changed pin on an otherwise matching device must fail.
    first = c['devices'][0]
    bad = netlist.replace(' '.join(first['nodes']), 'unexpected 0', 1)
    with pytest.raises(ValueError, match='topology'):
        worker.validate_netlist(bad, c)


def test_wire_aliases_ground_and_conflicting_sources():
    t = parse_circuit(EXAMPLES['divider'][1])
    c = normalize(t)
    assert c['aliases']['mid'] == c['aliases']['out']
    assert len(c['components']) == 3
    for text in [
        'V1 a 0 DC 5\nW1 a 0\n.op\n.save V(a)',
        'V1 a 0 DC 5\nV2 a 0 DC 10\n.op\n.save V(a)',
        'R1 a b 1k\n.op\n.save V(a)',
        'V1 a 0 DC 5\nR1 x y 1k\n.op\n.save V(a)',
        'V1 a 0 DC 5\nR1 a 0 0\n.op\n.save V(a)',
        'V1 a 0 DC 5\nU1 a a out\n.op\n.save V(out)',
    ]:
        with pytest.raises(ValueError):
            parse_circuit(text)


def test_input_does_not_infer_missing_connections_or_execute_commands():
    for text in ['请仿真一个 RLC 电路', 'R1 a 0 1k', 'V1 a 0 DC 1\n.ac 1 10 10\n.save V(a)',
                 'V1 a 0 DC 1\n.shell rm\n.save V(a)', 'V1 a 0 DC 1\n.op\n.save I(unknown)']:
        with pytest.raises(ValueError):
            parse_circuit(text)
    bad = parse_circuit(EXAMPLES['divider'][1]).model_dump()
    bad['components'][0]['pins']['p'] = 'x) shell foo'
    with pytest.raises(ValueError):
        CircuitTask.model_validate(bad)


def test_waveform_parameters_models_and_reference_validation():
    t = parse_circuit(EXAMPLES['rectifier'][1]).model_dump()
    t['components'][0]['waveform'] = {'type':'pwl','points':[[0,0],[.01,2],[.02,0]]}
    t['models'] = [{'id':'specific','saturation_current_a':2e-12}]
    t['components'][1]['model'] = 'specific'
    c = compile_task(CircuitTask.model_validate(t))
    assert '2e-12' in c['model_text']
    assert 'tvpairs' in c['devices'][0]['properties']
    for change in [{'models':[]}, {'signals':[{'id':'bad','type':'voltage','p':'unknown'}]},
                   {'analyses':[{'type':'tran','stop_s':1,'max_step_s':1e-10}]}]:
        with pytest.raises(ValueError):
            CircuitTask.model_validate({**t, **change})


def test_v2_preview_is_read_only_and_tasks_persist(tmp_path):
    manager = RunManager(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path), manager)) as client:
        r = client.post('/api/v2/parse',json={'text':EXAMPLES['divider'][1]})
        assert r.status_code == 200
        assert r.json()['requires_confirmation'] is True
        assert not manager.list()
        assert client.post('/api/v2/parse', json={'text':'unknown'}).status_code == 422
        # Submit without starting remote EDA: the executor is an explicit fixture.
        manager.executor = lambda task, root, emit: {'metrics':{'test_fixture':True},'warnings':[]}
        submitted = client.post('/api/v2/runs',json=r.json()['task'])
        assert submitted.status_code == 202
        rid = submitted.json()['run_id']
    recovered = RunManager(tmp_path).get(rid)
    assert recovered.task.template_id == 'general_circuit'


def test_archive_contains_generated_programs_and_no_ssh_secrets():
    task = parse_circuit(EXAMPLES['inverting'][1]).model_dump()
    with tarfile.open(fileobj=io.BytesIO(_archive(task,'vai_generic_archive',{'ssh_identity_file':'secret','remote_base':'/test'})),mode='r:gz') as tf:
        assert {'general.py','compiled.json','ideal_opamp.va','export.il'} <= set(tf.getnames())
        assert 'secret' not in tf.extractfile('input.json').read().decode()
        assert 'V(out):' in tf.extractfile('ideal_opamp.va').read().decode()


def test_real_sample_measurements_use_time_weighting_and_complex_values(tmp_path):
    base = {'operation':'mean','representation':'real','analysis':'tran'}
    assert evaluate([[0,0],[1,2],[4,2]],base) == pytest.approx(1.75)
    assert evaluate([[0,0],[1,2]],{**base,'operation':'rms'}) == pytest.approx((4/3)**.5)
    assert evaluate([[10,3,4]],{**base,'analysis':'ac','operation':'final','representation':'magnitude'}) == 5
    task = parse_circuit(EXAMPLES['divider'][1]).model_dump()
    task['measurements'] = [{'id':'voltage','analysis':'op','signal':'s1','operation':'final','minimum':6}]
    task = CircuitTask.model_validate(task).model_dump()
    manifest = [{'analysis':'op','signal':'s1','filename':'op_s0.txt','unit':'V'}, {'analysis':'op','signal':'s2','filename':'op_s1.txt','unit':'A'}]
    (tmp_path/'signals.json').write_text(json.dumps(manifest))
    (tmp_path/'op_s0.txt').write_text('0 5\n')
    (tmp_path/'op_s1.txt').write_text('0 .005\n')
    result = analyze(task,tmp_path)
    assert result['validation_status'] == 'PASS'
    assert result['requirements_status'] == 'FAIL'
    assert result['measurements'][0]['value'] == 5
    (tmp_path/'op_s0.txt').write_text('0 NaN\n')
    with pytest.raises(Exception,match='non-finite'):
        analyze(task,tmp_path)


def test_initialization_and_dc_sweep_do_not_use_ambiguous_simulator_defaults():
    task = parse_circuit(EXAMPLES['pwl_cap'][1])
    netlist = render_netlist(task, compile_task(task))
    assert 'rforce=0.001' in netlist
    assert 'ic=dev' in netlist and 'skipdc=yes' not in netlist
    disabled = task.model_copy(update={'analyses': [task.analyses[0].model_copy(update={'use_initial_conditions':False})]})
    assert 'ic=dc' in render_netlist(disabled, compile_task(disabled))
    assert any('忽略' in w for w in compile_task(disabled)['warnings'])
    both = scripts(parse_circuit(EXAMPLES['divider_dc'][1]))
    assert 'selectResults("dc-dc")' in both['export.il']
    assert "selectResults('dc)" not in both['export.il']
    assert evaluate([[10,5],[0,0]],{'analysis':'dc','operation':'at','representation':'real','at':2}) == 1
    assert evaluate([[1,-1,.01],[2,-1,-.01]],{'analysis':'ac','operation':'at','representation':'phase_deg','at':1.5}) == 180


def test_generic_drawing_validation_accepts_a_constant_trace_but_rejects_only_toolbar():
    # Synthetic pixels test the validator only; these are never run evidence.
    image = Image.new('RGB',(1000,800),'black')
    draw = ImageDraw.Draw(image)
    draw.rectangle((10,20,990,80),fill='cyan')
    with pytest.raises(ImageError,match='canvas is empty'):
        _general_canvas_stats(image,'waveform')
    draw.line((500,400,920,400),fill='lime',width=2)
    assert _general_canvas_stats(image,'waveform')['colored_pixels'] > 150
