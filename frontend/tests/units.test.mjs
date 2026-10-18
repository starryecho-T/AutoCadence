import assert from 'node:assert/strict'
import { test } from 'node:test'
import { build } from 'esbuild'
const { outputFiles } = await build({ entryPoints: ['src/units.ts'], bundle: true, write: false, platform: 'node', format: 'esm' })
const { PARAMETERS, chooseUnit, displayInUnit, toSI } = await import('data:text/javascript;base64,' + Buffer.from(outputFiles[0].text).toString('base64'))

test('engineering input produces exact API values for RC, pulse and scan units', () => {
  assert.equal(toSI('16', 1e3), 16000)
  assert.equal(toSI('10', 1e-9), 1e-8)
  assert.equal(toSI('0.01', 1e-6), 1e-8)
  assert.equal(toSI('8.301', 1e-3), .008301)
  assert.equal(toSI('1', 1e6), 1e6)
  assert.equal(toSI('', 1e3), '')
  assert.equal(toSI('-2', 1e3), -2000, 'validation, not conversion, rejects negative components')
})
test('changing display units preserves small values and does not change backend bounds', () => {
  for (const [key, values] of Object.entries({ r_ohm: [10, 16000, 1e6], c_farad: [1e-12, 1e-8, .001], period_s: [1e-5, .004, .1] })) {
    const units = PARAMETERS[key].units
    for (const value of values) {
      const preferred = chooseUnit(value, units)
      assert.ok(Number(displayInUnit(value, preferred.scale)) >= 1)
      for (const unit of units) assert.equal(toSI(displayInUnit(value, unit.scale), unit.scale), value)
    }
  }
})
