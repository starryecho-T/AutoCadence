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
from vai_backend.cmn018 import MODEL_PLACEHOLDER
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


def test_capture_config_preserves_each_curve_analysis():
    config = json.loads(scripts(parse_circuit(EXAMPLES['inverting'][1]))['capture_config.json'])
    assert [plot['analysis'] for plot in config['plots']] == ['tran', 'ac']
    assert config['analysis'] == 'tran'
    assert all(len(plot['expressions']) == len(plot['labels']) for plot in config['plots'])
    op_only = json.loads(scripts(parse_circuit(EXAMPLES['divider'][1]))['capture_config.json'])
    assert [plot['analysis'] for plot in op_only['plots']] == ['op']


def test_nmos_symbol_and_spectre_model_and_current_probe():
    task = parse_circuit(EXAMPLES['nmos_families'][1])
    compiled = compile_task(task)
    mos = next(d for d in compiled['devices'] if d['id'] == 'M1')
    assert mos['symbol'] == 'nmos4'
    assert mos['master'].startswith('dm')
    assert 'mos1 type=n vto=0.7' in compiled['model_text']
    assert worker.validate_netlist(render_netlist(task, compiled), compiled)['status'] == 'PASS'
    assert '"nmos4"' in scripts(task)['build.il']


def test_cmn018_direct_models_use_only_allowlisted_server_sections():
    task = parse_circuit('''VDD rail 0 DC 1.8
VG gate 0 DC 1
M1 rail gate 0 0 core_n w=10u l=0.18u
.model core_n cmn018 nch
.corner tt
.op
.save I(M1,d) P(M1,region)''')
    compiled = compile_task(task)
    assert compiled['pdk_sections'] == ['tt']
    assert compiled['devices'][2]['master'] == 'nch'
    assert f'include "{MODEL_PLACEHOLDER}" section=tt' in compiled['model_text']
    netlist = render_netlist(task, compiled)
    assert worker.validate_netlist(netlist, compiled)['status'] == 'PASS'
    assert MODEL_PLACEHOLDER in scripts(task)['models.scs']
    with tarfile.open(fileobj=io.BytesIO(_archive(task.model_dump(), 'vai_cmn018_archive',
                                                  {'remote_base':'/test', 'cmn018_model_file':'/pdk/model/cmn018_gp2a_5v_v1d4.scs'})),mode='r:gz') as tf:
        assert 'cmn018_gp2a_5v_v1d4.scs' not in tf.getnames()
        assert 'models.scs' in tf.getnames()
        assert b'@CMN018_MODEL_FILE@' in tf.extractfile('models.scs').read()


def test_cmn018_rejects_unknown_model_wrong_type_and_out_of_range_geometry():
    base = parse_circuit(EXAMPLES['nmos_families'][1]).model_dump()
    base['models'] = [{'id':'core_n','type':'cmn018','name':'nch'}]
    base['components'][2]['model'] = 'core_n'
    assert CircuitTask.model_validate(base)
    for name, width, length in [('unknown',10e-6,1e-6),('pch',10e-6,1e-6),
                                ('nch',.1e-6,1e-6),('nch',10e-6,.1e-6)]:
        bad = copy.deepcopy(base)
        bad['models'][0]['name'] = name
        bad['components'][2]['width_m'] = width
        bad['components'][2]['length_m'] = length
        with pytest.raises(ValueError):
            CircuitTask.model_validate(bad)


@pytest.mark.parametrize('corner', ['ss', 'ff'])
def test_cmn018_mixed_families_use_selected_corner_sections(corner):
    task = parse_circuit('''V1 rail 0 DC 1.8
VG gate 0 DC 1
R1 rail node 1k
Q1 node rail 0 core_q
D1 node 0 core_d
M1 node gate 0 0 core_n w=1u l=0.18u
M2 rail gate rail rail core_p w=1u l=0.18u
.model core_q cmn018 npn2
.model core_d cmn018 ndio
.model core_n cmn018 nch
.model core_p cmn018 pch
.corner ''' + corner + '''
.op
.save I(Q1,c) I(D1)''')
    compiled = compile_task(task)
    assert compiled['pdk_sections'] == [corner, corner + '_bip', corner + '_dio']
    assert {d['id']: d['master'] for d in compiled['devices']}['Q1'] == 'npn2'
    assert {d['id']: d['master'] for d in compiled['devices']}['D1'] == 'ndio'
    assert {d['id']: d['master'] for d in compiled['devices']}['M1'] == 'nch'
    assert {d['id']: d['master'] for d in compiled['devices']}['M2'] == 'pch'
    assert 'parOpt options redefinedparams=ignore' in compiled['model_text']
    assert 'parameters mismatchflag_mos=0' in compiled['model_text']
    assert 'parameters mismatchflag_bip=0' in compiled['model_text']
    assert worker.validate_netlist(render_netlist(task, compiled), compiled)['status'] == 'PASS'


def test_cmn018_preflight_checks_server_local_companion_and_sections(monkeypatch):
    class ModelError(Exception):
        def __init__(self, code, message):
            self.code = code
            super().__init__(message)

    compiled = {'pdk_sections':['tt', 'tt_bip']}
    with pytest.raises(ModelError, match='cmn018_model_file') as exc:
        worker.resolve_model_file({}, compiled, ModelError)
    assert exc.value.code == 'CMN018_NOT_CONFIGURED'
    deck = '/pdk/cmn018_gp2a_5v_v1d4.scs'
    usage = worker.os.path.join(worker.os.path.dirname(deck), 'cmn018_gp2a_5v_v1d4_usage.scs')
    contents = {deck:'section tt\nendsection tt\nsection tt_bip\nendsection tt_bip\n',
                usage:'include "cmn018_gp2a_5v_v1d4.scs" section=tt\n'
                      'include "cmn018_gp2a_5v_v1d4.scs" section=tt_bip\n'}
    monkeypatch.setattr(worker.os.path, 'isfile', lambda path: path in contents)
    monkeypatch.setattr(worker.os, 'access', lambda path, mode: path in contents)
    monkeypatch.setattr(worker, 'open', lambda path: io.StringIO(contents[path]), raising=False)
    config = {'cmn018_model_file':deck}
    assert worker.resolve_model_file(config, compiled, ModelError) == (deck, usage)
    missing_usage = contents.pop(usage)
    with pytest.raises(ModelError) as exc:
        worker.resolve_model_file(config, compiled, ModelError)
    assert exc.value.code == 'CMN018_MODEL_MISSING'
    contents[usage] = missing_usage
    contents[usage] = 'include "cmn018_gp2a_5v_v1d4.scs" section=tt\n'
    with pytest.raises(ModelError) as exc:
        worker.resolve_model_file(config, compiled, ModelError)
    assert exc.value.code == 'CMN018_SECTION_MISSING'


def test_generic_drawing_validation_accepts_a_constant_trace_but_rejects_only_toolbar():
    # Synthetic pixels test the validator only; these are never run evidence.
    image = Image.new('RGB',(1000,800),'black')
    draw = ImageDraw.Draw(image)
    draw.rectangle((10,20,990,80),fill='cyan')
    with pytest.raises(ImageError,match='canvas is empty'):
        _general_canvas_stats(image,'waveform')
    draw.line((500,400,920,400),fill='lime',width=2)
    assert _general_canvas_stats(image,'waveform')['colored_pixels'] > 150
