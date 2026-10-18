import base64
from vai_backend.circuit_parsing import parse_circuit
from vai_backend.circuit_models import CircuitTask
from vai_backend.circuit_analysis import generate_report


def test_specific_titles_propagate_to_reports(tmp_path):
    task = parse_circuit('I1 0 vin DC 0.01\nR1 vin 0 100\nL1 vin 0 10m\n.tran 5m 1u\n.save V(vin) I(L1)')
    assert task.title == 'RL 电路 · 瞬态响应'
    custom = CircuitTask.model_validate({**task.model_dump(), 'title': '10mH 电感阶跃响应'})
    assert custom.title == '10mH 电感阶跃响应'
    metrics = {'validation_status':'PASS','requirements_status':'NOT_SPECIFIED','measurements':[], 'signals':{}, 'limitations':[]}
    for name in ('schematic_window.png', 'waveform_window.png'):
        (tmp_path/name).write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8WQAAAAASUVORK5CYII='))
    generate_report(custom.model_dump(), metrics, tmp_path, 'test-title', [])
    assert '<h1>10mH 电感阶跃响应</h1>' in (tmp_path/'report.html').read_text('utf-8')
    assert (tmp_path/'report.md').read_text('utf-8').startswith('# 10mH 电感阶跃响应')
