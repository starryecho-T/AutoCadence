from __future__ import print_function
import os,sys,json,time,subprocess,signal,re,hashlib,shutil,traceback,math

def utc(): return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
def write(path,data):
    if isinstance(data,unicode):data=data.encode('utf-8')
    f=open(path,'w');f.write(data);f.close()
def save(path,obj):write(path,json.dumps(obj,indent=2,sort_keys=True))
def sha(path):
    h=hashlib.sha256();f=open(path,'rb')
    while True:
        b=f.read(1048576)
        if not b:break
        h.update(b)
    f.close();return h.hexdigest()

class WorkerError(Exception):
    def __init__(self,code,message):self.code=code;Exception.__init__(self,message)

class Runner(object):
    def __init__(self,root):
        self.root=root
        payload=json.load(open(os.path.join(root,'input.json')))
        self.task=payload['task'];self.config=payload['config'];self.run_id=payload['run_id']
        self.env=os.environ.copy();self.env.pop('DISPLAY',None)
        self.env['PATH']=os.path.dirname(self.config['spectre_bin'])+':'+self.env.get('PATH','/usr/bin:/bin')
        self.stages=[];self.current='preflight';self.before={}
        self.evidence=os.path.join(root,'evidence');self.logs=os.path.join(root,'logs')
        for d in [self.evidence,self.logs,os.path.join(root,'db')]:os.mkdir(d)
        save(os.path.join(self.evidence,'task.json'),self.task)
    def event(self,entry):
        print(json.dumps({'event':'stage','stage':entry}));sys.stdout.flush()
    def begin(self,name):
        self.current=name;self.entry={'name':name,'status':'running','started_at':utc()};self.started=time.time()
        self.event(self.entry)
    def end(self,code=0,message=None):
        self.entry.update({'status':'succeeded' if code==0 else 'failed','finished_at':utc(),'elapsed_s':round(time.time()-self.started,3),'exit_code':code})
        if message:self.entry['message']=message
        self.stages.append(dict(self.entry));save(os.path.join(self.evidence,'stages.json'),self.stages);self.event(self.entry)
    def process(self,name,args,marker=None,cwd=None):
        self.begin(name);logpath=os.path.join(self.logs,name+'.log')
        f=open(logpath,'w');null=open('/dev/null','r')
        p=subprocess.Popen(args,cwd=cwd or self.root,env=self.env,stdin=null,stdout=f,stderr=subprocess.STDOUT,preexec_fn=os.setsid)
        timed=False
        while p.poll() is None:
            if time.time()-self.started>self.config.get('stage_timeout_s',120):
                timed=True
                try:os.killpg(p.pid,signal.SIGTERM)
                except OSError:pass
                time.sleep(.5)
                if p.poll() is None:
                    try:os.killpg(p.pid,signal.SIGKILL)
                    except OSError:pass
                break
            time.sleep(.15)
        rc=p.wait();f.close();null.close();text=open(logpath).read()
        self.entry['log_path']='logs/'+name+'.log'
        bad=timed or rc!=0 or (marker is not None and marker not in text) or '*Error*' in text or 'ASSERT_FAIL' in text or 'PROBE_FAIL ' in text
        if bad:
            self.end(rc if rc else 1,'timeout' if timed else 'process or required marker failed')
            raise WorkerError('STAGE_TIMEOUT' if timed else 'PROCESS_FAILED',name+' failed; see '+self.entry['log_path'])
        self.end(rc);return text
    def ocean(self,name,filename,marker):
        if self.task.get('template_id') == 'general_circuit':
            guarded='guarded_'+filename
            write(os.path.join(self.root,guarded),'unless(errset(load('+json.dumps(os.path.join(self.root,filename))+') t) exit(1))\nexit(1)\n')
            filename=guarded
        return self.process(name,[self.config['virtuoso_bin'],'-64','-ocean','-nograph','-nocdsinit','-restore',os.path.join(self.root,filename),'-log',os.path.join(self.logs,name+'.cds.log')],marker)
    def protect(self):
        files=self.config.get('protected_files',[])
        absent=[p for p in files if not os.path.isfile(p)]
        if absent:raise WorkerError('PROTECTED_FILE_MISSING','A configured protected file is missing')
        self.before=dict((p,sha(p)) for p in files)
        save(os.path.join(self.evidence,'protected_before.json'),self.before)
    def render(self):
        t=self.task;p=t['pulse'];a=t['ac'];tr=t['transient']
        values={'LIB':self.run_id,'ROOT':self.root,'DBPATH':os.path.join(self.root,'db',self.run_id),'R':t['r_ohm'],'C':t['c_f'],'LOW':p['low_v'],'HIGH':p['high_v'],'PERIOD':p['period_s'],'WIDTH':p['width_s'],'RISE':p['rise_s'],'FALL':p['fall_s'],'DELAY':p['delay_s'],'ACMAG':1,'AC_START':a['start_hz'],'AC_STOP':a['stop_hz'],'AC_POINTS':a['points_per_decade'],'TRAN_STOP':tr['stop_s'],'MAX_STEP':tr['max_step_s']}
        values=dict((k,('%.15g'%v) if isinstance(v,(int,float)) else v) for k,v in values.items())
        for name in ['build','probe','netlist']:
            text=open(os.path.join(self.root,'templates',name+'.il')).read().decode('utf-8')
            for k,v in values.items():text=text.replace('@'+k+'@',v)
            if re.search(r'@[A-Z_]+@',text):raise WorkerError('RENDER_ERROR','Unresolved template variable')
            write(os.path.join(self.root,name+'.il'),text)
            write(os.path.join(self.evidence,name+'.il'),text)
        write(os.path.join(self.root,'cds.lib'),'INCLUDE '+self.config['cadence_cds_lib']+'\n')
    def validate_netlist(self,text):
        flat=' '.join(text.replace('\\\n',' ').split());t=self.task;p=t['pulse'];a=t['ac'];tr=t['transient']
        def numeric(raw):
            m=re.match(r'^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)([a-zA-Z]*)$',raw)
            if not m:raise ValueError(raw)
            scales={'':1,'T':1e12,'G':1e9,'M':1e6,'meg':1e6,'k':1e3,'m':1e-3,'u':1e-6,'n':1e-9,'p':1e-12,'f':1e-15}
            return float(m.group(1))*scales[m.group(2)]
        checks={}
        for name,pattern,expected in [
            ('R',r'R1 \(vin out\) resistor r=([^ ]+)',t['r_ohm']),
            ('C',r'C1 \(out 0\) capacitor c=([^ ]+)',t['c_f']),
            ('period',r'\bperiod=([^ ]+)',p['period_s']),('width',r'\bwidth=([^ ]+)',p['width_s']),
            ('rise',r'\brise=([^ ]+)',p['rise_s']),('fall',r'\bfall=([^ ]+)',p['fall_s']),
            ('delay',r'\bdelay=([^ ]+)',p['delay_s']),('low',r'\bval0=([^ ]+)',p['low_v']),('high',r'\bval1=([^ ]+)',p['high_v']),
            ('tran_stop',r'tran tran stop=([^ ]+)',tr['stop_s']),('max_step',r'\bmaxstep=([^ ]+)',tr['max_step_s']),
            ('ac_start',r'ac ac start=([^ ]+)',a['start_hz']),('ac_stop',r'ac ac start=[^ ]+ stop=([^ ]+)',a['stop_hz'])]:
            match=re.search(pattern,flat)
            actual=numeric(match.group(1)) if match else None
            checks[name]={'expected':expected,'actual':actual,'pass':actual is not None and abs(actual-expected)<=max(abs(expected)*1e-9,1e-18)}
        checks['source']={'pass':self.run_id in text}
        checks['voltage_topology']={'pass':'V1 (vin 0) vsource' in flat and 'type=pulse' in flat}
        save(os.path.join(self.evidence,'netlist_checks.json'),checks)
        if not all(x['pass'] for x in checks.values()):raise WorkerError('NETLIST_MISMATCH','Generated netlist does not match requested parameters')
    def execute(self):
        if self.task.get('template_id') == 'general_circuit':
            from general import execute
            return execute(self, WorkerError)
        self.begin('preflight');self.protect()
        for k in ['virtuoso_bin','spectre_bin','cadence_cds_lib']:
            if not os.path.isfile(self.config[k]):raise WorkerError('ENVIRONMENT_MISSING',k+' not found')
        self.render();self.end()
        self.ocean('build','build.il','BUILD_PASSED')
        self.ocean('probe','probe.il','PROBE_RESULT=PASS')
        self.ocean('netlist','netlist.il','NETLIST_ONLY_DONE')
        self.begin('netlist_validation')
        matches=[]
        for d,ds,fs in os.walk(os.path.join(self.root,'batch_netlisting')):
            if 'input.scs' in fs:matches.append(os.path.join(d,'input.scs'))
        if len(matches)!=1:raise WorkerError('NETLIST_COUNT','Expected exactly one generated netlist')
        original=matches[0];text=open(original).read();self.validate_netlist(text)
        batch=os.path.join(self.root,'batch');os.mkdir(batch)
        normalized=re.sub(r'sensfile="[^"]*"','sensfile="sens.output"',text)
        write(os.path.join(batch,'input.scs'),normalized)
        write(os.path.join(self.evidence,'netlist_original.scs'),text);write(os.path.join(self.evidence,'input.scs'),normalized)
        save(os.path.join(self.evidence,'provenance.json'),{'run_id':self.run_id,'source':original,'source_sha256':sha(original),'executed_sha256':sha(os.path.join(batch,'input.scs')),'allowed_change':'sensfile path only'})
        self.end()
        self.process('spectre',[self.config['spectre_bin'],'input.scs','+escchars','-format','psfascii','-raw','psf','+log','spectre.out'],cwd=batch)
        s=open(os.path.join(batch,'spectre.out')).read();shutil.copy2(os.path.join(batch,'spectre.out'),os.path.join(self.evidence,'spectre.out'))
        if 'spectre completes with 0 errors' not in s:raise WorkerError('SPECTRE_ERRORS','Spectre completion audit not successful')
        export=r'''procedure(vaiExport(path wave)
  let((f xv yv n i)
    unless(wave error("MISSING_WAVEFORM"))
    xv=drGetWaveformXVec(wave) yv=drGetWaveformYVec(wave)
    n=drVectorLength(xv) unless(n>1 error("EMPTY_WAVEFORM"))
    f=outfile(path) unless(f error("EXPORT_OPEN_FAILED"))
    for(i 0 n-1 fprintf(f "%.15e %.15e\n" drGetElem(xv i) drGetElem(yv i)))
    close(f)
  )
)
openResults("@ROOT@/batch/psf")
selectResults('ac)
vaiExport("@EVIDENCE@/ac_vdb_out.txt" db20(v("out")))
vaiExport("@EVIDENCE@/ac_vdb_in.txt" db20(v("vin")))
selectResults('tran)
vaiExport("@EVIDENCE@/tran_out.txt" v("out"))
vaiExport("@EVIDENCE@/tran_in.txt" v("vin"))
println("EXPORT_DONE")
exit()
'''.replace('@ROOT@',self.root).replace('@EVIDENCE@',self.evidence)
        write(os.path.join(self.root,'export.il'),export);write(os.path.join(self.evidence,'export.il'),export)
        self.ocean('export','export.il','EXPORT_DONE')
        for fn in ['ac_vdb_in.txt','ac_vdb_out.txt','tran_in.txt','tran_out.txt']:
            if not os.path.isfile(os.path.join(self.evidence,fn)) or os.path.getsize(os.path.join(self.evidence,fn))<100:raise WorkerError('MISSING_DATA',fn+' is missing or empty')
        self.begin('capture')
        from capture import capture
        result=capture(self.root,self.run_id,self.env,self.config['virtuoso_bin'],timeout=100)
        if not result.get('ok'):raise WorkerError('CAPTURE_FAILED',str(result.get('error','Capture did not succeed')))
        self.end()
    def finish(self,error=None):
        after=dict((p,sha(p)) for p in self.before if os.path.isfile(p))
        unchanged=after==self.before
        save(os.path.join(self.evidence,'protection.json'),{'unchanged':unchanged,'files_checked':len(self.before),'before':self.before,'after':after})
        if not unchanged:error=WorkerError('PROTECTED_FILE_CHANGED','Protected file hash changed')
        if error:
            if self.entry.get('status')=='running':self.end(1,str(error))
            status={'status':'failed','error':{'code':getattr(error,'code','WORKER_ERROR'),'stage':self.current,'message':str(error)}}
        else:status={'status':'succeeded','error':None}
        status.update({'run_id':self.run_id,'stages':self.stages,'protected_unchanged':unchanged})
        save(os.path.join(self.evidence,'worker_result.json'),status)
        dest=os.path.join(self.evidence,'logs')
        if not os.path.exists(dest):shutil.copytree(self.logs,dest)
        print(json.dumps({'event':'result','result':status}));sys.stdout.flush()
        return 1 if error else 0

if __name__=='__main__':
    runner=Runner(os.path.abspath(sys.argv[1]));error=None
    try:runner.execute()
    except Exception as exc:
        error=exc;write(os.path.join(runner.logs,'exception.log'),traceback.format_exc())
    sys.exit(runner.finish(error))
