"""Real Cadence/Spectre regressions, never fixtures. Uses remote EDA licenses."""
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vai_backend.circuit_examples import EXAMPLES
from vai_backend.circuit_parsing import parse_circuit
from vai_backend.circuit_models import CircuitTask
from vai_backend.pipeline import execute


def run_case(key):
    task = parse_circuit(EXAMPLES[key][1]).model_dump()
    # Independent analytic/reference targets, evaluated on full numeric exports.
    measures = {
        'divider': [('voltage','op','s1','final','real',None,4.9999,5.0001), ('current','op','s2','final','real',None,.004999,.005001)],
        'divider_dc': [('voltage','op','s1','final','real',None,4.9999,5.0001), ('sweep_end','dc','s1','final','real',None,-1e-9,1e-9)],
        'inverting': [('gain','ac','s2','at','magnitude',1000,1.9999,2.0001), ('feedback','tran','s3','max','magnitude',None,0,1e-6)],
        'rc_highpass': [('low_frequency','ac','s2','at','magnitude',10,0,.01), ('high_frequency','ac','s2','final','magnitude',None,.999,1.001)],
        'rlc': [('dc_limit','ac','s1','at','magnitude',10,.99,1.01)],
        'rectifier': [('charge','tran','s2','max','real',None,4,5), ('blocking','tran','s2','min','real',None,-.001,.001)],
        'diode_iv': [('forward','dc','s2','final','real',None,.003,.006)],
        'current_rl': [('inductor_current','tran','s2','max','real',None,.009,.011)],
        'rl_initial': [('initial_current','tran','s2','at','real',0,.00999,.01001), ('decay','tran','s2','final','real',None,0,1e-6)],
        'floating_cap': [('initial_voltage','tran','s1','at','real',0,.9999,1.0001), ('positive_node','tran','s2','at','real',0,.4999,.5001), ('negative_node','tran','s3','at','real',0,-.5001,-.4999), ('decay','tran','s1','final','real',None,0,.001)],
        'pwl_cap': [('initial_voltage','tran','output','at','real',0,.9999,1.0001), ('discharge','tran','output','final','real',None,0,.2)],
    }
    task['measurements'] = [{'id':id,'analysis':a,'signal':s,'operation':op,'representation':rep,'at':at,'minimum':lo,'maximum':hi} for id,a,s,op,rep,at,lo,hi in measures[key]]
    task = CircuitTask.model_validate(task).model_dump()
    run_id = 'vai_general_'+key+'_'+uuid.uuid4().hex[:10]
    root = Path(__file__).resolve().parents[1]/'runs'/run_id
    root.mkdir()
    print(json.dumps({'case':key,'run_id':run_id}),flush=True)
    try:
        result = execute(task,root,lambda e:print(key+' '+e['name']+' '+e['status']+(' '+e['message'] if e.get('message') else ''),flush=True))
        status = 'PASS' if result['metrics']['requirements_status'] == 'PASS' else 'FAIL'
        result = {'case':key,'run_id':run_id,'status':status,**result}
    except Exception as e:
        result = {'case':key,'run_id':run_id,'status':'FAIL','error':str(e),'stage':getattr(e,'stage','unknown')}
    (root/'regression_result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'case':key,'status':result['status'],'error':result.get('error')}),flush=True)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',action='append',choices=list(EXAMPLES))
    a = p.parse_args()
    results = [run_case(key) for key in (a.case or EXAMPLES)]
    raise SystemExit(0 if all(r['status']=='PASS' for r in results) else 1)
