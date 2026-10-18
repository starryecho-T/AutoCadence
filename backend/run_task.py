import argparse,json,sys,time,uuid
from pathlib import Path
from vai_backend.models import TaskSpec
from vai_backend.pipeline import execute

p=argparse.ArgumentParser(description='Run one real Virtuoso task from JSON')
p.add_argument('task');p.add_argument('--run-id');p.add_argument('--output',default=str(Path(__file__).parent/'runs'))
a=p.parse_args();task=TaskSpec.model_validate_json(Path(a.task).read_text(encoding='utf-8')).model_dump()
run_id=a.run_id or 'vai_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
root=Path(a.output)/run_id;root.mkdir(parents=True,exist_ok=False)
try:
    result=execute(task,root,lambda e:print(json.dumps(e,ensure_ascii=True),flush=True))
    (root/'cli_result.json').write_text(json.dumps({'run_id':run_id,'status':'succeeded',**result},ensure_ascii=False,indent=2),encoding='utf-8')
    print('RUN_SUCCEEDED '+str(root))
except Exception as exc:
    (root/'cli_result.json').write_text(json.dumps({'run_id':run_id,'status':'failed','code':getattr(exc,'code','ERROR'),'stage':getattr(exc,'stage','execution'),'message':str(exc)},ensure_ascii=False,indent=2),encoding='utf-8')
    print('RUN_FAILED '+str(root)+' '+str(exc));raise
