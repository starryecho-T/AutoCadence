"""Generic execution branch. Keep compatible with the server's Python 2.6."""
from __future__ import print_function
import json
import os
import re
import shutil


MODEL_PLACEHOLDER = '@CMN018_MODEL_FILE@'
MODEL_FILENAME = 'cmn018_gp2a_5v_v1d4.scs'
USAGE_FILENAME = 'cmn018_gp2a_5v_v1d4_usage.scs'


def resolve_model_file(config, compiled, error_class):
    """Require the administrator-installed model deck before opening Cadence."""
    sections = compiled.get('pdk_sections', [])
    if not sections:
        return None
    path = config.get('cmn018_model_file', '')
    if not path or not re.match(r'^/[A-Za-z0-9_./-]+$', path) or '..' in path.split('/') or os.path.basename(path) != MODEL_FILENAME:
        raise error_class('CMN018_NOT_CONFIGURED', 'Set cmn018_model_file to the server-local ' + MODEL_FILENAME)
    usage = os.path.join(os.path.dirname(path), USAGE_FILENAME)
    if not os.path.isfile(path) or not os.access(path, os.R_OK) or not os.path.isfile(usage) or not os.access(usage, os.R_OK):
        raise error_class('CMN018_MODEL_MISSING', 'The configured CMN018 model file and sibling usage file must both be readable')
    deck = open(path).read()
    wrapper = open(usage).read()
    for section in sections:
        if not re.search(r'^\s*section\s+' + re.escape(section) + r'\s*$', deck, re.M | re.I):
            raise error_class('CMN018_SECTION_MISSING', 'CMN018 deck has no section ' + section)
        if not re.search(r'^\s*include\s+"' + re.escape(MODEL_FILENAME) + r'"\s+section\s*=\s*' + re.escape(section) + r'\s*$', wrapper, re.M | re.I):
            raise error_class('CMN018_SECTION_MISSING', 'CMN018 usage file has no section ' + section)
    return path, usage


def numeric(raw):
    m = re.match(r'^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)([A-Za-z]*)$', raw)
    scales = {'': 1, 'T': 1e12, 'G': 1e9, 'M': 1e6, 'meg': 1e6, 'k': 1e3, 'm': 1e-3, 'u': 1e-6, 'n': 1e-9, 'p': 1e-12, 'f': 1e-15, 'a': 1e-18}
    if not m or m.group(2) not in scales:
        raise ValueError('Invalid numeric value: ' + raw)
    return float(m.group(1)) * scales[m.group(2)]


def validate_netlist(text, compiled):
    flat = text.replace('\\\n', ' ')
    actual = {}
    for name, pins, master, tail in re.findall(r'^\s*([A-Za-z]\w*)\s*\(([^)]+)\)\s+(\w+)([^\n]*)', flat, re.M):
        if name in actual:
            raise ValueError('Duplicate generated instance: ' + name)
        params = dict(re.findall(r'(\w+)\s*=\s*(\[[^\]]*\]|[^\s]+)', tail))
        actual[name] = (pins.split(), master, params)
    if set(actual) != set(d['instance'] for d in compiled['devices']):
        raise ValueError('Generated instance set differs from confirmed circuit')
    for d in compiled['devices']:
        pins, master, params = actual[d['instance']]
        if pins != d['nodes'] or master != d['master']:
            raise ValueError(d['id'] + ': generated topology or device model mismatch')
        for key, expected in d['parameters'].items():
            raw = params.get(key)
            if raw is None and expected == 0:
                continue  # Spectre defaults for mag/phase/DC and delay are zero.
            if raw is None:
                raise ValueError(d['id'] + ': missing generated parameter ' + key)
            if isinstance(expected, list):
                found = [numeric(v) for v in raw.strip('[]').split()]
                equal = len(found) == len(expected) and all(abs(a-b) <= max(1e-18, abs(b)*1e-10) for a, b in zip(found, expected))
            elif isinstance(expected, (int, float)):
                equal = abs(numeric(raw)-expected) <= max(1e-18, abs(expected)*1e-10)
            else:
                equal = raw.strip('"') == expected
            if not equal:
                raise ValueError(d['id'] + ': generated parameter mismatch ' + key)
    return {'status': 'PASS', 'devices_checked': len(actual), 'topology_and_parameters_match': True}


def execute(runner, error_class):
    from run import write, save, sha
    r = runner
    r.begin('preflight')
    compiled = json.load(open(os.path.join(r.root, 'compiled.json')))
    model_files = resolve_model_file(r.config, compiled, error_class)
    if model_files:
        r.config['protected_files'] = list(r.config.get('protected_files', [])) + list(model_files)
    r.protect()
    for k in ['virtuoso_bin', 'spectre_bin', 'cadence_cds_lib']:
        if not os.path.isfile(r.config[k]):
            raise error_class('ENVIRONMENT_MISSING', k + ' not found')
    values = {'LIB': r.run_id, 'ROOT': r.root, 'DBPATH': os.path.join(r.root, 'db', r.run_id)}
    for name in ['build.il', 'probe.il', 'netlist.il', 'models.scs', 'export.il']:
        text = open(os.path.join(r.root, name)).read()
        for key, value in values.items():
            text = text.replace('@' + key + '@', value)
        if model_files:
            text = text.replace(MODEL_PLACEHOLDER, model_files[0])
        write(os.path.join(r.root, name), text)
        write(os.path.join(r.evidence, name), text)
    write(os.path.join(r.root, 'cds.lib'), 'INCLUDE ' + r.config['cadence_cds_lib'] + '\n')
    for name in ['compiled.json', 'signals.json', 'jobs.json', 'ideal_opamp.va']:
        shutil.copy2(os.path.join(r.root, name), os.path.join(r.evidence, name))
    r.end()
    r.ocean('build', 'build.il', 'BUILD_PASSED')
    r.ocean('probe', 'probe.il', 'PROBE_RESULT=PASS')
    r.ocean('netlist', 'netlist.il', 'NETLIST_ONLY_DONE')
    r.begin('netlist_validation')
    matches = []
    for directory, ds, fs in os.walk(os.path.join(r.root, 'batch_netlisting')):
        if 'input.scs' in fs:
            matches.append(os.path.join(directory, 'input.scs'))
    if len(matches) != 1:
        raise error_class('NETLIST_COUNT', 'Expected exactly one Cadence netlist')
    original = matches[0]; source = open(original).read()
    write(os.path.join(r.evidence, 'netlist_original.scs'), source)
    try:
        checks = validate_netlist(source, compiled)
    except ValueError as exc:
        raise error_class('NETLIST_MISMATCH', str(exc))
    save(os.path.join(r.evidence, 'netlist_checks.json'), checks)
    jobs = json.load(open(os.path.join(r.root,'jobs.json')))
    provenance = []
    for job in jobs:
        cid = job['id']; prefix = '' if cid == 'base' else cid+'_'
        batch = os.path.join(r.root, 'batch' if cid == 'base' else 'batch_'+cid)
        os.mkdir(batch)
        executed = job['netlist'].replace('"ideal_opamp.va"', '"' + r.root + '/ideal_opamp.va"')
        if model_files:
            executed = executed.replace(MODEL_PLACEHOLDER, model_files[0])
        validate_netlist(executed,job['compiled'])
        write(os.path.join(batch,'input.scs'),executed)
        write(os.path.join(r.evidence,prefix+'input.scs'),executed)
        provenance.append({'case':cid,'parameters':job['parameters'],'executed_sha256':sha(os.path.join(batch,'input.scs'))})
    save(os.path.join(r.evidence, 'provenance.json'), {'run_id': r.run_id, 'source_sha256': sha(original), 'executed_sha256':provenance[0]['executed_sha256'], 'cases':provenance, 'source': 'Cadence baseline topology/parameters verified; subsequent bounded parameter variants and explicit two-port test benches generated from validated IR.'})
    r.end()
    r.begin('spectre')
    for job in jobs:
        cid = job['id']; prefix = '' if cid == 'base' else cid+'_'
        batch = os.path.join(r.root, 'batch' if cid == 'base' else 'batch_'+cid)
        r.process('spectre' if cid == 'base' else 'spectre_'+cid, [r.config['spectre_bin'], 'input.scs', '+escchars', '-format', 'psfascii', '-raw', 'psf', '+log', 'spectre.out'], cwd=batch,grouped=True)
        log = open(os.path.join(batch, 'spectre.out')).read()
        shutil.copy2(os.path.join(batch,'spectre.out'),os.path.join(r.evidence,prefix+'spectre.out'))
        if 'spectre completes with 0 errors' not in log:
            raise error_class('SPECTRE_ERRORS',cid+': Spectre did not complete without errors')
        if any(a['type']=='op' for a in job['task']['analyses']):
            export_operating_point(r,job['compiled'],error_class,job['task'],batch,prefix)
    r.end()
    r.ocean('export', 'export.il', 'EXPORT_DONE')
    r.begin('capture')
    from capture import capture
    result = capture(r.root, r.run_id, r.env, r.config['virtuoso_bin'], timeout=100)
    if not result.get('ok'):
        raise error_class('CAPTURE_FAILED', result.get('error', 'Screenshot capture failed'))
    r.end()


def current_terminal(kind, requested):
    if kind in ('bjt','pmos','nmos'):
        return ('b' if requested == 'bulk' else requested or ('c' if kind == 'bjt' else 'd')), 1
    return ('a' if kind == 'diode' else 'p' if kind in ('voltage_source','vcvs','ccvs') else 'sink' if kind in ('current_source','vccs','cccs') else '1'), (-1 if requested == 'n' else 1)


def export_operating_point(r, compiled, error_class, task=None, batch=None, prefix=''):
    """Read named scalar PSF directly, independent of OCEAN's DC aliases."""
    from run import write
    task = task or r.task
    path = os.path.join(batch or os.path.join(r.root,'batch'),'psf','dcOp.dc')
    source = open(path).read()
    shutil.copy2(path,os.path.join(r.evidence,prefix+'operating_point.psfascii'))
    values = dict((name,float(value)) for name,value in re.findall(r'^"([^"\n]+)" "[^"\n]+" ([+\-\d.eE]+)', source, re.M))
    def voltage(node):
        name = compiled['node_map'][compiled['aliases'][node]]
        return 0.0 if name == '0' else values[name]
    for i,s in enumerate(task['signals']):
        try:
            if s['type']=='voltage':
                value = voltage(s['p'])-voltage(s['n'])
            elif s['type']=='device_parameter':
                value = values[compiled['instance_map'][s['component']]+':'+s['parameter']]
            else:
                part = next(d for d in compiled['devices'] if d['id']==s['component'])
                terminal, sign = current_terminal(part['type'],s.get('terminal'))
                value = sign * values[part['instance']+':'+terminal]
        except KeyError:
            raise error_class('MISSING_SIGNAL','Operating point signal missing: '+s['id'])
        write(os.path.join(r.evidence,prefix+'op_s%d.txt'%i),'0 %.15e\n'%value)
