import json,time,shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from vai_backend.api import create_app
from vai_backend.config import Settings
from vai_backend.manager import RunManager
from vai_backend.models import TaskSpec
from vai_backend.pipeline import PipelineError, _validate_config
from vai_backend.parsing import parse_question
from vai_backend.analysis import analyze, AnalysisError

def wait(client,run_id):
    for _ in range(100):
        data=client.get('/api/v1/runs/'+run_id).json()
        if data['status'] in ('succeeded','failed'):return data
        time.sleep(.02)
    raise AssertionError('test job timeout')

def test_api_job_progress_artifacts_and_failure(tmp_path):
    def executor(task,root,emit):
        emit({'name':'build','status':'running'})
        if task['r_ohm']==2000:raise PipelineError('SIMULATION_FAILED','spectre','intentional test executor failure')
        (root/'evidence/result.txt').write_text('test fixture, not a simulation')
        emit({'name':'build','status':'succeeded'})
        return {'metrics':{'test_fixture':True},'warnings':[]}
    manager=RunManager(tmp_path,executor)
    with TestClient(create_app(Settings(data_dir=tmp_path),manager)) as c:
        assert c.get('/health').json()['queue']['worker_alive']
        bad=c.post('/api/v1/runs',json={'r_ohm':-1,'c_f':1e-7})
        assert bad.status_code==422 and bad.json()['error']['code']=='VALIDATION_ERROR'
        assert not manager.list()
        good=c.post('/api/v1/runs',json={'r_ohm':1000,'c_f':1e-7})
        assert good.status_code==202
        result=wait(c,good.json()['run_id']);assert result['status']=='succeeded'
        artifact=next(a for a in result['artifacts'] if a['filename']=='result.txt')
        assert c.get(artifact['url']).text=='test fixture, not a simulation'
        assert c.get('/api/v1/runs/not_found').status_code==404
        assert c.get('/api/v1/runs/'+result['run_id']+'/artifacts/invalid').status_code==404
        failed=c.post('/api/v1/runs',json={'r_ohm':2000,'c_f':1e-7}).json()
        result=wait(c,failed['run_id']);assert result['status']=='failed'
        assert result['error']['stage']=='spectre' and result['error']['code']=='SIMULATION_FAILED'
        assert any(a['kind']=='log' for a in result['artifacts'])

def test_auth_and_cors(tmp_path):
    settings=Settings(data_dir=tmp_path,api_token='test-only-token')
    with TestClient(create_app(settings)) as c:
        assert c.get('/health').status_code==200
        assert c.get('/api/v1/runs').status_code==401
        assert c.get('/api/v1/runs',headers={'Authorization':'Bearer test-only-token'}).status_code==200
        r=c.options('/api/v1/runs',headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'POST'})
        assert r.headers['access-control-allow-origin']=='http://localhost:5173'
        r=c.options('/api/v1/runs',headers={'Origin':'https://unexpected.example','Access-Control-Request-Method':'POST'})
        assert 'access-control-allow-origin' not in r.headers

def test_restart_marks_pending_failed(tmp_path):
    manager=RunManager(tmp_path)
    record=manager.submit(TaskSpec(r_ohm=1000,c_f=1e-7))
    recovered=RunManager(tmp_path).get(record.run_id)
    assert recovered.status=='failed' and recovered.error.code=='INTERRUPTED'

def test_path_validation():
    config={'ssh_host':'-bad','remote_base':'/data/home/test/vai_runs','environment_script':'/etc/profile','virtuoso_bin':'/opt/virtuoso','spectre_bin':'/opt/spectre','cadence_cds_lib':'/opt/cds.lib'}
    with pytest.raises(PipelineError):_validate_config(config,'vai_testing123')
    config['ssh_host']='school'
    config['remote_base']='/data/home/test/../other'
    with pytest.raises(PipelineError):_validate_config(config,'vai_testing123')

@pytest.mark.parametrize('changes',[{'r_ohm':0},{'c_f':float('nan')},{'template_id':'arbitrary'},{'transient':{'stop_s':.0005}},{'pulse':{'period_s':.001,'width_s':.002}},{'unknown':'reject'}])
def test_bad_tasks_rejected(changes):
    with pytest.raises(ValueError):TaskSpec.model_validate({'r_ohm':1000,'c_f':1e-7,**changes})

def test_parser_and_supported_boundaries():
    p=parse_question('设计RC低通滤波器，R=2kΩ，C=100nF。')
    assert p['task']['r_ohm']==2000 and p['task']['c_f']==pytest.approx(1e-7)
    assert p['requires_confirmation'] and p['defaults_applied']
    assert parse_question('设计高通 R=1kΩ C=100nF')['supported'] is False
    assert parse_question('低通 R=1kΩ')['task'] is None
    assert parse_question('低通 R=1kΩ R=2kΩ C=100nF')['task'] is None

def test_real_full_cycle_evidence_and_missing_samples(tmp_path):
    root=Path(__file__).resolve().parents[1]/'runs/vai_20261018_141418_21e24c15/evidence'
    if not root.is_dir():pytest.skip('Optional local real-run evidence is not bundled')
    task=json.loads((root/'task.json').read_text())
    metrics=analyze(task,root)
    assert metrics['fc_hz']==pytest.approx(1591.4121,rel=1e-5)
    assert len(metrics['pulse_measured']['fall_s'])>=2
    for name in ['ac_vdb_in.txt','ac_vdb_out.txt','tran_in.txt','tran_out.txt']:shutil.copy2(root/name,tmp_path/name)
    lines=(tmp_path/'tran_in.txt').read_text().splitlines()
    (tmp_path/'tran_in.txt').write_text('\n'.join(lines[:-1]))
    with pytest.raises(AnalysisError):analyze(task,tmp_path)
