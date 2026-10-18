"""Generate trusted SKILL/OCEAN programs from validated circuit data."""
import json
from .circuits import compile_task, render_netlist, IDEAL_OPAMP


def q(value):
    return json.dumps(value, ensure_ascii=True)


BUILD_HEADER = r'''
LIB="@LIB@"
unless(ddGetObj(LIB) ddCreateLib(LIB "@DBPATH@"))
procedure(gPin(cv name x y)
  let((net term fig)
    net=dbCreateNet(cv name)
    term=dbCreateTerm(net name "inputOutput")
    fig=dbCreateRect(cv list("pin" "drawing") list(list(x-0.03125 y-0.03125) list(x+0.03125 y+0.03125)))
    dbCreatePin(net fig name)
  )
)
procedure(gPos(master name)
  let((term bb)
    term=car(setof(tm master~>terminals equal(tm~>name name)))
    unless(term error("MISSING_TERMINAL %s" name))
    bb=car(term~>pins)~>fig~>bBox
    list((xCoord(car(bb))+xCoord(cadr(bb)))/2.0 (yCoord(car(bb))+yCoord(cadr(bb)))/2.0)
  )
)
procedure(gConnect(cv inst master name node index)
  let((point endpoint wire)
    point=dbTransformPoint(gPos(master name) inst~>transform)
    cond(
      ((member(master~>cellName list("pmos4" "nmos4" "npn" "pnp")) && member(name list("D" "S" "C" "E"))) endpoint=list(car(point) cadr(point)+if(cadr(gPos(master name))>0 then 0.5 else -0.5)))
      ((member(master~>cellName list("pmos4" "nmos4")) && equal(name "B")) endpoint=list(car(point)+0.5 cadr(point)))
      (t endpoint=list(car(point)+if(equal(name "out") then 0.5 else -0.5) cadr(point)))
    )
    wire=schCreateWire(cv "draw" "orthogonal" list(point endpoint) 0.0625 0.0625 0)
    unless(wire error("WIRE_FAILED"))
    schCreateWireLabel(cv car(wire) endpoint node "lowerCenter" "R0" "stick" 0.0625 nil)
  )
)
procedure(gWire(cv points)
  let((wire)
    wire=schCreateWire(cv "draw" "orthogonal" points 0.0625 0.0625 0)
    unless(wire error("WIRE_FAILED"))
    wire
  )
)
procedure(gBetween(cv master name t0 t1 a b)
  let((p0 p1 delta target orientation center origin inst)
    p0=gPos(master t0) p1=gPos(master t1)
    target=list(xCoord(b)-xCoord(a) yCoord(b)-yCoord(a))
    foreach(rotation list("R0" "R90" "R180" "R270")
      delta=dbTransformPoint(list(xCoord(p1)-xCoord(p0) yCoord(p1)-yCoord(p0)) list(list(0 0) rotation 1))
      when(abs(xCoord(delta)*yCoord(target)-yCoord(delta)*xCoord(target))<0.00001 && xCoord(delta)*xCoord(target)+yCoord(delta)*yCoord(target)>0 orientation=rotation)
    )
    unless(orientation error("NONAXIAL_TERMINALS"))
    center=dbTransformPoint(list((xCoord(p0)+xCoord(p1))/2 (yCoord(p0)+yCoord(p1))/2) list(list(0 0) orientation 1))
    origin=list((xCoord(a)+xCoord(b))/2-xCoord(center) (yCoord(a)+yCoord(b))/2-yCoord(center))
    inst=schCreateInst(cv master name origin orientation)
    inst
  )
)
'''


def scripts(task):
    from .circuit_studies import study_jobs
    jobs = study_jobs(task)
    t = jobs[0]['task']
    c = compile_task(task)
    from .schematic_layout import loop_layout
    loop = loop_layout(c['devices'])
    # Draw explicit conductive paths for loops, parallel branches, and buses.
    # Cadence terminal probing and emitted netlist validation remain mandatory.
    nodes = {n for d in c['devices'] for n in d['nodes']}
    rails = (len(nodes) == 2 and '0' in nodes and len(c['devices']) <= 12 and
             all(len(d['terminals']) == 2 and set(d['nodes']) == nodes for d in c['devices']))
    lines = [BUILD_HEADER]
    if any(d['type'] == 'ideal_opamp' for d in c['devices']):
        lines += [r'''
sym=dbOpenCellViewByType(LIB "ideal_opamp" "symbol" "schematicSymbol" "a")
dbCreatePolygon(sym list("device" "drawing") list(list(0 -0.5) list(0 0.5) list(1 0) list(0 -0.5)))
gPin(sym "plus" 0 0.25)
gPin(sym "minus" 0 -0.25)
gPin(sym "out" 1 0)
dbSave(sym) dbClose(sym)
cf=cdfCreateBaseCellCDF(ddGetObj(LIB "ideal_opamp"))
cf->simInfo=list(nil)
cf->simInfo->spectre=list(nil)
cf->simInfo->spectre->termOrder=list("plus" "minus" "out")
cf->simInfo->spectre->componentName="ideal_opamp"
cf->simInfo->spectre->namePrefix=""
cdfSaveCDF(cf)
stopView=dbOpenCellViewByType(LIB "ideal_opamp" "spectre" "schematicSymbol" "a")
gPin(stopView "plus" 0 0.25)
gPin(stopView "minus" 0 -0.25)
gPin(stopView "out" 1 0)
dbSave(stopView) dbClose(stopView)
''']
    lines += ['when(ddGetObj(LIB "general" "schematic") error("REFUSE_EXISTING_CELL"))',
              'cv=dbOpenCellViewByType(LIB "general" "schematic" "schematic" "a")']
    expected = []
    if rails:
        lines.append('railPins=nil')
    if not rails and not loop:
        lines.append('busPins=nil')
    for i, d in enumerate(c['devices']):
        library = 'LIB' if d['type'] == 'ideal_opamp' else '"analogLib"'
        lines += [f'master=dbOpenCellViewByType({library} {q(d["symbol"])} "symbol" "schematicSymbol" "r")',
                  'unless(master error("SYMBOL_MISSING"))']
        if rails:
            top = d['terminals'][next(j for j, node in enumerate(d['nodes']) if node != '0')]
            bottom = d['terminals'][d['nodes'].index('0')]
            lines += [f'orientation=if(yCoord(gPos(master {q(top)}))>yCoord(gPos(master {q(bottom)})) then "R0" else "R180")']
        orientation = 'orientation' if rails else '"R0"'
        if loop:
            a, b = loop['devices'][i]
            placement = f'gBetween(cv master {q(d["instance"])} {q(d["terminals"][0])} {q(d["terminals"][1])} list({a[0]} {a[1]}) list({b[0]} {b[1]}))'
        else:
            placement = f'schCreateInst(cv master {q(d["instance"])} list({i*2.0 if rails else i*4.0} 0) {orientation})'
        lines += [f'inst={placement}',
                  'unless(inst error("INSTANCE_FAILED"))']
        for prop, value in d['properties'].items():
            ptype = 'int' if isinstance(value, int) else 'string'
            val = str(value) if isinstance(value, int) else q(value)
            lines.append(f'dbReplaceProp(inst {q(prop)} "{ptype}" {val})')
        for j, (term, node) in enumerate(zip(d['terminals'], d['nodes'])):
            node = 'gnd!' if node == '0' else node
            if rails:
                lines.append(f'railPins=cons(list({q(node)} dbTransformPoint(gPos(master {q(term)}) inst~>transform)) railPins)')
            elif loop:
                p = loop['devices'][i][j]
                lines += [f'point=list({p[0]} {p[1]})',
                          f'wire=gWire(cv list(point dbTransformPoint(gPos(master {q(term)}) inst~>transform)))',
                          f'schCreateWireLabel(cv car(wire) point {q(node)} "lowerCenter" "R0" "stick" 0.0625 nil)']
            else:
                # Each terminal gets its own vertical lane. Rail crossings are
                # interior-to-interior; only the target rail has an endpoint.
                side = -1 if j % 2 == 0 else 1
                if d['type'] == 'ideal_opamp':
                    side = 1 if term == 'out' else -1
                elif d['type'] == 'pmos':
                    side = 1 if term == 'B' else -1
                elif d['type'] == 'bjt' and term == 'B':
                    side = -1
                x = i*4.0 + side*(1.0 + j*.25)
                lines += [f'point=dbTransformPoint(gPos(master {q(term)}) inst~>transform)',
                          f'endpoint=list({x} yCoord(point))',
                          'gWire(cv list(point endpoint))',
                          f'busPins=cons(list({q(node)} endpoint) busPins)']
            expected.append((d['instance'], term, node))
    lines.append('gm=dbOpenCellViewByType("analogLib" "gnd" "symbol" "schematicSymbol" "r")')
    if rails:
        live_node = next(n for n in nodes if n != '0')
        lines += [r'''
xs=mapcar(lambda((entry) xCoord(cadr(entry))) railPins)
ys=mapcar(lambda((entry) yCoord(cadr(entry))) railPins)
left=apply('min xs)-0.75 right=apply('max xs)+0.5
upper=apply('max ys)+0.5 lower=apply('min ys)-0.5
foreach(entry railPins
  point=cadr(entry)
  target=list(xCoord(point) if(equal(car(entry) "gnd!") then lower else upper))
  unless(schCreateWire(cv "draw" "orthogonal" list(point target) 0.0625 0.0625 0) error("RAIL_BRANCH_FAILED"))
)
''', f'foreach(entry list(list({q(live_node)} upper) list("gnd!" lower))',
                  '  point=list(left cadr(entry))',
                  '  wire=schCreateWire(cv "draw" "orthogonal" list(point list(right cadr(entry))) 0.0625 0.0625 0)',
                  '  unless(wire error("RAIL_FAILED"))',
                  '  schCreateWireLabel(cv car(wire) point car(entry) "lowerCenter" "R0" "stick" 0.0625 nil)',
                  ')',
                  'gp=gPos(gm car(gm~>terminals)~>name)',
                  'gi=schCreateInst(cv gm "GND0" list(left-xCoord(gp) lower-0.5-yCoord(gp)) "R0")',
                  'unless(schCreateWire(cv "draw" "orthogonal" list(list(left lower) list(left lower-0.5)) 0.0625 0.0625 0) error("GROUND_WIRE_FAILED"))']
    elif loop:
        lines += [f'gWire(cv list(list(0 0) list({loop["width"]} 0)))',
                  'gp=gPos(gm car(gm~>terminals)~>name)',
                  'gi=schCreateInst(cv gm "GND0" list(-xCoord(gp) -0.5-yCoord(gp)) "R0")',
                  'gWire(cv list(list(0 0) list(0 -0.5)))']
    else:
        for j, node in enumerate(sorted(nodes)):
            name = 'gnd!' if node == '0' else node
            y = 2 + j*.5
            lines += [f'foreach(entry busPins when(equal(car(entry) {q(name)}) gWire(cv list(cadr(entry) list(xCoord(cadr(entry)) {y})))))',
                      f'wire=gWire(cv list(list(-2 {y}) list({len(c["devices"])*4-2} {y})))',
                      f'schCreateWireLabel(cv car(wire) list(-2 {y}) {q(name)} "lowerCenter" "R0" "stick" 0.0625 nil)']
        lines += ['gp=gPos(gm car(gm~>terminals)~>name)',
                  'gi=schCreateInst(cv gm "GND0" list(-2-xCoord(gp) 1.5-yCoord(gp)) "R0")',
                  'gWire(cv list(list(-2 2) list(-2 1.5)))']
    lines += ['schCheck(cv)', 'dbSave(cv)', 'dbClose(cv)', 'println("BUILD_PASSED")', 'exit()']
    probe = ['cv=dbOpenCellViewByType("@LIB@" "general" "schematic" "schematic" "r")',
             f'unless(length(cv~>instances)=={len(c["devices"])+1} error("PROBE_INSTANCE_COUNT"))']
    for inst, term, node in expected:
        probe += [f'ii=car(setof(x cv~>instances equal(x~>name {q(inst)})))',
                  f'it=car(setof(x ii~>instTerms equal(x~>term~>name {q(term)})))',
                  f'unless(it && equal(it~>net~>name {q(node)}) error("PROBE_CONNECTIVITY {inst}/{term}"))']
    probe += ['dbClose(cv)', 'println("PROBE_RESULT=PASS")', 'exit()']
    netlist = r'''
envSetVal("asimenv.startup" "projectDir" 'string "@ROOT@/batch_netlisting")
simulator('spectre)
design("@LIB@" "general" "schematic")
resultsDir("@ROOT@/batch_results")
modelFile(list("@ROOT@/models.scs" ""))
analysis('dc)
nl=createNetlist(?recreateAll t)
unless(nl error("NETLIST_ONLY_FAILED"))
println("NETLIST_ONLY_DONE")
exit()
'''
    models = 'simulator lang=spectre\n' + c['model_text'] + '\n'
    if any(d['type'] == 'ideal_opamp' for d in c['devices']):
        models += 'ahdl_include "@ROOT@/ideal_opamp.va"\n'
    exports, manifest = [], []
    for job in jobs:
        job['compiled'] = compile_task(job['task'])
        job['netlist'] = render_netlist(job['task'],job['compiled'])
        program, entries = export_program(job['task'],job['compiled'],job['id'])
        exports.append(program)
        manifest.extend(entries)
    export = EXPORT_HEADER + '\n' + '\n'.join(exports) + '\nprintln("EXPORT_DONE")\nexit()'
    return {'compiled.json': json.dumps(c), 'build.il': '\n'.join(lines), 'probe.il': '\n'.join(probe),
            'netlist.il': netlist, 'models.scs': models, 'ideal_opamp.va': IDEAL_OPAMP,
            'expected.scs': render_netlist(task, c), 'export.il': export,
            'signals.json': json.dumps(manifest), 'jobs.json':json.dumps(jobs),
            'capture_config.json': json.dumps(capture_config(t, c))}


def expression(s, c):
    if s['type'] == 'device_parameter':
        return f'getData({q(c["instance_map"][s["component"]]+":"+s["parameter"])})'
    if s['type'] == 'current':
        part = next(p for p in c['devices'] if p['id'] == s['component'])
        terminal, sign = current_terminal(part['type'],s.get('terminal'))
        return ('-' if sign < 0 else '') + f'i({q(part["instance"]+":"+terminal)})'
    def v(node):
        n = c['node_map'][c['aliases'][node]]
        return '0' if n == '0' else f'v({q(n)})'
    return f'({v(s["p"])} - {v(s["n"])})'


EXPORT_HEADER = r'''
procedure(gExport(path wave complexData)
  let((f xv yv n value)
    f=outfile(path) unless(f error("EXPORT_OPEN_FAILED"))
    if(drIsWaveform(wave) then
      xv=drGetWaveformXVec(wave) yv=drGetWaveformYVec(wave)
      n=drVectorLength(xv)
      for(j 0 n-1
        value=drGetElem(yv j)
        if(complexData then
          fprintf(f "%.15e %.15e %.15e\n" drGetElem(xv j) real(value) imag(value))
        else fprintf(f "%.15e %.15e\n" drGetElem(xv j) value))
      )
    else
      unless(numberp(wave) error("MISSING_SIGNAL"))
      fprintf(f "0 %.15e\n" wave)
    )
    close(f)
  )
)
'''


def current_terminal(kind, requested=None):
    if kind in ('bjt','pmos'):
        return ('b' if requested == 'bulk' else requested or ('c' if kind == 'bjt' else 'd')), 1
    return ('a' if kind == 'diode' else 'p' if kind in ('voltage_source','vcvs','ccvs') else 'sink' if kind in ('current_source','vccs','cccs') else '1'), (-1 if requested == 'n' else 1)


def signal_unit(s):
    if s['type'] == 'voltage':
        return 'V'
    if s['type'] == 'current':
        return 'A'
    p = s['parameter']
    return '1' if p == 'region' else 'S' if p in ('gm','gds') else 'V' if p.startswith('v') else 'A'


def export_program(task, c, case='base'):
    batch = 'batch' if case == 'base' else 'batch_' + case
    lines, manifest = [f'openResults("@ROOT@/{batch}/psf")'], []
    for a in task['analyses']:
        kind = a['type']
        if kind != 'op':
            lines.append('selectResults("dc-dc")' if kind == 'dc' else f"selectResults('{kind})")
        for i, s in enumerate(task['signals']):
            filename = ('' if case == 'base' else case+'_') + f'{kind}_s{i}.txt'
            if kind != 'op':
                lines.append(f'gExport("@ROOT@/evidence/{filename}" {expression(s,c)} {"t" if kind == "ac" else "nil"})')
            manifest.append({'case':case, 'analysis': kind, 'signal': s['id'], 'filename': filename, 'unit': signal_unit(s)})
    return '\n'.join(lines), manifest


def capture_config(task, c):
    kind = next((k for k in ('tran', 'ac', 'dc') if any(a['type'] == k for a in task['analyses'])), 'op')
    # OP values are shown as a flat two-point trace, explicitly labeled operating point.
    exprs = [expression(s, c) for s in task['signals']]
    if kind == 'ac':
        exprs = [f'mag({x})' for x in exprs]
    return {'cell': 'general', 'analysis': kind, 'expressions': exprs,
            'labels': [s['id'] + (' [AC magnitude]' if kind == 'ac' else ' [operating point]' if kind == 'op' else '') for s in task['signals']]}
