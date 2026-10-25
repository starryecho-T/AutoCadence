import assert from 'node:assert/strict'
import { test } from 'node:test'
import { build } from 'esbuild'
async function bundle(path) { const r = await build({ entryPoints: [path], bundle: true, write: false, platform: 'node', format: 'esm' }); return import('data:text/javascript;base64,' + Buffer.from(r.outputFiles[0].text).toString('base64')) }
const circuit = await bundle('src/generalCircuit.ts')

test('nmos circuits get their own family and component label', () => {
  assert.equal(circuit.COMPONENT_LABELS.nmos, 'NMOS')
  const task = { title: '通用电路仿真', components: [{ type: 'nmos' }], analyses: [{ type: 'dc' }] }
  assert.equal(circuit.circuitTitle(task), 'NMOS 电路 · 直流扫描')
  // Existing family precedence stays intact when nmos is combined with other devices.
  assert.equal(circuit.circuitTitle({ ...task, components: [{ type: 'pmos' }, { type: 'nmos' }] }), 'CMOS 电路 · 直流扫描')
  assert.equal(circuit.circuitTitle({ ...task, components: [{ type: 'bjt' }, { type: 'nmos' }] }), 'BJT 晶体管电路 · 直流扫描')
  assert.equal(circuit.circuitTitle({ ...task, components: [{ type: 'pmos' }] }), 'PMOS 电路 · 直流扫描')
})

test('mos pin labels cover drain/gate/source and the bulk current terminal', () => {
  assert.equal(circuit.PIN_LABELS.d, '漏极')
  assert.equal(circuit.PIN_LABELS.g, '栅极')
  assert.equal(circuit.PIN_LABELS.s, '源极')
  assert.equal(circuit.PIN_LABELS.b, '基极 / 衬底')
  assert.equal(circuit.PIN_LABELS.bulk, '衬底')
})

test('nmos circuits pass the editor guard that parses saved circuit JSON', () => {
  const task = { title: 'NMOS 电路 · 直流扫描', components: [{ id: 'M1', type: 'nmos', pins: { d: 'drain', g: 'gate', s: '0', b: '0' }, model: 'generic_nmos' }], analyses: [{ type: 'dc' }], signals: [{ id: 's1', type: 'current' }] }
  const parsed = circuit.editableCircuit(JSON.stringify(task))
  assert.equal(parsed?.components[0].type, 'nmos')
  assert.equal(parsed?.components[0].model, 'generic_nmos')
})
