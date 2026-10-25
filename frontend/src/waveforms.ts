export interface WaveSeries { analysis: string; signal: string; unit: string; original_samples: number; rows: number[][]; case?: string; role?: string; parameters?: Record<string, number>; source?: string }
export const waveKey = (s: WaveSeries) => `${s.case ?? 'base'}.${s.analysis}.${s.signal}`
export type WaveMode = 'real' | 'imag' | 'magnitude' | 'phase'
export function waveValue(row: number[], mode: WaveMode): number {
  if (row.length < 3) return row[1]
  return mode === 'imag' ? row[2] : mode === 'magnitude' ? Math.hypot(row[1], row[2]) : mode === 'phase' ? Math.atan2(row[2], row[1]) * 180 / Math.PI : row[1]
}
export function waveUnit(s: WaveSeries, mode: WaveMode): string { return s.analysis === 'ac' && s.rows[0]?.length === 3 && mode === 'phase' ? '°' : s.unit }
export function validateWaveforms(value: unknown): WaveSeries[] {
  const series = (value as { series?: unknown } | null)?.series
  if (!Array.isArray(series) || series.length > 1600) throw new Error('波形数据格式异常')
  const keys = new Set<string>()
  for (const s of series) {
    if (!s || !['ac', 'dc', 'tran', 'op'].includes(s.analysis) || typeof s.signal !== 'string' || typeof s.unit !== 'string' ||
      !Number.isInteger(s.original_samples) || !Array.isArray(s.rows) || !s.rows.length || s.rows.length > 200000 || s.original_samples < s.rows.length ||
      !s.rows.every((r: unknown) => Array.isArray(r) && r.length === (s.analysis === 'ac' && s.unit !== 'dB' ? 3 : 2) && r.every(x => typeof x === 'number' && Number.isFinite(x)) && (s.analysis !== 'ac' || r[0] > 0))) throw new Error('波形数据含有缺失、无效数值或频率')
    if (s.case !== undefined && (typeof s.case !== 'string' || !/^(base|s\d{3}|yp1|yp2|ypcheck|equivalent)$/.test(s.case))) throw new Error('扫描组编号异常')
    const key = waveKey(s)
    if (keys.has(key)) throw new Error('波形数据包含重复的信号')
    keys.add(key)
    const direction = Math.sign((s.rows[1]?.[0] ?? s.rows[0][0]) - s.rows[0][0])
    if (s.rows.some((r: number[], i: number) => i > 0 && Math.sign(r[0] - s.rows[i - 1][0]) !== direction) || (s.rows.length > 1 && !direction)) throw new Error('波形横轴顺序异常')
  }
  return series
}
export function groupWaveforms(series: WaveSeries[]): WaveSeries[][] {
  const groups = new Map<string, WaveSeries[]>()
  for (const s of series.filter(s => s.analysis !== 'op')) { const key = `${s.analysis}:${s.unit}`; groups.set(key, [...(groups.get(key) ?? []), s]) }
  return [...groups.values()]
}
export function sampleWave(rows: number[][], limit = 1000): number[][] {
  if (rows.length <= limit) return rows
  const indexes = new Set([0, rows.length - 1]), width = Math.ceil(rows.length / (limit / 2))
  for (let start = 0; start < rows.length; start += width) {
    let low = start, high = start
    for (let i = start + 1; i < Math.min(start + width, rows.length); i++) { if (rows[i][1] < rows[low][1]) low = i; if (rows[i][1] > rows[high][1]) high = i }
    indexes.add(low); indexes.add(high)
  }
  return [...indexes].sort((a, b) => a - b).map(i => rows[i])
}
export function parseNumericWave(text: string, analysis: string, signal: string, unit: string): WaveSeries {
  const rows = text.trim().split(/\r?\n/).filter(x => x.trim()).map(line => line.trim().split(/\s+/).map(Number))
  const series = validateWaveforms({ series: [{ analysis, signal, unit, original_samples: rows.length, rows }] })[0]
  return { ...series, rows: sampleWave(series.rows) }
}
/** 对整组波形做与 txt 路径一致的抽样；纯函数，不修改入参，original_samples 保留完整点数。 */
export function sampleWaveforms(series: WaveSeries[]): WaveSeries[] {
  return series.map(s => ({ ...s, rows: sampleWave(s.rows) }))
}
export function waveBounds(series: WaveSeries[], mode: WaveMode) {
  let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity
  for (const s of series) for (const row of s.rows) {
    const x = s.analysis === 'ac' ? Math.log10(row[0]) : row[0], y = waveValue(row, mode)
    xmin = Math.min(xmin, x); xmax = Math.max(xmax, x); ymin = Math.min(ymin, y); ymax = Math.max(ymax, y)
  }
  const padding = ymax === ymin ? Math.max(Math.abs(ymin) * .05, 1e-9) : (ymax - ymin) * .07
  return { xmin, xmax, low: ymin - padding, high: ymax + padding }
}
