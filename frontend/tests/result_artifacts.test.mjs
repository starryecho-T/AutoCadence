import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFile } from 'node:fs/promises'
import { transform } from 'esbuild'

const source = await readFile(new URL('../src/resultArtifacts.ts', import.meta.url), 'utf8')
const { code } = await transform(source, { loader: 'ts', format: 'esm' })
const { imageLabel, resultImages } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'))

test('all browser images remain visible once; raw XWD stays out of the image set', () => {
  const artifact = (id, filename, kind, mime = 'image/png') => ({ id, filename, kind, mime, url: `/artifacts/${id}` })
  const native = artifact('native-wave', 'waveform_native.png', 'waveform')
  const window = artifact('window-wave', 'waveform_window.png', 'waveform')
  const schematic = artifact('window-sch', 'schematic_window.png', 'schematic')
  const schematicNative = artifact('native-sch', 'schematic_native.png', 'schematic')
  const xwd = artifact('raw-wave', 'waveform_window.xwd', 'data', 'image/x-xwindowdump')
  const { images, shots, waveform } = resultImages([native, xwd, schematicNative, window, schematic, native])
  assert.equal(images.length, 4)
  assert.deepEqual(shots.map(a => a.filename), ['schematic_window.png', 'waveform_window.png', 'waveform_native.png', 'schematic_native.png'])
  assert.equal(waveform, window)
  assert.equal(imageLabel(native), 'Cadence 波形原生导出')
  assert.equal(imageLabel(window), 'ViVA 波形窗口截图')
})

test('analysis screenshots and native exports have distinct labels and all appear', () => {
  const artifact = (id, filename) => ({ id, filename, kind: 'waveform', mime: 'image/png', url: `/artifacts/${id}` })
  const items = [
    artifact('tran-native', 'waveform_tran_native.png'),
    artifact('dc-window', 'waveform_dc_window.png'),
    artifact('legacy', 'waveform_window.png'),
    artifact('ac-window', 'waveform_ac_window.png'),
    artifact('op-window', 'waveform_op_window.png'),
    artifact('tran-window', 'waveform_tran_window.png'),
    artifact('ac-native', 'waveform_ac_native.png')
  ]
  const { shots, waveform } = resultImages(items)
  assert.equal(waveform.filename, 'waveform_window.png')
  assert.deepEqual(shots.map(a => a.filename), [
    'waveform_window.png', 'waveform_ac_window.png', 'waveform_dc_window.png',
    'waveform_op_window.png', 'waveform_tran_window.png',
    'waveform_ac_native.png', 'waveform_tran_native.png'
  ])
  assert.equal(imageLabel(items[1]), 'ViVA DC 波形窗口截图')
  assert.equal(imageLabel(items[4]), 'ViVA 工作点窗口截图')
  assert.equal(imageLabel(items[0]), 'Cadence 瞬态波形原生导出')
})

test('run artifact paths keep the real window captures first', () => {
  const artifact = filename => ({ id: filename, filename: `evidence/${filename}`, kind: filename.startsWith('schematic') ? 'schematic' : 'waveform', mime: 'image/png', url: `/artifacts/${filename}` })
  const { schematic, waveform, shots } = resultImages([
    artifact('waveform_ac_native.png'), artifact('schematic_native.png'),
    artifact('waveform_tran_window.png'), artifact('waveform_window.png'),
    artifact('schematic_window.png'), artifact('waveform_ac_window.png')
  ])
  assert.equal(schematic.filename, 'evidence/schematic_window.png')
  assert.equal(waveform.filename, 'evidence/waveform_window.png')
  assert.deepEqual(shots.map(a => a.filename), [
    'evidence/schematic_window.png', 'evidence/waveform_window.png',
    'evidence/waveform_ac_window.png', 'evidence/waveform_tran_window.png',
    'evidence/waveform_ac_native.png', 'evidence/schematic_native.png'
  ])
  assert.equal(imageLabel(shots[2]), 'ViVA AC 波形窗口截图')
})
