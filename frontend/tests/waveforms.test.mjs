import assert from 'node:assert/strict'
import { test } from 'node:test'
import { build } from 'esbuild'
async function bundle(path) { const r = await build({ entryPoints: [path], bundle: true, write: false, platform: 'node', format: 'esm' }); return import('data:text/javascript;base64,' + Buffer.from(r.outputFiles[0].text).toString('base64')) }
const wave = await bundle('src/waveforms.ts')

const tranSeries = (rows, extra = {}) => ({ analysis: 'tran', signal: 'V(out)', unit: 'V', original_samples: rows.length, rows, ...extra })

test('sampleWaveforms downsamples large series like the txt path and preserves metadata', () => {
  const rows = Array.from({ length: 5000 }, (_, i) => [i * 1e-6, Math.sin(i / 100)])
  const series = [tranSeries(rows), tranSeries([[0, 1]], { analysis: 'op' })]
  const sampled = wave.sampleWaveforms(series)
  assert.equal(sampled.length, 2)
  assert.ok(sampled[0].rows.length <= 1100, 'each series is capped near the sampling limit')
  assert.equal(sampled[0].original_samples, 5000, 'original_samples keeps the full point count')
  assert.deepEqual(sampled[0].rows[0], rows[0])
  assert.deepEqual(sampled[0].rows.at(-1), rows.at(-1))
  assert.equal(Math.min(...sampled[0].rows.map((r) => r[1])), Math.min(...rows.map((r) => r[1])), 'global minimum survives sampling')
  assert.equal(Math.max(...sampled[0].rows.map((r) => r[1])), Math.max(...rows.map((r) => r[1])), 'global maximum survives sampling')
  assert.deepEqual(sampled[1].rows, [[0, 1]], 'single-row op series stay untouched')
  assert.equal(wave.waveKey(sampled[0]), wave.waveKey(series[0]), 'wave identity is preserved')
  assert.deepEqual(series[0].rows.length, 5000, 'input series are not mutated')
})

test('sampleWaveforms is idempotent so JSON and txt paths converge on identical rows', () => {
  const rows = Array.from({ length: 3000 }, (_, i) => [i, (i % 97) - 48])
  const once = wave.sampleWaveforms([tranSeries(rows)])
  const twice = wave.sampleWaveforms(once)
  assert.deepEqual(twice, once)
  assert.ok(once[0].rows.length >= 2 && once[0].rows.length <= 1100)
  const jsonShaped = wave.validateWaveforms({ series: [{ analysis: 'tran', signal: 'V(out)', unit: 'V', original_samples: 3000, rows: once[0].rows }] })
  assert.equal(jsonShaped.length, 1, 'sampled rows still pass waveform validation')
})

test('sampleWaveforms keeps AC three-column rows and waveBounds readable after sampling', () => {
  const rows = Array.from({ length: 4000 }, (_, i) => [10 ** (i / 1000), 3, -4])
  const sampled = wave.sampleWaveforms([{ analysis: 'ac', signal: 'V(out)', unit: 'V', original_samples: 4000, rows }])
  assert.ok(sampled[0].rows.every((r) => r.length === 3), 'row shape is unchanged')
  const bounds = wave.waveBounds(sampled, 'magnitude')
  assert.ok(Number.isFinite(bounds.xmin) && Number.isFinite(bounds.high) && bounds.high > bounds.low)
})
