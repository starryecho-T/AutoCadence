import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from vai_backend.api import create_app
from vai_backend.config import Settings
from vai_backend.manager import RunManager, utc_now
from vai_backend.models import RunResult, TaskSpec
from vai_backend.result_context import build_result_context, summarize_wave
from vai_backend.images import _general_canvas_stats, ImageError
from vai_backend.circuit_parsing import parse_circuit
from vai_backend.circuits import normalize


def test_native_flat_trace_near_top_passes_but_legend_only_fails():
    image = Image.new('RGB', (718, 641), 'black')
    drawing = ImageDraw.Draw(image)
    drawing.line((10, 55, 25, 55), fill='red', width=5)  # legend
    with pytest.raises(ImageError):
        _general_canvas_stats(image, 'waveform', native=True)
    drawing.line((204, 85, 685, 85), fill=(160, 0, 0))  # valid flat response
    assert _general_canvas_stats(image, 'waveform', native=True)['span_x'] > 400


def test_exact_statistics_use_all_raw_rows_including_unsampled_spike():
    rows = [[i / 1000, 9 if i == 377 else 1] for i in range(1001)]
    result = summarize_wave(rows, {'analysis': 'tran', 'unit': 'V'})
    assert result['real'] == {'min': 1, 'min_at': 0, 'max': 9, 'max_at': .377}
    assert result['rows_sampled'] is True
    assert result['mean'] == pytest.approx(1.008)
    assert result['rms'] > 1
    assert all(row[1] == 1 for row in result['sample_rows'])


def test_context_uses_registered_run_artifacts_handles_bad_data_and_is_read_only(tmp_path):
    manager = RunManager(tmp_path)
    record = RunResult(run_id='vai_context_test', status='failed', created_at=utc_now(), updated_at=utc_now(), task=TaskSpec(r_ohm=1000, c_f=1e-7))
    manager.records[record.run_id] = record
    root = tmp_path / record.run_id / 'evidence'
    root.mkdir(parents=True)
    (root / 'signals.json').write_text(json.dumps([
        {'analysis': 'ac', 'signal': 's1', 'unit': 'V', 'filename': 'ac_s0.txt'},
        {'analysis': 'ac', 'signal': 's2', 'unit': 'V', 'filename': 'ac_s1.txt'},
        {'analysis': 'ac', 'signal': 's3', 'unit': 'V', 'filename': '../secrets.txt'}]), encoding='utf-8')
    (root / 'ac_s0.txt').write_text('1 3 4\n10 0 2\n', encoding='utf-8')
    (root / 'ac_s1.txt').write_text('1 NaN 2\n', encoding='utf-8')
    (root / 'private-config.json').write_text('{"apiKey":"must-not-send"}', encoding='utf-8')
    (root / 'logs').mkdir()
    (root / 'logs/spectre.log').write_text('ERROR SPECTRE example\nAuthorization: Bearer hidden-key', encoding='utf-8')
    manager._refresh_artifacts(record)
    original = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = build_result_context(record, manager.artifact_path)
    assert result['series_count'] == 1
    assert len(result['omitted']) == 2
    assert 'must-not-send' not in result['context'] and 'hidden-key' not in result['context']
    assert json.loads(result['context'])['curves'][0]['magnitude']['max'] == 5
    assert original == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with TestClient(create_app(Settings(data_dir=tmp_path), manager)) as client:
        response = client.get('/api/v2/runs/vai_context_test/ai-context')
        assert response.status_code == 200
        assert response.json()['run_id'] == record.run_id
        assert client.get('/api/v2/runs/vai_unknown/ai-context').status_code == 404


def test_capacitor_only_opamp_feedback_warns_and_resistive_feedback_does_not():
    base = 'V1 in 0 DC 0 AC 1\nR1 in minus 1k\nC1 out minus 1n\nU1 0 minus out\n.ac 1 1meg 20\n.save V(out)'
    task = parse_circuit(base)
    assert any('未发现输出' in w for w in normalize(task)['warnings'])
    corrected = parse_circuit(base + '\nR2 out minus 10k')
    assert not any('未发现输出' in w for w in normalize(corrected)['warnings'])
