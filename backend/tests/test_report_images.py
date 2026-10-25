import base64

from vai_backend.circuit_analysis import generate_report as generate_circuit_report
from vai_backend.circuit_parsing import parse_circuit
from vai_backend.reporting import generate_report as generate_rc_report


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8WQAAAAASUVORK5CYII=')


def write_images(root, names):
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root/name).write_bytes(PNG)


def test_circuit_report_includes_each_analysis_capture_and_native_export(tmp_path):
    names = (
        'schematic_window.png', 'waveform_window.png',
        'waveform_ac_window.png', 'waveform_dc_window.png',
        'waveform_op_window.png', 'waveform_tran_window.png',
        'waveform_ac_native.png', 'waveform_tran_native.png',
    )
    write_images(tmp_path, names)
    task = parse_circuit('I1 0 vin DC 0.01\nR1 vin 0 100\nL1 vin 0 10m\n.tran 5m 1u\n.save V(vin) I(L1)')
    metrics = {'validation_status': 'PASS', 'requirements_status': 'NOT_SPECIFIED', 'measurements': [], 'signals': {}, 'limitations': []}
    generate_circuit_report(task.model_dump(), metrics, tmp_path, 'test-multi-capture', [])
    html = (tmp_path/'report.html').read_text(encoding='utf-8')
    markdown = (tmp_path/'report.md').read_text(encoding='utf-8')
    assert html.count('data:image/png;base64,') == len(names)
    for name in names:
        assert name in html
        assert f']({name})' in markdown
    assert 'ViVA AC 波形真实窗口截图' in html
    assert 'Cadence 瞬态波形原生导出' in html


def test_rc_report_includes_optional_analysis_captures_and_old_runs(tmp_path):
    old_run = tmp_path/'old'
    new_run = tmp_path/'new'
    legacy = ('schematic_window.png', 'waveform_window.png', 'schematic_native.png', 'waveform_native.png')
    write_images(old_run, legacy)
    write_images(new_run, (*legacy, 'waveform_ac_window.png', 'waveform_tran_window.png', 'waveform_ac_native.png'))
    metrics = {'checks': [{'name': 'evidence', 'status': 'PASS'}], 'validation_status': 'PASS'}
    for root, image_count in ((old_run, 4), (new_run, 7)):
        generate_rc_report({'title': 'RC'}, metrics, root, root.name, [])
        html = (root/'report.html').read_text(encoding='utf-8')
        assert html.count('data:image/png;base64,') == image_count
        assert '真实窗口截图不完整' not in html
    assert 'waveform_tran_window.png' in (new_run/'report.md').read_text(encoding='utf-8')
