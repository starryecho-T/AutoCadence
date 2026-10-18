import type { ParseResult, TaskSpec } from './types'
import { ANALYSIS_DEFAULTS } from './contract'

const NUMBER = '[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?'
const SCALE: Record<string, number> = { '': 1, k: 1e3, K: 1e3, M: 1e6, m: 1e-3, u: 1e-6, µ: 1e-6, μ: 1e-6, n: 1e-9, p: 1e-12 }
const E24 = [1, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2, 2.2, 2.4, 2.7, 3, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]

/** Same bounded E24/common-capacitor search as backend/skill/vai_client.py. */
export function deriveRC(target: number) {
  if (!Number.isFinite(target) || target <= 0) throw new Error('目标截止频率必须是大于 0 的有限数值')
  const capacitors: number[] = []
  for (let exponent = -12; exponent <= -4; exponent++) {
    const bases = exponent === -4 ? [1, 2.2, 4.7] : exponent === -5 ? [1, 2.2, 4.7] : exponent === -7 || exponent === -6 ? [1, 1.5, 2.2, 3.3, 4.7, 6.8] : [1, 2.2, 3.3, 4.7, 6.8]
    for (const base of bases) capacitors.push(Number((base * 10 ** exponent).toPrecision(12)))
  }
  let best: { r: number; c: number; fc: number; error: number; distance: number } | undefined
  for (let decade = 0; decade <= 5; decade++) {
    for (const base of E24) {
      const r = base * 10 ** decade
      if (r < 10 || r > 1e6) continue
      for (const c of capacitors) {
        const fc = 1 / (2 * Math.PI * r * c), error = Math.abs(fc / target - 1)
        const distance = Math.abs(Math.log10(r) - 4)
        if (!best || error < best.error - 1e-12 || (Math.abs(error - best.error) <= 1e-12 && distance < best.distance)) {
          best = { r, c, fc, error, distance }
        }
      }
    }
  }
  if (!best || best.error > .02) throw new Error('在当前元件范围内找不到误差 ≤ 2% 的标准 R/C 组合，请手动指定元件')
  return best
}

/** Read only explicit, unit-bearing quantities. Conflicting values stay blank. */
function quantity(text: string, pattern: string): number | undefined | null {
  const values = [...text.matchAll(new RegExp(pattern, 'gi'))]
    .map((m) => Number(m[1]) * SCALE[m[2] ?? ''])
  if (!values.length) return undefined
  return values.every((v) => Number.isFinite(v) && v === values[0]) ? values[0] : null
}

export function planQuestion(text: string, parsed: ParseResult): ParseResult {
  const p: Record<string, number | string> = {
    r_ohm: '', c_farad: '', ...ANALYSIS_DEFAULTS, ...parsed.task?.params
  }
  const defaults: Record<string, unknown> = { ...ANALYSIS_DEFAULTS }
  const hints = [...(parsed.hints ?? [])]
  const missing = new Set(parsed.missing ?? [])
  const explicitlySet = new Set<string>()
  function set(key: string, value: number | undefined | null) {
    if (value === undefined) return
    p[key] = value ?? ''
    explicitlySet.add(key)
    delete defaults[key]
    if (value === null) hints.push(`${key} 出现多个不同数值，请手动确定采用值。`)
  }
  // When the backend has no complete TaskSpec, recover only unambiguous explicit R/C.
  if (!parsed.task) {
    set('r_ohm', quantity(text, `(?:\\bR1?\\b|电阻(?:\\s*R1?)?)\\s*(?:=|:|：|为|是|取)?\\s*(${NUMBER})\\s*([kKMm]?)\\s*(?:Ω|Ω|ohms?|欧姆|欧)(?![A-Za-z])`))
    set('c_farad', quantity(text, `(?:\\bC1?\\b|电容(?:\\s*C1?)?)\\s*(?:=|:|：|为|是|取)?\\s*(${NUMBER})\\s*([munpµμ]?)\\s*(?:F|farads?|法拉|法)(?![A-Za-z])`))
  }
  const target = quantity(text, `(?:截止频率|\\bfc\\b|cutoff\\s+frequency)\\s*(?:约为|约|为|是|=|:|：|of|is)?\\s*(${NUMBER})\\s*([kKMm]?)\\s*Hz`)
  let derivation: ParseResult['derivation']
  // Never replace an explicit or ambiguous component with a guessed one.
  if (typeof target === 'number' && p.r_ohm === '' && p.c_farad === '' && !/(?:\b[RC]1?\s*[=:：]|电阻|电容)/i.test(text)) {
    const selected = deriveRC(target)
    p.r_ohm = selected.r; p.c_farad = selected.c
    derivation = { target_hz: target, achieved_hz: selected.fc, error_pct: selected.error * 100 }
    hints.push('根据目标截止频率，使用 E24 电阻与常用电容推导候选值；请确认后运行。')
  } else if (target === null) {
    hints.push('存在多个目标截止频率，请明确目标后重新解析。')
  }

  const timeFields: [string, string][] = [
    ['period_s', '周期|\\bperiod'], ['width_s', '脉宽|脉冲宽度|高电平宽度|\\bwidth'],
    ['rise_s', '上升时间|上升沿时间|\\brise'], ['fall_s', '下降时间|下降沿时间|\\bfall'],
    ['delay_s', '延迟|\\bdelay'], ['stop_s', '瞬态终点|瞬态时长|仿真时长'], ['max_step_s', '最大步长']
  ]
  for (const [key, label] of timeFields) {
    set(key, quantity(text, `(?:${label})\\s*(?:为|是|=|:|：|of|is)?\\s*(${NUMBER})\\s*([munpµμ]?)s(?![A-Za-z])`))
  }
  const pulseMatches = [...text.matchAll(new RegExp(`(${NUMBER})\\s*(?:V)?\\s*(?:到|至|→|~|～)\\s*(${NUMBER})\\s*V`, 'gi'))]
  if (pulseMatches.length) {
    const unique = (index: number) => pulseMatches.every((m) => m[index] === pulseMatches[0][index]) ? Number(pulseMatches[0][index]) : null
    set('low_v', unique(1)); set('high_v', unique(2))
  }
  set('low_v', quantity(text, `(?:低电平|\\blow)\\s*(?:为|=|:|：)?\\s*(${NUMBER})\\s*()V`))
  set('high_v', quantity(text, `(?:高电平|\\bhigh)\\s*(?:为|=|:|：)?\\s*(${NUMBER})\\s*()V`))
  const ranges = [...text.matchAll(new RegExp(`(${NUMBER})\\s*([kKMm]?)Hz\\s*(?:到|至|~|～|—|–|-)\\s*(${NUMBER})\\s*([kKMm]?)Hz`, 'gi'))]
  if (ranges.length) {
    const start = ranges.map((m) => Number(m[1]) * SCALE[m[2]])
    const stop = ranges.map((m) => Number(m[3]) * SCALE[m[4]])
    set('freq_min_hz', start.every((v) => v === start[0]) ? start[0] : null)
    set('freq_max_hz', stop.every((v) => v === stop[0]) ? stop[0] : null)
  }
  // Suggested analysis settings may change; explicit question requirements never do.
  if (typeof p.r_ohm === 'number' && p.r_ohm > 0 && typeof p.c_farad === 'number' && p.c_farad > 0) {
    const tau = p.r_ohm * p.c_farad, fc = 1 / (2 * Math.PI * tau)
    if (!explicitlySet.has('freq_min_hz')) p.freq_min_hz = Math.min(10, fc / 10)
    if (!explicitlySet.has('freq_max_hz')) p.freq_max_hz = Math.max(1e6, fc * 10)
    if (!explicitlySet.has('stop_s')) p.stop_s = Math.max(.004201, Number(p.delay_s) + 2.075 * Number(p.period_s))
    if (!explicitlySet.has('max_step_s')) p.max_step_s = Math.min(1e-6, tau / 20, Number(p.period_s) / 200, Number(p.width_s) / 20)
  }
  for (const key of Object.keys(defaults)) defaults[key] = p[key]
  if (p.r_ohm !== '') missing.delete('r_ohm')
  if (p.c_farad !== '') missing.delete('c_f')
  const task: TaskSpec = { ...parsed.task, contract: '1.0', kind: 'rc_lowpass', source_text: text, params: p }
  hints.push('仅自动提取带单位的 R/C、截止频率、脉冲电平/时间和扫描范围。请核对其他题目条件；分析建议值均可编辑。')
  return { ...parsed, task, missing: [...missing], defaults, hints, derivation }
}
