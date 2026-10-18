"""Audit saved real study evidence and create a compact reproducible summary."""
import hashlib
import json
import sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from vai_backend.circuit_examples import EXAMPLES
from vai_backend.circuit_analysis import read_wave
from vai_backend.study_analysis import compare_curves

KEYS=['controlled_sources','bjt_transfer','pnp_bias','pmos_families','pmos_ground_reference','common_base_y','bjt_biased_y','parameter_comparison']


def latest(key):
    for path in sorted((ROOT/'runs').glob('vai_general_'+key+'_*/regression_result.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        value=json.loads(path.read_text(encoding='utf-8'))
        if value.get('case')==key and value.get('status')=='PASS':
            return path.parent/'evidence',value
    raise RuntimeError('No successful real evidence for '+key)


def summarize():
    cases=[]
    for key in KEYS:
        evidence,result=latest(key);metrics=result['metrics']
        assert metrics['validation_status']==metrics['requirements_status']=='PASS'
        protection=json.loads((evidence/'protection.json').read_text(encoding='utf-8'))
        assert protection['unchanged']
        assert json.loads((evidence/'netlist_checks.json').read_text())['status']=='PASS'
        extra={}
        if key.startswith('pmos_'):
            expected_vsg={'base':2,'s000':1,'s001':1.5,'s002':2,'s003':2.5}
            checks=[]
            for cid,vsg in expected_vsg.items():
                signal=('' if cid=='base' else cid+'.')+'dc.s1'
                found=metrics['signals'][signal]['final_real']
                target=-.5*1e-4*10*(vsg-.7)**2*(1+.02*5)
                assert abs(found-target)<1e-10, (key,cid,found,target)
                checks.append({'case':cid,'vsg_v':vsg,'vsd_v':5,'current_a':found,'mos1_square_law_a':target,'absolute_error_a':abs(found-target),'status':'PASS'})
            extra['independent_mos1_checks']=checks
        if key=='common_base_y':
            target=[[.04101,-.00001],[-.04001,.00001]]
            found=metrics['two_port']['reference_matrix']
            assert all(abs(found[i][j]['real']-target[i][j])<1e-9 and abs(found[i][j]['imag'])<1e-12 for i in range(2) for j in range(2))
        if metrics.get('two_port'):
            assert metrics['two_port']['equivalence']['status']=='PASS'
            extra['two_port']={k:v for k,v in metrics['two_port'].items() if k!='sweep'}
        if metrics.get('bjt_transfer'):extra['bjt_transfer']=metrics['bjt_transfer']
        cases.append({'case':key,'label':EXAMPLES[key][0],'run_id':result['run_id'],'status':'PASS',
            'remote_eda_executed':True,'protected_unchanged':True,'protected_files_checked':protection['files_checked'],
            'numerical_cases':len(metrics['cases']),'measurements':metrics['measurements'],'comparisons':metrics.get('comparisons',[]),
            'hashes':{name:hashlib.sha256((evidence/name).read_bytes()).hexdigest() for name in ['input.scs','jobs.json','provenance.json','schematic_window.png','waveform_window.png','metrics.json']},**extra})
    first,_=latest('pmos_families');second,_=latest('pmos_ground_reference')
    comparisons=[]
    for cid in ['base','s000','s001','s002','s003']:
        prefix='' if cid=='base' else cid+'_'
        a=read_wave(first/(prefix+'dc_s0.txt'),False);b=read_wave(second/(prefix+'dc_s0.txt'),False)
        checks=compare_curves([[round(r[0]-5,10),r[1]] for r in b],[[round(r[0],10),r[1]] for r in a],rtol=1e-5,atol=1e-10)
        assert checks['status']=='PASS'
        comparisons.append({'case':cid,**checks})
    reference={'source_reference_run':first.parent.name,'ground_reference_run':second.parent.name,
        'coordinate_transform':'VSD=-VD (source reference); VSD=5-VD (ground reference). Same VSG and VSD at each comparison point.', 'checks':comparisons}
    (ROOT/'docs/pmos_reference_comparison.json').write_text(json.dumps(reference,indent=2)+'\n',encoding='utf-8')
    summary={'status':'PASS','checked_at':datetime.now(timezone.utc).isoformat(),'engine':'Cadence IC617 / Spectre MMSIM151',
        'mode':'Audit of actual saved EDA runs; no fixture-generated numerical results','cases_passed':len(cases),
        'pmos_reference_comparison_status':'PASS','cases':cases}
    (ROOT/'docs/study_regression_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'PASS','real_cases':len(cases),'mos1_targets':'PASS','pmos_reference_comparison':'PASS'}))


if __name__=='__main__':summarize()
