import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFile } from 'node:fs/promises'
import { transform } from 'esbuild'

const source = await readFile(new URL('../src/generalCircuit.ts', import.meta.url), 'utf8')
const { code } = await transform(source, { loader: 'ts', format: 'esm' })
const { circuitTitle, COMPONENT_LABELS } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'))

test('NMOS and mixed CMOS circuits have usable result labels', () => {
  const circuit = types => ({ title: '通用电路仿真', components: types.map(type => ({ type })), analyses: [{ type: 'dc' }] })
  assert.equal(circuitTitle(circuit(['nmos'])), 'NMOS 电路 · 直流扫描')
  assert.equal(circuitTitle(circuit(['nmos', 'pmos'])), 'CMOS 电路 · 直流扫描')
  assert.equal(COMPONENT_LABELS.nmos, 'NMOS')
})
