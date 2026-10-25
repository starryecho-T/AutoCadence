import type { Artifact } from './types'

function imageName(artifact: Artifact): string {
  return artifact.filename?.split('/').pop() ?? ''
}

function previewableImage(artifact: Artifact): boolean {
  if (!artifact.url || /\.xwd$/i.test(artifact.filename ?? '')) return false
  return /\.(png|jpe?g|gif|webp|svg|avif)$/i.test(artifact.filename ?? '')
    || /^image\/(png|jpeg|gif|webp|svg\+xml|avif)$/i.test(artifact.mime ?? '')
    || (artifact.url.startsWith('data:image/') && !artifact.mime && !artifact.filename)
}

export function imageLabel(artifact: Artifact): string {
  const labels: Record<string, string> = {
    'schematic_window.png': 'Virtuoso 原理图窗口截图',
    'waveform_window.png': 'ViVA 波形窗口截图',
    'schematic_native.png': 'Cadence 原理图原生导出',
    'waveform_native.png': 'Cadence 波形原生导出'
  }
  const name = imageName(artifact)
  const analysisImage = /^waveform_(ac|dc|op|tran)_(window|native)\.png$/i.exec(name)
  if (analysisImage) {
    const analysis = { ac: 'AC 波形', dc: 'DC 波形', op: '工作点', tran: '瞬态波形' }[analysisImage[1].toLowerCase() as 'ac' | 'dc' | 'op' | 'tran']
    return analysisImage[2].toLowerCase() === 'window' ? `ViVA ${analysis}窗口截图` : `Cadence ${analysis}原生导出`
  }
  return labels[name] ?? artifact.label ?? artifact.filename ?? (artifact.kind === 'schematic' ? '电路原理图' : '仿真波形')
}

export function resultImages(artifacts: Artifact[]) {
  const images = artifacts.filter(previewableImage).filter((a, index, all) => all.findIndex(other => other.id === a.id) === index)
  const schematic = images.find(a => imageName(a) === 'schematic_window.png') ?? images.find(a => a.kind === 'schematic')
  const waveform = images.find(a => imageName(a) === 'waveform_window.png') ?? images.find(a => /^waveform_(ac|dc|op|tran)_window\.png$/i.test(imageName(a))) ?? images.find(a => a.kind === 'waveform')
  const analysisOrder = ['ac', 'dc', 'op', 'tran']
  const shotOrder = (a: Artifact): number => {
    const name = imageName(a)
    if (a === schematic) return 0
    if (a === waveform) return 1
    const match = /^waveform_(ac|dc|op|tran)_(window|native)\.png$/i.exec(name)
    if (match) return (match[2].toLowerCase() === 'window' ? 2 : 8) + analysisOrder.indexOf(match[1].toLowerCase())
    if (name === 'waveform_native.png') return 7
    if (name === 'schematic_native.png') return 12
    return 13
  }
  const shots = [...images].sort((a, b) => shotOrder(a) - shotOrder(b))
  return { images, schematic, waveform, shots }
}
