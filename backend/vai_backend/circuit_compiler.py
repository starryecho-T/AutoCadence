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
    endpoint=list(car(point)+if(equal(name "out") then 0.5 else -0.5) cadr(point))
    wire=schCreateWire(cv "draw" "orthogonal" list(point endpoint) 0.0625 0.0625 0)
    unless(wire error("WIRE_FAILED"))
    schCreateWireLabel(cv car(wire) endpoint node "lowerCenter" "R0" "stick" 0.0625 nil)
  )
)
'''


def scripts(task):
    t = task.model_dump()
    c = compile_task(task)
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
    for i, d in enumerate(c['devices']):
        library = 'LIB' if d['type'] == 'ideal_opamp' else '"analogLib"'
        lines += [f'master=dbOpenCellViewByType({library} {q(d["symbol"])} "symbol" "schematicSymbol" "r")',
                  'unless(master error("SYMBOL_MISSING"))',
                  f'inst=schCreateInst(cv master {q(d["instance"])} list({i%4*4.0} {-(i//4)*2.5}) "R0")',
                  'unless(inst error("INSTANCE_FAILED"))']
        for prop, value in d['properties'].items():
            ptype = 'int' if isinstance(value, int) else 'string'
            val = str(value) if isinstance(value, int) else q(value)
            lines.append(f'dbReplaceProp(inst {q(prop)} "{ptype}" {val})')
        for j, (term, node) in enumerate(zip(d['terminals'], d['nodes'])):
            node = 'gnd!' if node == '0' else node
            lines.append(f'gConnect(cv inst master {q(term)} {q(node)} {j})')
            expected.append((d['instance'], term, node))
    lines += ['gm=dbOpenCellViewByType("analogLib" "gnd" "symbol" "schematicSymbol" "r")',
              'gi=schCreateInst(cv gm "GND0" list(-2 -1) "R0")',
              'schCheck(cv)', 'dbSave(cv)', 'dbClose(cv)', 'println("BUILD_PASSED")', 'exit()']
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
    export, manifest = export_program(t, c)
    return {'compiled.json': json.dumps(c), 'build.il': '\n'.join(lines), 'probe.il': '\n'.join(probe),
            'netlist.il': netlist, 'models.scs': models, 'ideal_opamp.va': IDEAL_OPAMP,
            'expected.scs': render_netlist(task, c), 'export.il': export,
            'signals.json': json.dumps(manifest), 'capture_config.json': json.dumps(capture_config(t, c))}


def expression(s, c):
    if s['type'] == 'current':
        part = next(p for p in c['devices'] if p['id'] == s['component'])
        terminal = 'a' if part['type'] == 'diode' else 'p' if part['type'] == 'voltage_source' else 'sink' if part['type'] == 'current_source' else '1'
        return f'i({q(part["instance"]+":"+terminal)})'
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
openResults("@ROOT@/batch/psf")
'''


def export_program(task, c):
    lines, manifest = [EXPORT_HEADER], []
    for a in task['analyses']:
        kind = a['type']
        if kind != 'op':
            lines.append('selectResults("dc-dc")' if kind == 'dc' else f"selectResults('{kind})")
        for i, s in enumerate(task['signals']):
            filename = f'{kind}_s{i}.txt'
            if kind != 'op':
                lines.append(f'gExport("@ROOT@/evidence/{filename}" {expression(s,c)} {"t" if kind == "ac" else "nil"})')
            manifest.append({'analysis': kind, 'signal': s['id'], 'filename': filename, 'unit': 'V' if s['type'] == 'voltage' else 'A'})
    return '\n'.join(lines + ['println("EXPORT_DONE")', 'exit()']), manifest


def capture_config(task, c):
    kind = next((k for k in ('tran', 'ac', 'dc') if any(a['type'] == k for a in task['analyses'])), 'op')
    # OP values are shown as a flat two-point trace, explicitly labeled operating point.
    exprs = [expression(s, c) for s in task['signals']]
    if kind == 'ac':
        exprs = [f'mag({x})' for x in exprs]
    return {'cell': 'general', 'analysis': kind, 'expressions': exprs,
            'labels': [s['id'] + (' [AC magnitude]' if kind == 'ac' else ' [operating point]' if kind == 'op' else '') for s in task['signals']]}
