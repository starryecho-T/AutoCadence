from __future__ import annotations
import io,json,os,queue,re,shlex,subprocess,tarfile,threading,time
from pathlib import Path
from datetime import datetime,timezone
from .config import load_worker_config
from .models import TaskSpec
from .circuit_models import CircuitTask

PACKAGE=Path(__file__).resolve().parents[1]
def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')

class PipelineError(RuntimeError):
    def __init__(self,code,stage,message):
        self.code=code;self.stage=stage;super().__init__(message)

def _ssh(config):
    host=config['ssh_host']
    if not isinstance(host,str) or not re.fullmatch(r'[A-Za-z0-9_.@-]+',host) or host.startswith('-'):
        raise PipelineError('CONFIG_ERROR','upload','Invalid SSH host alias')
    args=['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=12']
    port=config.get('ssh_port',22)
    if isinstance(port,bool) or not isinstance(port,int) or not 1<=port<=65535:
        raise PipelineError('CONFIG_ERROR','upload','ssh_port must be an integer between 1 and 65535')
    if 'ssh_port' in config:args+=['-p',str(port)]
    for key,option in [('ssh_identity_file','IdentityFile'),('ssh_known_hosts_file','UserKnownHostsFile')]:
        if key not in config:continue
        value=config[key]
        if not isinstance(value,str) or any(c in value for c in '\r\n\x00') or not Path(value).is_file():
            raise PipelineError('CONFIG_ERROR','upload','Missing or invalid local file: '+key)
        args+=['-o',option+'='+str(Path(value).resolve())]
    if config.get('ssh_identity_file'):args+=['-o','IdentitiesOnly=yes']
    legacy=config.get('ssh_legacy_rsa',False)
    if not isinstance(legacy,bool):
        raise PipelineError('CONFIG_ERROR','upload','ssh_legacy_rsa must be boolean')
    if legacy:
        # Old course servers may only offer RSA/SHA-1; scoped to this connection.
        args+=['-o','HostKeyAlgorithms=+ssh-rsa','-o','PubkeyAcceptedAlgorithms=+ssh-rsa']
    return args+[host]

def _validate_config(config,run_id):
    if not re.fullmatch(r'[a-z][a-z0-9_]{5,80}',run_id):raise PipelineError('RUN_ID_INVALID','upload','Invalid run ID')
    for key in ['remote_base','environment_script','virtuoso_bin','spectre_bin','cadence_cds_lib']:
        value=config.get(key,'')
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+',value) or '..' in value.split('/'):
            raise PipelineError('CONFIG_ERROR','upload','Invalid configured path: '+key)
    if config['remote_base'] in ['/','/tmp','/home','/data/home']:
        raise PipelineError('CONFIG_ERROR','upload','remote_base must be a dedicated user directory')
    _ssh(config)

def _archive(task,run_id,config):
    memory=io.BytesIO()
    with tarfile.open(fileobj=memory,mode='w:gz') as tf:
        for path in [PACKAGE/'worker/run.py',PACKAGE/'worker/capture.py']+list((PACKAGE/'worker/templates').glob('*.il')):
            tf.add(path,arcname=path.relative_to(PACKAGE/'worker').as_posix(),recursive=False)
        remote_config={key:value for key,value in config.items() if not key.startswith('ssh_')}
        payload=json.dumps({'task':task,'run_id':run_id,'config':remote_config},ensure_ascii=True).encode()
        if task.get('template_id') == 'general_circuit':
            from .circuit_compiler import scripts
            tf.add(PACKAGE/'worker/general.py', arcname='general.py', recursive=False)
            for name, value in scripts(CircuitTask.model_validate(task)).items():
                data=value.encode('utf-8')
                item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o600
                tf.addfile(item,io.BytesIO(data))
        info=tarfile.TarInfo('input.json');info.size=len(payload);info.mode=0o600
        tf.addfile(info,io.BytesIO(payload))
    return memory.getvalue()

def _download(config,root,run_dir):
    command='tar -czf - -C '+shlex.quote(root)+' evidence'
    r=subprocess.run(_ssh(config)+[command],stdin=subprocess.DEVNULL,capture_output=True,timeout=60)
    if r.returncode:raise PipelineError('ARTIFACT_TRANSFER_FAILED','download',r.stderr.decode(errors='replace')[-1000:])
    if len(r.stdout)>40*1024*1024:raise PipelineError('ARTIFACT_LIMIT','download','Artifact archive exceeds limit')
    with tarfile.open(fileobj=io.BytesIO(r.stdout),mode='r:gz') as tf:
        total=0
        for member in tf.getmembers():
            parts=member.name.split('/')
            if parts[0]!='evidence' or any(x in ('..','') for x in parts) or member.issym() or member.islnk():
                raise PipelineError('ARTIFACT_PATH','download','Unsafe archive member')
            if member.isdir():continue
            if not member.isfile():raise PipelineError('ARTIFACT_TYPE','download','Unexpected artifact type')
            total+=member.size
            if total>80*1024*1024:raise PipelineError('ARTIFACT_LIMIT','download','Expanded artifacts exceed limit')
            dest=run_dir.joinpath(*parts);dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(tf.extractfile(member).read())

def _run_remote(config,root,run_dir,emit):
    shell='source '+shlex.quote(config['environment_script'])+' >/dev/null 2>&1; exec timeout '+str(int(config.get('run_timeout_s',600)))+' python -u '+shlex.quote(root+'/run.py')+' '+shlex.quote(root)
    args=_ssh(config)+['bash -lc '+shlex.quote(shell)]
    # No remote interaction is needed. Inheriting a desktop/server input pipe
    # can leave Windows OpenSSH waiting for input after the remote job exits.
    proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    lines=queue.Queue()
    def read():
        try:
            for line in iter(proc.stdout.readline,b''):lines.put(line)
        finally:lines.put(None)
    thread=threading.Thread(target=read,daemon=True);thread.start()
    started=time.monotonic();final=None;done=False
    with (run_dir/'evidence/remote.log').open('wb') as log:
        while not done:
            if time.monotonic()-started>config.get('run_timeout_s',600)+30:
                proc.kill();proc.wait(timeout=10)
                raise PipelineError('SSH_TIMEOUT','execution','Remote worker exceeded wall-clock timeout')
            try:line=lines.get(timeout=.5)
            except queue.Empty:continue
            if line is None:done=True;continue
            log.write(line);log.flush()
            try:item=json.loads(line)
            except (ValueError,UnicodeDecodeError):continue
            if item.get('event')=='stage':emit(item['stage'])
            elif item.get('event')=='result':final=item['result']
    rc=proc.wait(timeout=15)
    return rc,final

def execute(task_dict:dict,run_dir:Path,emit)->dict:
    model=CircuitTask if task_dict.get('template_id')=='general_circuit' else TaskSpec
    task=model.model_validate(task_dict).model_dump();run_dir=Path(run_dir).resolve()
    evidence=run_dir/'evidence';evidence.mkdir(parents=True,exist_ok=True)
    config=load_worker_config();run_id=run_dir.name;_validate_config(config,run_id)
    root=config['remote_base'].rstrip('/')+'/'+run_id
    def stage(name,fn):
        start=time.monotonic();stamp=now();emit({'name':name,'status':'running','started_at':stamp})
        try:value=fn()
        except Exception as exc:
            emit({'name':name,'status':'failed','started_at':stamp,'finished_at':now(),'elapsed_s':time.monotonic()-start,'message':str(exc)})
            if not hasattr(exc,'stage'):raise PipelineError(getattr(exc,'code','PIPELINE_ERROR'),name,str(exc)) from exc
            raise
        emit({'name':name,'status':'succeeded','started_at':stamp,'finished_at':now(),'elapsed_s':time.monotonic()-start})
        return value
    def upload():
        command='umask 077; mkdir -p '+shlex.quote(config['remote_base'])+' && mkdir '+shlex.quote(root)+' && tar -xzf - -C '+shlex.quote(root)
        r=subprocess.run(_ssh(config)+[command],input=_archive(task,run_id,config),capture_output=True,timeout=45)
        if r.returncode:raise PipelineError('SSH_UPLOAD_FAILED','upload',r.stderr.decode(errors='replace')[-1000:])
    stage('upload',upload)
    remote_error=None;rc=-1;result=None
    try:rc,result=_run_remote(config,root,run_dir,emit)
    except Exception as exc:remote_error=exc
    try:stage('download',lambda:_download(config,root,run_dir))
    except Exception:
        if remote_error:raise remote_error
        raise
    if remote_error:raise remote_error
    if not result or rc or result.get('status')!='succeeded':
        error=(result or {}).get('error') or {}
        raise PipelineError(error.get('code','REMOTE_FAILED'),error.get('stage','execution'),error.get('message','Remote process failed with exit '+str(rc)+'; see remote.log'))
    from .images import convert_and_validate
    if task.get('template_id') == 'general_circuit':
        from .circuit_analysis import analyze, generate_report
    else:
        from .analysis import analyze
        from .reporting import generate_report
    image_result=stage('image_validation',lambda:convert_and_validate(evidence, general=True) if task.get('template_id') == 'general_circuit' else convert_and_validate(evidence))
    (evidence/'image_validation.json').write_text(json.dumps(image_result,indent=2),encoding='utf-8')
    metrics=stage('validation',lambda:analyze(task,evidence))
    if task.get('template_id') == 'general_circuit' and task.get('two_port') and task['two_port']['generate_equivalent'] and metrics['two_port']['equivalent_supported']:
        from .study_analysis import finish_equivalence
        def run_equivalent():
            equivalent=json.loads((evidence/'equivalent_task.json').read_text(encoding='utf-8'))
            child_id=run_id[:65]+'_yeq'
            child_dir=evidence/'equivalent'/child_id
            child_dir.mkdir(parents=True)
            child_stages=[]
            try:
                child_result=execute(equivalent,child_dir,child_stages.append)
                finish_equivalence(task,metrics,evidence,child_result,child_dir/'evidence')
            finally:
                (evidence/'equivalent_stages.json').write_text(json.dumps(child_stages,indent=2),encoding='utf-8')
        stage('equivalent',run_equivalent)
    (evidence/'metrics.json').write_text(json.dumps(metrics,indent=2,allow_nan=False),encoding='utf-8')
    warnings=[]
    if task.get('template_id') == 'general_circuit':
        from .circuits import compile_task
        warnings.extend(compile_task(task)['warnings'])
        spectre_log='\n'.join(p.read_text(errors='replace') for p in evidence.glob('*spectre.out'))
        for line in spectre_log.splitlines():
            if re.search(r'\bWARNING\b',line,re.I) and '0 warnings' not in line.lower():
                warnings.append(line.strip()[:500])
    for log in (evidence/'logs').glob('*.log'):
        content=log.read_text(errors='replace')
        if '*WARNING*' in content or 'Qt Warning' in content:warnings.append('Frontend tool warning recorded in logs/'+log.name)
    stage('report',lambda:generate_report(task,metrics,evidence,run_id,warnings))
    for name in ['schematic_window.png','waveform_window.png','report.html','report.md','metrics.json','input.scs']:
        path=evidence/name
        if not path.is_file() or path.stat().st_size==0:raise PipelineError('ARTIFACT_MISSING','report',name+' missing')
    return {'metrics':metrics,'warnings':warnings}
